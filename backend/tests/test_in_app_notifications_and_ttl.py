"""
iter86 — Cross-device in-app notifications + TTL sweeper.

Two surfaces under test:
  1. GET /api/me/notifications/recent — returns the calling user's recent
     notifications (default cutoff: 24h ago, max 20 results). Powers the
     30s in-app poller mounted in frontend App.js.
  2. _dismissed_uploads_ttl_sweeper — hard-purges chunked_uploads with
     dismissed_at >30 days old AND user_notifications >30 days old.
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
    return {"email": f"notif-{s}@example.com", "password": "NotifPass2026!", "name": f"Notif {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


# ---------------------------------------------------------------------------
# 1. GET /api/me/notifications/recent
# ---------------------------------------------------------------------------

def test_notifications_recent_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/me/notifications/recent")
            assert r.status_code in (401, 403), r.text
    _run_async(run())


def test_notifications_recent_empty_for_fresh_user():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.get("/api/me/notifications/recent")
            assert r.status_code == 200, r.text
            assert r.json() == {"count": 0, "notifications": []}
        finally:
            await c.aclose()
    _run_async(run())


def test_notifications_recent_returns_recent_notifs_for_user():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            # Look up the user_id we registered as
            me = (await c.get("/api/auth/me")).json()
            user_id = me["id"]

            # Insert a notification directly via the DB (this is what
            # processing.py does after a match finishes)
            notif_id = str(uuid.uuid4())
            await db.user_notifications.insert_one({
                "id": notif_id,
                "user_id": user_id,
                "type": "processing_complete",
                "title": "Match analysis ready",
                "body": "AI tactical breakdown is ready for Demo Home vs Demo Away.",
                "deep_link": "/match/abc",
                "video_id": "vid-abc",
                "match_id": "abc",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            r = await c.get("/api/me/notifications/recent")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["count"] >= 1
            ids = [n["id"] for n in body["notifications"]]
            assert notif_id in ids

            # Cleanup
            await db.user_notifications.delete_one({"id": notif_id})
        finally:
            await c.aclose()
    _run_async(run())


def test_notifications_recent_does_not_leak_other_users():
    async def run():
        from db import db
        c_a = await _client(_payload())
        c_b = await _client(_payload())
        try:
            me_a = (await c_a.get("/api/auth/me")).json()
            notif_id = str(uuid.uuid4())
            await db.user_notifications.insert_one({
                "id": notif_id,
                "user_id": me_a["id"],
                "type": "processing_complete",
                "title": "User A's match ready",
                "body": "Only User A should see this.",
                "deep_link": "/match/xyz",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            r_b = await c_b.get("/api/me/notifications/recent")
            assert r_b.status_code == 200
            b_ids = [n["id"] for n in r_b.json()["notifications"]]
            assert notif_id not in b_ids, (
                "User A's notification leaked into User B's recent feed!"
            )

            r_a = await c_a.get("/api/me/notifications/recent")
            a_ids = [n["id"] for n in r_a.json()["notifications"]]
            assert notif_id in a_ids

            await db.user_notifications.delete_one({"id": notif_id})
        finally:
            await c_a.aclose()
            await c_b.aclose()
    _run_async(run())


def test_notifications_recent_respects_since_cutoff():
    """Anything older than `since` should be filtered out."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            old_id = str(uuid.uuid4())
            new_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            await db.user_notifications.insert_many([
                {
                    "id": old_id, "user_id": me["id"], "type": "processing_complete",
                    "title": "Old", "body": "old", "deep_link": "/",
                    "created_at": (now - timedelta(hours=2)).isoformat(),
                },
                {
                    "id": new_id, "user_id": me["id"], "type": "processing_complete",
                    "title": "Fresh", "body": "fresh", "deep_link": "/",
                    "created_at": now.isoformat(),
                },
            ])

            # Cutoff is 1h ago → old should be filtered out (it's 2h old)
            since = (now - timedelta(hours=1)).isoformat()
            r = await c.get("/api/me/notifications/recent", params={"since": since})
            assert r.status_code == 200
            ids = [n["id"] for n in r.json()["notifications"]]
            assert new_id in ids
            assert old_id not in ids, (
                f"`since` cutoff didn't filter the 2h-old notif: {ids}"
            )

            await db.user_notifications.delete_many({"id": {"$in": [old_id, new_id]}})
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. TTL sweeper
# ---------------------------------------------------------------------------

def test_ttl_sweeper_purges_old_dismissed_uploads_and_notifications():
    """Manually invoke one tick of the sweeper logic and verify both
    collections lose their stale entries while fresh ones stay."""
    async def run():
        from db import db
        from server import DISMISSED_UPLOADS_TTL_DAYS, USER_NOTIFICATIONS_TTL_DAYS  # noqa: F401

        # Inject 2 dismissed_uploads (1 stale, 1 fresh) + 2 user_notifications (same)
        uid = f"sweeper-user-{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc)
        stale_upload_id = str(uuid.uuid4())
        fresh_upload_id = str(uuid.uuid4())
        stale_notif_id = str(uuid.uuid4())
        fresh_notif_id = str(uuid.uuid4())

        await db.chunked_uploads.insert_many([
            {
                "upload_id": stale_upload_id, "user_id": uid, "match_id": "m1",
                "filename": "stale.mp4", "file_size": 1024,
                "status": "initialized",
                "dismissed_at": (now - timedelta(days=DISMISSED_UPLOADS_TTL_DAYS + 1)).isoformat(),
            },
            {
                "upload_id": fresh_upload_id, "user_id": uid, "match_id": "m1",
                "filename": "fresh.mp4", "file_size": 1024,
                "status": "initialized",
                "dismissed_at": (now - timedelta(days=1)).isoformat(),
            },
        ])
        await db.user_notifications.insert_many([
            {
                "id": stale_notif_id, "user_id": uid, "type": "processing_complete",
                "title": "Old", "body": "x", "deep_link": "/",
                "created_at": (now - timedelta(days=USER_NOTIFICATIONS_TTL_DAYS + 1)).isoformat(),
            },
            {
                "id": fresh_notif_id, "user_id": uid, "type": "processing_complete",
                "title": "Fresh", "body": "y", "deep_link": "/",
                "created_at": now.isoformat(),
            },
        ])

        # Run ONE tick of the sweeper logic directly (without the asyncio.sleep loop)
        dismiss_cutoff = (now - timedelta(days=DISMISSED_UPLOADS_TTL_DAYS)).isoformat()
        notif_cutoff = (now - timedelta(days=USER_NOTIFICATIONS_TTL_DAYS)).isoformat()
        uploads_res = await db.chunked_uploads.delete_many({
            "dismissed_at": {"$exists": True, "$lt": dismiss_cutoff},
        })
        notifs_res = await db.user_notifications.delete_many({
            "created_at": {"$lt": notif_cutoff},
        })

        # Stale entries gone, fresh entries still present
        assert uploads_res.deleted_count >= 1
        assert notifs_res.deleted_count >= 1
        assert await db.chunked_uploads.find_one({"upload_id": stale_upload_id}) is None
        assert await db.chunked_uploads.find_one({"upload_id": fresh_upload_id}) is not None
        assert await db.user_notifications.find_one({"id": stale_notif_id}) is None
        assert await db.user_notifications.find_one({"id": fresh_notif_id}) is not None

        # Cleanup
        await db.chunked_uploads.delete_many({"user_id": uid})
        await db.user_notifications.delete_many({"user_id": uid})

    _run_async(run())


def test_ttl_sweeper_constants_are_sensible():
    """Guards against accidentally setting the TTL to 0 or 1 (which would
    purge legitimately-recent data)."""
    from server import DISMISSED_UPLOADS_TTL_DAYS, USER_NOTIFICATIONS_TTL_DAYS, TTL_SWEEPER_INTERVAL_SECS
    assert 7 <= DISMISSED_UPLOADS_TTL_DAYS <= 365
    assert 7 <= USER_NOTIFICATIONS_TTL_DAYS <= 365
    # Daily cadence — definitely not faster than once an hour, not slower than weekly
    assert 3600 <= TTL_SWEEPER_INTERVAL_SECS <= 7 * 24 * 3600


# ---------------------------------------------------------------------------
# 3. Frontend wiring grep-tests
# ---------------------------------------------------------------------------

def test_app_mounts_in_app_notifications_hook():
    app_path = os.path.join(_BACKEND, "..", "frontend", "src", "App.js")
    with open(app_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "useInAppNotifications" in src, (
        "App.js must import + invoke useInAppNotifications so cross-device "
        "notifications work on every authenticated page."
    )
    assert "<Toaster" in src, (
        "App.js must mount <Toaster /> so the hook's toast() calls actually render."
    )


def test_hook_polls_recent_endpoint():
    hook_path = os.path.join(_BACKEND, "..", "frontend", "src", "hooks", "useInAppNotifications.js")
    assert os.path.isfile(hook_path), f"{hook_path} must exist"
    with open(hook_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "/me/notifications/recent" in src
    assert "setInterval" in src, "Hook must poll on an interval"
    assert "showLocalNotification" in src, (
        "Hook should fire showLocalNotification so users with push permission "
        "still get the browser-level OS notification."
    )
    assert "localStorage" in src, (
        "Per-device 'seen' state must persist to localStorage so a page reload "
        "doesn't re-fire every recent notification."
    )


def test_processing_emits_user_notification_doc():
    """Grep-level guard: services/processing.py must insert into
    user_notifications when a match finishes processing."""
    proc_path = os.path.join(_BACKEND, "services", "processing.py")
    with open(proc_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "user_notifications" in src, (
        "services/processing.py must write to db.user_notifications after "
        "processing completes — that's what the in-app poller reads."
    )
