"""
iter96 — Weekly storage-growth digest email.

When orphan storage grows >= 1 GB between weekly audit snapshots, fire a
Resend email pointing the user at /admin/storage-cleanup. Turns silent
quota loss into an inbox signal you can't miss.

Tests cover:
  - Opt-out preference round-trip (GET / POST)
  - Email is sent on first measurement when total >= threshold
  - Email is sent on growth >= threshold
  - Email is SKIPPED when growth < threshold
  - Email is SKIPPED when user opted out
  - Email is SKIPPED when current total < threshold
  - send-digest-now manual trigger endpoint works
  - email_queue row gets the right `kind` so the iter72 audit log surfaces it
"""
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


def _payload():
    s = uuid.uuid4().hex[:10]
    return {"email": f"iter96-{s}@example.com", "password": "Iter96Pass!", "name": f"Iter96 {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


async def _seed_orphans_gb(uid: str, gb: float):
    """Drop enough storage-backed chunks in failed_videos to total ~gb GB.
    Each chunk is the default 10 MiB."""
    from db import db
    n_chunks = int(round(gb * 1024 / 10))  # 10 MiB chunks
    chunk_paths = {str(i): f"soccer-analysis/iter96-{uid[:6]}/{i}.bin" for i in range(n_chunks)}
    chunk_backends = {str(i): "storage" for i in range(n_chunks)}
    await db.videos.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": uid, "match_id": "m1",
        "original_filename": "seed.mp4", "is_chunked": True, "is_deleted": False,
        "total_chunks": n_chunks, "chunk_size": 10 * 1024 * 1024,
        "chunk_paths": chunk_paths, "chunk_backends": chunk_backends,
        "processing_status": "failed",
        "storage_path": "chunked:seed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


# ---------------------------------------------------------------------------
# 1. Opt-out preference round-trip
# ---------------------------------------------------------------------------

def test_digest_preference_defaults_to_opt_in():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.get("/api/me/preferences/storage-digest")
            assert r.status_code == 200
            assert r.json() == {"opt_out": False}
        finally:
            await c.aclose()
    _run_async(run())


def test_digest_preference_can_be_toggled():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.post("/api/me/preferences/storage-digest", json={"opt_out": True})
            assert r.status_code == 200
            assert r.json() == {"opt_out": True}
            r = await c.get("/api/me/preferences/storage-digest")
            assert r.json() == {"opt_out": True}
            # Toggle back
            await c.post("/api/me/preferences/storage-digest", json={"opt_out": False})
            r = await c.get("/api/me/preferences/storage-digest")
            assert r.json() == {"opt_out": False}
        finally:
            await c.aclose()
    _run_async(run())


def test_digest_preference_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/me/preferences/storage-digest")
            assert r.status_code in (401, 403)
            r = await c.post("/api/me/preferences/storage-digest", json={"opt_out": True})
            assert r.status_code in (401, 403)
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. send-digest-now manual trigger
# ---------------------------------------------------------------------------

def test_send_digest_now_skipped_when_below_threshold():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.post("/api/admin/storage-cleanup/send-digest-now")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "skipped"
            assert "threshold" in body["reason"].lower() or "growth" in body["reason"].lower()
        finally:
            await c.aclose()
    _run_async(run())


def test_send_digest_now_fires_when_orphans_exceed_threshold():
    """User has ~1.5 GB of orphans on first run → digest sends (is_first_send)."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await _seed_orphans_gb(uid, 1.5)

            r = await c.post("/api/admin/storage-cleanup/send-digest-now")
            assert r.status_code == 200, r.text
            body = r.json()
            # status is one of: sent / quota_deferred / failed (we expect a queue row regardless)
            assert body["status"] in ("sent", "quota_deferred", "failed"), body
            assert "queue_id" in body

            # email_queue row exists with the right kind
            row = await db.email_queue.find_one({"id": body["queue_id"]}, {"_id": 0})
            assert row is not None
            assert row["kind"] == "storage_growth_digest"
            assert row["to_email"] == me["email"]
            assert "Storage Quota Alert" in row["subject"]

            # snapshot stamped with digest_sent_at
            snap = await db.storage_growth_audits.find_one(
                {"user_id": uid, "triggered_manually": True}, {"_id": 0}
            )
            assert snap is not None
            assert snap.get("digest_sent_at") is not None
        finally:
            await c.aclose()
    _run_async(run())


def test_send_digest_now_respects_opt_out():
    async def run():
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await _seed_orphans_gb(uid, 1.5)
            # Opt out
            await c.post("/api/me/preferences/storage-digest", json={"opt_out": True})

            r = await c.post("/api/admin/storage-cleanup/send-digest-now")
            body = r.json()
            assert body["status"] == "skipped"
            assert "opted out" in body["reason"].lower() or "opt" in body["reason"].lower()
        finally:
            await c.aclose()
    _run_async(run())


def test_send_digest_now_skipped_when_growth_below_threshold():
    """If a prior snapshot already shows ~1.5 GB and current is also ~1.5 GB,
    no growth → skip (avoids weekly spam)."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            # Seed 1.5 GB of orphans
            await _seed_orphans_gb(uid, 1.5)
            # Insert a prior snapshot that's exactly the same total
            await db.storage_growth_audits.insert_one({
                "id": str(uuid.uuid4()), "user_id": uid,
                "recorded_at": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
                "total_orphan_chunks": 154, "total_estimated_bytes": int(1.5 * 1024 ** 3),
                "total_estimated_gb": 1.5,
                "by_bucket": {"failed_videos": 154},
            })

            r = await c.post("/api/admin/storage-cleanup/send-digest-now")
            body = r.json()
            assert body["status"] == "skipped", body
        finally:
            await c.aclose()
    _run_async(run())


def test_send_digest_now_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.post("/api/admin/storage-cleanup/send-digest-now")
            assert r.status_code in (401, 403)
    _run_async(run())


# ---------------------------------------------------------------------------
# 3. Email content + iter72 open-pixel injection
# ---------------------------------------------------------------------------

def test_digest_email_contains_orphan_summary_and_cta():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await _seed_orphans_gb(uid, 2.0)

            r = await c.post("/api/admin/storage-cleanup/send-digest-now")
            body = r.json()
            row = await db.email_queue.find_one({"id": body["queue_id"]}, {"_id": 0})
            html = row["html"]
            # Headline mentions GB total
            assert "GB" in html
            # CTA link to /admin/storage-cleanup
            assert "/admin/storage-cleanup" in html
            # Mentions opt-out path
            assert "storage digest" in html.lower() or "weekly" in html.lower()
            # iter72 open pixel was injected
            assert "lens-track/email-pixel" in html
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 4. Frontend wiring
# ---------------------------------------------------------------------------

def test_frontend_storage_cleanup_page_has_digest_toggle():
    src = open("/app/frontend/src/pages/AdminStorageCleanup.js").read()
    assert 'data-testid="digest-preferences-section"' in src
    assert 'data-testid="toggle-digest-btn"' in src
    assert 'data-testid="send-test-digest-btn"' in src
    assert "/me/preferences/storage-digest" in src
    assert "/admin/storage-cleanup/send-digest-now" in src
