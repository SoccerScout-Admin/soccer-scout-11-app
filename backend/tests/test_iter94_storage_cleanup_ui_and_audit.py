"""
iter94 — Storage cleanup UI + proactive leak tracking.

Two new backend surfaces wired below:
  1. `POST /admin/storage-cleanup/mark-orphans` — materialize the current
     orphan inventory into `orphan_chunks` so when Emergent ships DELETE,
     we have a paths-ledger to sweep immediately. Idempotent (upsert).
  2. `GET /admin/storage-cleanup/audit-history` — return the user's
     weekly storage-growth audits so the admin UI can render a trend
     line.

Plus a frontend grep guard: `pages/AdminStorageCleanup.js` must exist
and call both endpoints + the existing iter93 report endpoint.
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
    return {"email": f"iter94-{s}@example.com", "password": "Iter94Pass!", "name": f"Iter94 {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


# ---------------------------------------------------------------------------
# 1. mark-orphans auth + empty state
# ---------------------------------------------------------------------------

def test_mark_orphans_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.post("/api/admin/storage-cleanup/mark-orphans")
            assert r.status_code in (401, 403)
    _run_async(run())


def test_mark_orphans_empty_for_fresh_user():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.post("/api/admin/storage-cleanup/mark-orphans")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["newly_marked"] == 0
            assert body["refreshed"] == 0
            assert body["total_marked_now"] == 0
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. mark-orphans persists to `orphan_chunks` and is idempotent
# ---------------------------------------------------------------------------

def test_mark_orphans_persists_and_is_idempotent():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            # Seed: one dismissed session with 2 storage chunks
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "x.mp4",
                "file_size": 20 * 1024 * 1024, "status": "in_progress",
                "chunk_paths": {"0": "soccer-analysis/iter94/0.bin", "1": "soccer-analysis/iter94/1.bin"},
                "chunk_backends": {"0": "storage", "1": "storage"},
                "dismissed_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            r1 = await c.post("/api/admin/storage-cleanup/mark-orphans")
            assert r1.status_code == 200, r1.text
            b1 = r1.json()
            assert b1["newly_marked"] == 2
            assert b1["refreshed"] == 0
            assert b1["total_marked_now"] == 2

            # Verify rows in orphan_chunks
            count = await db.orphan_chunks.count_documents({"user_id": uid})
            assert count == 2

            # Re-running should refresh, not double-mark
            r2 = await c.post("/api/admin/storage-cleanup/mark-orphans")
            b2 = r2.json()
            assert b2["newly_marked"] == 0
            assert b2["refreshed"] == 2
            assert b2["total_marked_now"] == 2

            # Marked rows have the right shape
            doc = await db.orphan_chunks.find_one(
                {"user_id": uid, "path": "soccer-analysis/iter94/0.bin"}, {"_id": 0}
            )
            assert doc is not None
            assert doc["bucket"] == "dismissed_sessions"  # iter95 — bucket keys now used as-is
            assert doc["size_estimate"] == 10 * 1024 * 1024
            assert doc["marked_at"] is not None
            assert doc["last_seen_at"] is not None
            assert doc["purged_at"] is None
            assert "id" in doc
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 3. mark-orphans is cross-user isolated
# ---------------------------------------------------------------------------

def test_mark_orphans_cross_user_isolation():
    async def run():
        from db import db
        c_a = await _client(_payload())
        c_b = await _client(_payload())
        try:
            me_a = (await c_a.get("/api/auth/me")).json()
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": me_a["id"], "match_id": "ma", "filename": "a.mp4",
                "file_size": 10 * 1024 * 1024, "status": "in_progress",
                "chunk_paths": {"0": "soccer-analysis/a-iso/0.bin"},
                "chunk_backends": {"0": "storage"},
                "dismissed_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r_b = await c_b.post("/api/admin/storage-cleanup/mark-orphans")
            b = r_b.json()
            assert b["newly_marked"] == 0, "User B marked User A's chunks — cross-user leak!"
            assert b["total_marked_now"] == 0
        finally:
            await c_a.aclose()
            await c_b.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 4. audit-history empty + filters + isolation
# ---------------------------------------------------------------------------

def test_audit_history_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/admin/storage-cleanup/audit-history")
            assert r.status_code in (401, 403)
    _run_async(run())


def test_audit_history_empty_for_fresh_user():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.get("/api/admin/storage-cleanup/audit-history")
            assert r.status_code == 200
            body = r.json()
            assert body["audits"] == []
            assert body["days"] == 90
        finally:
            await c.aclose()
    _run_async(run())


def test_audit_history_returns_snapshots_in_window():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            now = datetime.now(timezone.utc)
            # Two recent snapshots + one ancient (outside default 90-day window)
            await db.storage_growth_audits.insert_many([
                {
                    "id": str(uuid.uuid4()), "user_id": uid,
                    "recorded_at": (now - timedelta(days=7)).isoformat(),
                    "total_orphan_chunks": 50, "total_estimated_gb": 0.5,
                    "by_bucket": {"dismissed_sessions": 50, "failed_videos": 0, "deleted_videos": 0, "lost_chunks": 0},
                    "total_estimated_bytes": 50 * 10 * 1024 * 1024,
                },
                {
                    "id": str(uuid.uuid4()), "user_id": uid,
                    "recorded_at": (now - timedelta(days=14)).isoformat(),
                    "total_orphan_chunks": 30, "total_estimated_gb": 0.3,
                    "by_bucket": {"dismissed_sessions": 30, "failed_videos": 0, "deleted_videos": 0, "lost_chunks": 0},
                    "total_estimated_bytes": 30 * 10 * 1024 * 1024,
                },
                {
                    "id": str(uuid.uuid4()), "user_id": uid,
                    "recorded_at": (now - timedelta(days=200)).isoformat(),
                    "total_orphan_chunks": 5, "total_estimated_gb": 0.05,
                    "by_bucket": {"dismissed_sessions": 5, "failed_videos": 0, "deleted_videos": 0, "lost_chunks": 0},
                    "total_estimated_bytes": 5 * 10 * 1024 * 1024,
                },
            ])

            r = await c.get("/api/admin/storage-cleanup/audit-history?days=30")
            body = r.json()
            assert len(body["audits"]) == 2, (
                f"Expected 2 snapshots in last 30 days, got {len(body['audits'])}"
            )
            # Ordered oldest → newest
            assert body["audits"][0]["total_orphan_chunks"] == 30
            assert body["audits"][1]["total_orphan_chunks"] == 50
        finally:
            await c.aclose()
    _run_async(run())


def test_audit_history_cross_user_isolation():
    async def run():
        from db import db
        c_a = await _client(_payload())
        c_b = await _client(_payload())
        try:
            me_a = (await c_a.get("/api/auth/me")).json()
            await db.storage_growth_audits.insert_one({
                "id": str(uuid.uuid4()), "user_id": me_a["id"],
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "total_orphan_chunks": 99, "total_estimated_gb": 1.0,
                "by_bucket": {"dismissed_sessions": 99, "failed_videos": 0, "deleted_videos": 0, "lost_chunks": 0},
                "total_estimated_bytes": 99 * 10 * 1024 * 1024,
            })
            r_b = await c_b.get("/api/admin/storage-cleanup/audit-history")
            assert r_b.json()["audits"] == [], "User B saw User A's audits — cross-user leak!"
        finally:
            await c_a.aclose()
            await c_b.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 5. Frontend admin page exists and wires endpoints
# ---------------------------------------------------------------------------

def test_frontend_admin_storage_cleanup_page_exists():
    """The admin UI page must exist and reference every iter93 + iter94 endpoint."""
    p = "/app/frontend/src/pages/AdminStorageCleanup.js"
    assert os.path.exists(p), f"{p} missing"
    src = open(p).read()
    assert "/admin/storage-cleanup/report" in src, "page must fetch the iter93 report"
    assert "/admin/storage-cleanup/mark-orphans" in src, "page must call mark-orphans"
    assert "/admin/storage-cleanup/audit-history" in src, "page must call audit-history"
    # Copy-email-to-support button is the headline UX
    assert "support@emergent.sh" in src, "copy-to-clipboard email must target support@emergent.sh"
    # Testids for the testing agent
    assert 'data-testid="storage-cleanup-page"' in src
    assert 'data-testid="copy-support-email-btn"' in src
    assert 'data-testid="mark-orphans-btn"' in src


def test_frontend_app_js_mounts_storage_cleanup_route():
    src = open("/app/frontend/src/App.js").read()
    assert "AdminStorageCleanup" in src, "App.js must import the new page"
    assert "/admin/storage-cleanup" in src, "App.js must register the new route"
