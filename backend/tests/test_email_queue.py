"""Tests for services.email_queue + /api/admin/email-queue endpoints."""
import os
import secrets
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import requests

from tests.conftest import BASE_URL, run_async as _run  # noqa: F401


# ---------- Pure-function tests ----------

def test_quota_detection():
    from services.email_queue import _is_quota_error
    assert _is_quota_error(Exception("daily_quota exceeded"))
    assert _is_quota_error(Exception("monthly_quota exceeded"))
    assert _is_quota_error(Exception("You have hit the rate_limit"))
    assert _is_quota_error(Exception("too_many_requests"))
    assert _is_quota_error(Exception("HTTP 429 from resend"))
    assert not _is_quota_error(Exception("Invalid email address"))
    assert not _is_quota_error(Exception("network timeout"))


def test_backoff_progression():
    from services.email_queue import _next_retry
    now = datetime.now(timezone.utc)
    quota_retry = _next_retry(attempts=1, quota=True)
    diff_h = (quota_retry - now).total_seconds() / 3600
    assert 0.9 < diff_h < 1.1

    # Non-quota: attempt 0→1h, 1→4h, 2→12h, 3→24h, 4→72h, 10→72h (capped)
    for attempts, expected_h in [(0, 1), (1, 4), (2, 12), (3, 24), (4, 72), (10, 72)]:
        r = _next_retry(attempts=attempts, quota=False)
        diff = (r - now).total_seconds() / 3600
        assert abs(diff - expected_h) < 0.1, f"attempt={attempts} expected={expected_h} got={diff:.2f}"


# ---------- Integration tests with real MongoDB + mocked Resend ----------


def _mock_ok(return_value):
    async def _mock(*args, **kwargs):
        return return_value
    return _mock


def _mock_raise(message):
    async def _mock(*args, **kwargs):
        raise Exception(message)
    return _mock


def test_send_or_queue_success_path():
    from services import email_queue
    from db import db

    async def go():
        with patch.object(email_queue, '_resend_send', new=_mock_ok('fake-email-id-123')):
            with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key'}):
                result = await email_queue.send_or_queue(
                    to_email="test@example.com",
                    subject="Test",
                    html="<p>hi</p>",
                    kind="unit_test",
                )
        assert result["status"] == "sent"
        assert result["email_id"] == "fake-email-id-123"
        doc = await db.email_queue.find_one({"id": result["queue_id"]}, {"_id": 0})
        assert doc is not None
        assert doc["status"] == "sent"
        assert doc["attempts"] == 1
        assert doc["kind"] == "unit_test"
        await db.email_queue.delete_one({"id": result["queue_id"]})
    _run(go())


def test_send_or_queue_quota_deferred():
    from services import email_queue
    from db import db

    async def go():
        with patch.object(email_queue, '_resend_send', new=_mock_raise("daily_quota exceeded")):
            with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key'}):
                result = await email_queue.send_or_queue(
                    to_email="quota@example.com",
                    subject="Over quota",
                    html="<p>fail</p>",
                    kind="unit_test",
                )
        assert result["status"] == "quota_deferred"
        doc = await db.email_queue.find_one({"id": result["queue_id"]}, {"_id": 0})
        assert doc["status"] == "quota_deferred"
        assert doc["attempts"] == 1
        assert doc["next_retry_at"] is not None
        assert "daily_quota" in doc["last_error"]
        await db.email_queue.delete_one({"id": result["queue_id"]})
    _run(go())


def test_send_or_queue_transient_failure():
    from services import email_queue
    from db import db

    async def go():
        with patch.object(email_queue, '_resend_send', new=_mock_raise("invalid email address")):
            with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key'}):
                result = await email_queue.send_or_queue(
                    to_email="bad",
                    subject="No",
                    html="x",
                    kind="unit_test",
                )
        assert result["status"] == "failed"
        doc = await db.email_queue.find_one({"id": result["queue_id"]}, {"_id": 0})
        assert doc["status"] == "failed"
        assert doc["next_retry_at"] is not None
        await db.email_queue.delete_one({"id": result["queue_id"]})
    _run(go())


def test_process_queue_retries_and_sends():
    from services import email_queue
    from db import db

    async def go():
        test_id = "eq-test-process-1"
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await db.email_queue.insert_one({
            "id": test_id,
            "to_email": "retry@example.com",
            "subject": "retry me",
            "html": "<p>x</p>",
            "kind": "unit_test",
            "created_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "status": "quota_deferred",
            "attempts": 1,
            "last_error": "daily_quota",
            "next_retry_at": past,
        })

        with patch.object(email_queue, '_resend_send', new=_mock_ok('sent-after-retry')):
            with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key'}):
                result = await email_queue.process_queue()
        assert result["processed"] >= 1
        assert result["sent"] >= 1
        doc = await db.email_queue.find_one({"id": test_id}, {"_id": 0})
        assert doc["status"] == "sent"
        assert doc["email_id"] == "sent-after-retry"
        assert doc["attempts"] == 2
        await db.email_queue.delete_one({"id": test_id})
    _run(go())


def test_process_queue_skips_future_retries():
    from services import email_queue
    from db import db

    async def go():
        test_id = "eq-test-future-1"
        future = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()
        await db.email_queue.insert_one({
            "id": test_id,
            "to_email": "later@example.com",
            "subject": "wait",
            "html": "<p>x</p>",
            "kind": "unit_test",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "quota_deferred",
            "attempts": 1,
            "last_error": "daily_quota",
            "next_retry_at": future,
        })

        call_count = [0]
        async def _mock(*args, **kwargs):
            call_count[0] += 1
            return "should-not-happen"

        with patch.object(email_queue, '_resend_send', new=_mock):
            with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key'}):
                await email_queue.process_queue()

        doc = await db.email_queue.find_one({"id": test_id}, {"_id": 0})
        assert doc["status"] == "quota_deferred"
        assert doc["attempts"] == 1
        await db.email_queue.delete_one({"id": test_id})
    _run(go())


def test_give_up_after_5_non_quota_failures():
    from services import email_queue
    from db import db

    async def go():
        test_id = "eq-test-giveup"
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        await db.email_queue.insert_one({
            "id": test_id,
            "to_email": "perm@example.com",
            "subject": "doomed",
            "html": "<p>x</p>",
            "kind": "unit_test",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
            "attempts": 4,
            "last_error": "invalid email",
            "next_retry_at": past,
        })

        with patch.object(email_queue, '_resend_send', new=_mock_raise("still invalid")):
            with patch.dict(os.environ, {'RESEND_API_KEY': 'test-key'}):
                await email_queue.process_queue()

        doc = await db.email_queue.find_one({"id": test_id}, {"_id": 0})
        assert doc["status"] == "failed_permanent"
        assert doc["attempts"] == 5
        assert doc["next_retry_at"] is None
        await db.email_queue.delete_one({"id": test_id})
    _run(go())


# ---------- HTTP endpoint tests ----------


def test_admin_email_queue_requires_admin(auth_headers):
    r = requests.get(f"{BASE_URL}/api/admin/email-queue", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "depth" in data
    assert "items" in data
    assert isinstance(data["items"], list)
    for k in ("sent", "quota_deferred", "failed", "failed_permanent", "total"):
        assert k in data["depth"]


def test_admin_email_queue_blocked_for_coach(api_client):
    email = f"coach-{secrets.token_hex(4)}@test.com"
    r = api_client.post(f"{BASE_URL}/api/auth/register", json={
        "email": email, "password": "password123", "name": "Test Coach NoAdmin"
    })
    assert r.status_code == 200, r.text
    token = r.json().get("token") or r.json().get("access_token")
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{BASE_URL}/api/admin/email-queue", headers=headers, timeout=15)
    assert r.status_code == 403


def test_admin_process_queue_manually(auth_headers):
    r = requests.post(f"{BASE_URL}/api/admin/email-queue/process", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "processed" in data
    assert "sent" in data
    assert "failed" in data


def test_admin_retry_unknown_returns_404(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/email-queue/eq-does-not-exist/retry",
        headers=auth_headers,
        timeout=15,
    )
    assert r.status_code == 404
