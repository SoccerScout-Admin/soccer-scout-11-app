"""Tests for Web Push notification feature.

Covers:
- GET /api/push/vapid-key (public, no auth) — returns 87-char base64url key + configured:true
- POST /api/push/subscribe — upsert (same endpoint twice = 1 doc)
- POST /api/push/unsubscribe — cross-user isolation
- GET /api/push/subscriptions — count reflects only current user
- POST /api/push/send-test — fake endpoint returns failed>=1 (not 500)
- Auth gating — all push routes except vapid-key require auth
- send_to_user — auto-prunes 410/404 endpoints (uses real DB + mocked _send_sync via patch on services.push_notifications)
- Auto-processing hook import smoke + shared clip throttle hook
"""
import os
import asyncio
import uuid
import importlib
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://video-scout-11.preview.emergentagent.com").rstrip("/")

# A single, module-scoped event loop. Motor caches its IO executor against the first loop it
# sees, so re-creating loops with asyncio.run() causes "Event loop is closed" the second time.
_LOOP = asyncio.new_event_loop()

def _run(coro):
    return _LOOP.run_until_complete(coro)

# ---------- Helpers ----------

def _fake_endpoint():
    """Return a non-reachable but well-formed FCM-style endpoint."""
    return f"https://fcm.googleapis.com/fcm/send/TEST_{uuid.uuid4().hex[:32]}"

def _fake_keys():
    # 65-byte uncompressed P-256 point (b64url) and 16-byte auth secret (b64url) — fake but right shape
    return {
        "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM",
        "auth": "tBHItJI5svbpez7KI4CCXg",
    }


# ---------- VAPID key (public, unauth) ----------

class TestVapidKey:
    def test_vapid_key_no_auth_required(self):
        # No Authorization header — should succeed
        r = requests.get(f"{BASE_URL}/api/push/vapid-key", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("configured") is True
        pk = data.get("public_key", "")
        assert isinstance(pk, str) and len(pk) == 87, f"VAPID public key must be 87 base64url chars, got {len(pk)}"
        # base64url charset
        import re
        assert re.match(r"^[A-Za-z0-9_-]{87}$", pk), "key contains non-base64url chars"


# ---------- Auth-gated endpoints ----------

class TestAuthGating:
    @pytest.mark.parametrize("method,path,body", [
        ("post", "/api/push/subscribe", {"endpoint": _fake_endpoint(), "keys": _fake_keys()}),
        ("post", "/api/push/unsubscribe", {"endpoint": _fake_endpoint()}),
        ("get",  "/api/push/subscriptions", None),
        ("post", "/api/push/send-test", None),
    ])
    def test_requires_auth(self, method, path, body):
        fn = getattr(requests, method)
        kwargs = {"timeout": 15}
        if body is not None:
            kwargs["json"] = body
        r = fn(f"{BASE_URL}{path}", **kwargs)
        assert r.status_code in (401, 403), f"Expected 401/403 unauth, got {r.status_code}: {r.text[:200]}"


# ---------- Subscribe / Unsubscribe / List / Send-test (live API, authenticated) ----------

class TestPushCRUD:
    def test_subscribe_upsert_idempotent(self, api_client, auth_headers):
        endpoint = _fake_endpoint()
        payload = {"endpoint": endpoint, "keys": _fake_keys()}

        # Snapshot count
        c0 = api_client.get(f"{BASE_URL}/api/push/subscriptions", headers=auth_headers).json()["count"]

        r1 = api_client.post(f"{BASE_URL}/api/push/subscribe", json=payload, headers=auth_headers)
        assert r1.status_code == 200, r1.text
        assert r1.json().get("subscribed") is True

        r2 = api_client.post(f"{BASE_URL}/api/push/subscribe", json=payload, headers=auth_headers)
        assert r2.status_code == 200

        c1 = api_client.get(f"{BASE_URL}/api/push/subscriptions", headers=auth_headers).json()["count"]
        # Same endpoint submitted twice should only add one document
        assert c1 == c0 + 1, f"Upsert violated: count went from {c0} to {c1} after two identical subscribes"

        # Cleanup
        api_client.post(f"{BASE_URL}/api/push/unsubscribe", json={"endpoint": endpoint}, headers=auth_headers)
        c2 = api_client.get(f"{BASE_URL}/api/push/subscriptions", headers=auth_headers).json()["count"]
        assert c2 == c0

    def test_unsubscribe_missing_endpoint_returns_400(self, api_client, auth_headers):
        r = api_client.post(f"{BASE_URL}/api/push/unsubscribe", json={}, headers=auth_headers)
        assert r.status_code == 400

    def test_unsubscribe_unknown_endpoint_deletes_zero(self, api_client, auth_headers):
        r = api_client.post(f"{BASE_URL}/api/push/unsubscribe",
                            json={"endpoint": _fake_endpoint()}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json().get("deleted") == 0

    def test_subscriptions_count_returns_configured(self, api_client, auth_headers):
        r = api_client.get(f"{BASE_URL}/api/push/subscriptions", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data.get("count"), int)
        assert data.get("configured") is True

    def test_send_test_with_fake_endpoint_does_not_crash(self, api_client, auth_headers):
        # Subscribe with a fake endpoint, then call send-test
        endpoint = _fake_endpoint()
        sub = api_client.post(f"{BASE_URL}/api/push/subscribe",
                              json={"endpoint": endpoint, "keys": _fake_keys()},
                              headers=auth_headers)
        assert sub.status_code == 200

        try:
            r = api_client.post(f"{BASE_URL}/api/push/send-test", headers=auth_headers)
            assert r.status_code == 200, r.text
            data = r.json()
            assert "sent" in data and "removed" in data and "failed" in data
            # Fake endpoint isn't reachable — must be reflected in failed OR removed (404/410)
            assert (data["failed"] + data["removed"]) >= 1, f"Expected failed/removed>=1, got {data}"
            assert data["sent"] == 0
        finally:
            api_client.post(f"{BASE_URL}/api/push/unsubscribe",
                            json={"endpoint": endpoint}, headers=auth_headers)


# ---------- Cross-user isolation ----------

class TestCrossUserIsolation:
    """Create a second user, ensure user A cannot delete user B's subs (and counts are scoped)."""

    def _signup_or_login(self, email, password, name):
        # Try signup; if email already exists, fall back to login
        r = requests.post(f"{BASE_URL}/api/auth/register",
                          json={"email": email, "password": password, "name": name}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data.get("token") or data.get("access_token")
        # Already exists -> login
        r = requests.post(f"{BASE_URL}/api/auth/login",
                          json={"email": email, "password": password}, timeout=15)
        if r.status_code == 200:
            d = r.json()
            return d.get("token") or d.get("access_token")
        pytest.skip(f"Could not create/login secondary user: {r.status_code} {r.text[:200]}")

    def test_unsubscribe_cannot_delete_other_users_sub(self, auth_headers):
        # Secondary user
        email_b = f"test_push_{uuid.uuid4().hex[:8]}@demo.com"
        token_b = self._signup_or_login(email_b, "Password!23", "Push Tester B")
        headers_b = {"Authorization": f"Bearer {token_b}", "Content-Type": "application/json"}

        endpoint = _fake_endpoint()
        # User B subscribes
        rb = requests.post(f"{BASE_URL}/api/push/subscribe",
                           json={"endpoint": endpoint, "keys": _fake_keys()},
                           headers=headers_b, timeout=15)
        assert rb.status_code == 200

        # B's count snapshot
        cb_before = requests.get(f"{BASE_URL}/api/push/subscriptions", headers=headers_b, timeout=15).json()["count"]
        assert cb_before >= 1

        # User A (testcoach) tries to unsubscribe B's endpoint — should delete 0
        ra = requests.post(f"{BASE_URL}/api/push/unsubscribe",
                           json={"endpoint": endpoint}, headers=auth_headers, timeout=15)
        assert ra.status_code == 200
        assert ra.json().get("deleted") == 0, "User A should not be able to delete user B's sub"

        # B's count must be unchanged
        cb_after = requests.get(f"{BASE_URL}/api/push/subscriptions", headers=headers_b, timeout=15).json()["count"]
        assert cb_after == cb_before, "User A's request must not affect user B's subscription"

        # Cleanup with B's own token
        requests.post(f"{BASE_URL}/api/push/unsubscribe",
                      json={"endpoint": endpoint}, headers=headers_b, timeout=15)


# ---------- Service-layer: pruning of 410/404, hook smoke tests ----------

class TestServicePruning:
    """Directly exercise services.push_notifications.send_to_user with a mocked _send_sync."""

    def test_send_to_user_prunes_410_and_increments_removed(self, monkeypatch):
        # Import service in-process, patch _send_sync, call against real Mongo
        sys_path = "/app/backend"
        import sys
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        svc = importlib.import_module("services.push_notifications")
        from db import db as live_db

        async def _runner():
            # Seed a fresh sub for testcoach (look up user_id via login)
            login = requests.post(f"{BASE_URL}/api/auth/login",
                                  json={"email": "testcoach@demo.com", "password": "password123"}, timeout=15)
            assert login.status_code == 200, login.text
            token = login.json().get("token") or login.json().get("access_token")
            me = requests.get(f"{BASE_URL}/api/auth/me",
                              headers={"Authorization": f"Bearer {token}"}, timeout=15)
            assert me.status_code == 200, me.text
            user_id = me.json()["id"]

            endpoint = _fake_endpoint() + "_410test"
            await live_db.push_subscriptions.update_one(
                {"endpoint": endpoint},
                {"$set": {"endpoint": endpoint, "user_id": user_id, "keys": _fake_keys(),
                          "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00",
                          "last_sent_at": None}},
                upsert=True,
            )
            try:
                # Patch _send_sync to simulate 410 Gone
                monkeypatch.setattr(svc, "_send_sync", lambda sub_info, payload: (False, "webpush-410"))

                result = await svc.send_to_user(user_id=user_id, title="t", body="b", url="/")
                assert result["removed"] >= 1, f"Expected removed>=1 for webpush-410, got {result}"
                assert result["sent"] == 0
                # Confirm the sub doc was deleted
                still = await live_db.push_subscriptions.find_one({"endpoint": endpoint})
                assert still is None, "410 sub should have been pruned from DB"
            finally:
                await live_db.push_subscriptions.delete_one({"endpoint": endpoint})

        _run(_runner())

    def test_send_to_user_no_subs_returns_zero(self, monkeypatch):
        import sys
        if "/app/backend" not in sys.path:
            sys.path.insert(0, "/app/backend")
        svc = importlib.import_module("services.push_notifications")

        async def _runner():
            # Random user with no subs
            result = await svc.send_to_user(user_id=f"nobody-{uuid.uuid4().hex}", title="t", body="b")
            assert result == {"sent": 0, "removed": 0, "failed": 0, "reason": "no_subscriptions"}

        _run(_runner())


# ---------- Hook integration smoke ----------

class TestHookIntegration:
    """Verify the auto-processing + shared-clip imports are wired and don't crash."""

    def test_server_imports_push_router_and_send_to_user(self):
        import sys
        if "/app/backend" not in sys.path:
            sys.path.insert(0, "/app/backend")
        # These imports must succeed — server.py uses them inline at run_auto_processing tail
        from routes.push_notifications import router as push_router  # noqa: F401
        from services.push_notifications import send_to_user, is_configured  # noqa: F401
        assert is_configured() is True

    def test_shared_clip_route_is_mounted_from_routes_clips(self):
        """REGRESSION GUARD: server.py duplicates GET /shared/clip/{share_token} (line ~2184)
        and routes/clips.py is not registered in server.py — so the push hook in routes/clips.py
        is DEAD CODE. This test detects that condition by setting last_view_notify_at=None,
        hitting the endpoint, and expecting the marker to be populated.
        """
        import sys
        if "/app/backend" not in sys.path:
            sys.path.insert(0, "/app/backend")
        from db import db as live_db

        async def _setup():
            clip = await live_db.clips.find_one({"share_token": {"$exists": True, "$ne": None}}, {"_id": 0})
            if not clip:
                pytest.skip("No shared clips in DB to exercise the hook")
            await live_db.clips.update_one({"share_token": clip["share_token"]},
                                           {"$set": {"last_view_notify_at": None}})
            return clip["share_token"]

        share_token = _run(_setup())

        r1 = requests.get(f"{BASE_URL}/api/shared/clip/{share_token}", timeout=15)
        assert r1.status_code == 200, r1.text

        async def _check():
            doc = await live_db.clips.find_one({"share_token": share_token},
                                               {"_id": 0, "last_view_notify_at": 1})
            return doc

        doc = _run(_check())
        assert doc and doc.get("last_view_notify_at"), (
            "BUG: first hit on /api/shared/clip/{token} did NOT set last_view_notify_at. "
            "Root cause: routes/clips.py is never imported/mounted in server.py — "
            "server.py:2184 has its own duplicate handler `get_shared_clip_detail` that "
            "lacks the push hook. The throttled push notification on shared-clip view is dead code."
        )

        # Throttle assertion: 2nd hit within 6h must NOT advance the marker.
        t1 = doc["last_view_notify_at"]
        r2 = requests.get(f"{BASE_URL}/api/shared/clip/{share_token}", timeout=15)
        assert r2.status_code == 200
        doc2 = _run(_check())
        assert doc2["last_view_notify_at"] == t1, (
            f"Throttle violated: marker advanced from {t1} to {doc2['last_view_notify_at']}"
        )
