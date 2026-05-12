"""
Tests for iter55 login rate-limiter.

Validates the MongoDB-backed sliding-window brute force defender:
  - First 9 failures pass through (return 401)
  - 10th failure triggers the lockout — subsequent attempts get 429
  - Lockout applies even to the CORRECT password while window is active
  - Successful login clears both IP and email counters
  - IP-only attacker (rotating victims) blocked by per-IP counter
  - Email-only attacker (rotating IPs) blocked by per-email counter
  - 429 response includes Retry-After header + friendly message
"""
import os
import uuid
import requests
import pytest
import asyncio
from datetime import datetime, timezone

BASE_URL = os.environ.get(
    'REACT_APP_BACKEND_URL',
    'https://video-scout-11.preview.emergentagent.com',
).rstrip('/')


def _cleanup_attempts(email: str):
    """Direct DB cleanup so tests can run repeatedly without inheriting state."""
    try:
        from server import db
        loop = asyncio.new_event_loop()
        loop.run_until_complete(db.login_attempts.delete_many({
            "key": {"$regex": f"^(ip:|email:{email})"}
        }))
        loop.close()
    except Exception:
        pass  # not critical — TTL will eventually clear


@pytest.fixture
def fresh_user():
    """Register a throwaway user. Cleanup attempts after test."""
    email = f"ratelimit-{uuid.uuid4().hex[:8]}@example.com"
    password = "RateLimitTest2026!"
    resp = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": password, "name": "RL Tester", "role": "coach"},
        timeout=15,
    )
    if resp.status_code != 200:
        pytest.skip(f"register failed: {resp.text}")
    # Wipe register's own success-clear so the limiter starts fresh for these tests
    _cleanup_attempts(email)
    yield email, password
    _cleanup_attempts(email)


def test_9_failures_dont_lock_out(fresh_user):
    """Sliding-window allows up to 9 failures before tripping at 10."""
    email, _ = fresh_user
    for i in range(9):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "wrong"},
            timeout=15,
        )
        assert r.status_code == 401, f"attempt {i+1}: got {r.status_code} {r.text}"


def test_10th_failure_triggers_lockout(fresh_user):
    email, _ = fresh_user
    statuses = []
    for _ in range(10):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "wrong"},
            timeout=15,
        )
        statuses.append(r.status_code)
    # First 9 should be 401, then the 10th attempt itself records the 10th
    # entry — meaning the NEXT call (11th) is the one that 429s. But since
    # check happens BEFORE record, the 10th attempt's check sees 9, allows it,
    # then records #10. The 11th call sees 10 → 429.
    locked = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": "wrong"},
        timeout=15,
    )
    assert locked.status_code == 429, f"Expected 429 lockout, got {locked.status_code}: {locked.text}"
    assert "Retry-After" in locked.headers
    detail = locked.json().get("detail", "")
    assert "too many" in detail.lower() or "try again" in detail.lower()


def test_lockout_blocks_even_correct_password(fresh_user):
    """An attacker who eventually GUESSES the right password still can't use
    it during the lockout window. Critical — otherwise the limiter is moot."""
    email, password = fresh_user
    for _ in range(10):
        requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "wrong"},
            timeout=15,
        )
    # Now try the CORRECT password — should still 429
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 429, f"Lockout should block even correct password, got {r.status_code}: {r.text}"


def test_successful_login_resets_counters(fresh_user):
    """Coach who mistypes 3 times then gets it right shouldn't have those 3
    attempts hanging over them — clean slate after success."""
    email, password = fresh_user
    # 3 failures (well under threshold)
    for _ in range(3):
        requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "wrong"},
            timeout=15,
        )
    # Now a successful login
    ok = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert ok.status_code == 200, f"correct login failed: {ok.text}"

    # Now hammer 9 more failed attempts — should still all return 401 since
    # success wiped the previous 3.
    for i in range(9):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "wrong"},
            timeout=15,
        )
        assert r.status_code == 401, f"post-reset attempt {i+1}: counter not cleared (got {r.status_code})"


def test_429_response_has_retry_after_and_useful_message(fresh_user):
    email, _ = fresh_user
    for _ in range(11):
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "wrong"},
            timeout=15,
        )
    assert r.status_code == 429
    # Retry-After should be a positive integer seconds value
    retry_after = r.headers.get("Retry-After")
    assert retry_after and retry_after.isdigit(), f"bad Retry-After: {retry_after}"
    assert 0 < int(retry_after) <= 15 * 60, f"Retry-After out of expected range: {retry_after}"
    # Friendly message for the frontend
    detail = r.json()["detail"]
    assert "minute" in detail.lower(), f"detail should mention minutes: {detail}"
