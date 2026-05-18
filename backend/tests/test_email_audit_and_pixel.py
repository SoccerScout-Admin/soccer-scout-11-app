"""
Tests for iter72: email open tracking + admin audit log.

Pixel endpoint (`GET /api/lens-track/email-pixel/{queue_id}.png`):
  - Returns a 200 + image/png regardless of whether queue_id exists (don't
    reveal valid IDs to scrapers).
  - When queue_id matches an existing email_queue row, sets `opened_at` on
    first hit and bumps `open_count` on subsequent hits.

Audit endpoint (`GET /api/admin/email-audit-log`):
  - Admin-only (401/403 otherwise).
  - Returns rows in newest-first order with the right summary fields.
  - `kind` query param filters down to a single template family.
  - Aggregates `sent`, `opened`, `open_rate`, and `by_kind` rollup.
"""
import os
import uuid
import requests
import asyncio
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

BASE_URL = os.environ.get("BASE_URL") or "https://scout-lens.preview.emergentagent.com"
ADMIN_EMAIL = "testcoach@demo.com"
ADMIN_PASS = "password123"


def _login():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASS},
        timeout=15,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _run_mongo(coro_factory):
    load_dotenv()

    async def _run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            return await coro_factory(db)
        finally:
            client.close()

    return asyncio.get_event_loop().run_until_complete(_run())


def _seed_email(queue_id, kind="compression_help", status="sent", opened=False):
    async def go(db):
        doc = {
            "id": queue_id,
            "to_email": "audit-sentinel@test.local",
            "subject": f"Sentinel: {kind}",
            "html": "<html><body>...</body></html>",
            "kind": kind,
            "metadata": {"sentinel": True},
            "status": status,
            "attempts": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "sent_at": datetime.now(timezone.utc).isoformat() if status == "sent" else None,
        }
        if opened:
            doc["opened_at"] = datetime.now(timezone.utc).isoformat()
            doc["open_count"] = 1
        await db.email_queue.insert_one(doc)
    _run_mongo(go)


def _cleanup(queue_id):
    _run_mongo(lambda db: db.email_queue.delete_many({"id": queue_id}))


# ---------------------------------------------------------------------------
# Pixel endpoint
# ---------------------------------------------------------------------------

def test_pixel_returns_png_for_unknown_id():
    """Unknown queue_ids must still return a 200 + PNG (no info leak about
    which IDs are valid). The 67-byte transparent PNG is the response body."""
    fake_id = f"eq-bogus-{uuid.uuid4().hex[:8]}"
    r = requests.get(f"{BASE_URL}/api/lens-track/email-pixel/{fake_id}.png",
                     timeout=10)
    assert r.status_code == 200
    assert r.headers.get("content-type") == "image/png"
    assert r.content.startswith(b"\x89PNG")  # PNG magic bytes


def test_pixel_marks_opened_at_on_first_hit():
    """First GET of the pixel for a real queue_id sets opened_at + open_count=1."""
    qid = f"eq-sentinel-{uuid.uuid4().hex[:8]}"
    _seed_email(qid)
    try:
        r = requests.get(f"{BASE_URL}/api/lens-track/email-pixel/{qid}.png", timeout=10)
        assert r.status_code == 200

        async def fetch(db):
            return await db.email_queue.find_one({"id": qid}, {"_id": 0})

        doc = _run_mongo(fetch)
        assert doc["opened_at"] is not None
        assert doc["last_opened_at"] is not None
        assert doc["open_count"] == 1
    finally:
        _cleanup(qid)


def test_pixel_bumps_open_count_on_repeat_hits():
    """Second+ opens bump open_count and last_opened_at WITHOUT overwriting
    the original opened_at — first-read latency stays preserved."""
    qid = f"eq-sentinel-{uuid.uuid4().hex[:8]}"
    _seed_email(qid)
    try:
        requests.get(f"{BASE_URL}/api/lens-track/email-pixel/{qid}.png", timeout=10)

        async def fetch(db):
            return await db.email_queue.find_one({"id": qid}, {"_id": 0})

        first = _run_mongo(fetch)
        first_opened_at = first["opened_at"]

        requests.get(f"{BASE_URL}/api/lens-track/email-pixel/{qid}.png", timeout=10)
        requests.get(f"{BASE_URL}/api/lens-track/email-pixel/{qid}.png", timeout=10)

        second = _run_mongo(fetch)
        assert second["opened_at"] == first_opened_at  # NOT overwritten
        assert second["open_count"] == 3
        assert second["last_opened_at"] >= first_opened_at
    finally:
        _cleanup(qid)


# ---------------------------------------------------------------------------
# Audit log endpoint
# ---------------------------------------------------------------------------

def test_audit_log_requires_admin():
    r = requests.get(f"{BASE_URL}/api/admin/email-audit-log", timeout=10)
    assert r.status_code in (401, 403)


def test_audit_log_returns_seeded_rows_with_kinds():
    """The audit log surfaces freshly-seeded emails and the by_kind rollup
    correctly attributes opens to template families."""
    headers = _login()
    q_compress = f"eq-audit-c-{uuid.uuid4().hex[:8]}"
    q_incomplete = f"eq-audit-i-{uuid.uuid4().hex[:8]}"
    _seed_email(q_compress, kind="compression_help", opened=True)
    _seed_email(q_incomplete, kind="incomplete_upload_help", opened=False)
    try:
        r = requests.get(f"{BASE_URL}/api/admin/email-audit-log?days=1",
                         headers=headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        # Find OUR seeded rows specifically
        ours = [row for row in body["rows"] if row["id"] in (q_compress, q_incomplete)]
        assert len(ours) == 2
        compress_row = next(r for r in ours if r["id"] == q_compress)
        incomplete_row = next(r for r in ours if r["id"] == q_incomplete)
        assert compress_row["kind"] == "compression_help"
        assert compress_row["opened_at"] is not None
        assert incomplete_row["kind"] == "incomplete_upload_help"
        assert incomplete_row["opened_at"] is None
        # Aggregate rollup must include our kinds
        assert "compression_help" in body["by_kind"]
        assert "incomplete_upload_help" in body["by_kind"]
    finally:
        _cleanup(q_compress)
        _cleanup(q_incomplete)


def test_audit_log_kind_filter_excludes_others():
    """When `kind=compression_help`, only that template family is returned."""
    headers = _login()
    q_compress = f"eq-audit-c2-{uuid.uuid4().hex[:8]}"
    q_incomplete = f"eq-audit-i2-{uuid.uuid4().hex[:8]}"
    _seed_email(q_compress, kind="compression_help")
    _seed_email(q_incomplete, kind="incomplete_upload_help")
    try:
        r = requests.get(
            f"{BASE_URL}/api/admin/email-audit-log?days=1&kind=compression_help",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200
        ids = [row["id"] for row in r.json()["rows"]]
        assert q_compress in ids
        assert q_incomplete not in ids
    finally:
        _cleanup(q_compress)
        _cleanup(q_incomplete)


# ---------------------------------------------------------------------------
# Pixel injection in HTML
# ---------------------------------------------------------------------------

def test_pixel_injected_into_outbound_html():
    """services.email_queue._inject_open_pixel must append the tracking pixel
    before the closing body tag, and the URL must embed the queue_id we
    pass in so opens are credited to the right email."""
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from services.email_queue import _inject_open_pixel
    sample_qid = "eq-sample-abc123"
    html = "<html><body><p>Hello</p></body></html>"
    out = _inject_open_pixel(html, sample_qid)
    if out == html:
        # The helper no-ops when PUBLIC_APP_URL / REACT_APP_BACKEND_URL aren't
        # set — accept that as long as we also re-test with a base URL stubbed
        os.environ["PUBLIC_APP_URL"] = "https://example.test"
        out = _inject_open_pixel(html, sample_qid)
    assert "<img" in out
    assert sample_qid in out
    # Pixel must land BEFORE </body>, not after
    pixel_pos = out.find("<img")
    body_close_pos = out.find("</body>")
    assert pixel_pos < body_close_pos
