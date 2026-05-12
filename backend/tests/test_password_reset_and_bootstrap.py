"""Password reset + admin bootstrap endpoints.

Verified surfaces:
- POST /api/auth/forgot-password always returns {status: sent}, 200
  (no account enumeration)
- Unknown emails do NOT create rows in password_reset_tokens
- Known emails DO create a sha256-hashed single-use token + enqueue an email
- POST /api/auth/reset-password:
  - rejects bad token (400)
  - rejects weak passwords without letter+digit (400)
  - happy path updates bcrypt hash and old password fails to log in
  - replay rejected (400)
- POST /api/admin/bootstrap:
  - 401 without auth
  - 403 with wrong secret
  - 200 + promoted with correct secret
  - 200 + already_admin no-op on second call
"""
from __future__ import annotations

import os
import re
import time
import uuid
import pytest

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: F401

BOOTSTRAP_SECRET = os.environ.get('ADMIN_BOOTSTRAP_SECRET', '')


def _register(api_client, email: str, password: str = 'OrigPass123') -> dict:
    r = api_client.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": password, "name": "Reset Test", "role": "coach"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    return {"token": data['token'], "id": data['user']['id']}


def _cleanup(email: str):
    async def go():
        from db import db  # noqa: WPS433
        await db.users.delete_one({"email": email})
        await db.password_reset_tokens.delete_many({"email": email})
        await db.email_queue.delete_many({"to_email": email})
    _run_async(go())


# ---------- forgot-password ----------

def test_forgot_password_always_returns_200(api_client):
    r = api_client.post(
        f"{BASE_URL}/api/auth/forgot-password",
        json={"email": f"does-not-exist-{uuid.uuid4().hex[:8]}@example.com"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "sent"}


def test_forgot_password_unknown_email_creates_no_token(api_client):
    """Unknown email must NOT create a row in password_reset_tokens."""
    bogus = f"bogus-{uuid.uuid4().hex[:8]}@example.com"
    api_client.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": bogus})

    async def go():
        from db import db
        return await db.password_reset_tokens.count_documents({"email": bogus})
    assert _run_async(go()) == 0


def test_forgot_password_known_email_creates_hashed_token(api_client):
    email = f"fptest-{int(time.time())}-{uuid.uuid4().hex[:4]}@example.com"
    _register(api_client, email)
    try:
        r = api_client.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": email})
        assert r.status_code == 200

        async def go():
            from db import db
            doc = await db.password_reset_tokens.find_one({"email": email}, {"_id": 0})
            return doc
        doc = _run_async(go())
        assert doc is not None, "password_reset_tokens row should exist"
        # Hash is sha256 hex (64 chars)
        assert doc.get("token_hash") and len(doc["token_hash"]) == 64
        assert doc.get("used_at") is None
        assert doc.get("expires_at")
    finally:
        _cleanup(email)


# ---------- full reset round-trip ----------

def _extract_raw_token_from_queue(email: str) -> str:
    async def go():
        from db import db
        doc = await db.email_queue.find_one({"kind": "password_reset", "to_email": email}, sort=[("created_at", -1)])
        if not doc:
            return None
        m = re.search(r"token=([A-Za-z0-9_\-]+)", doc.get("html", ""))
        return m.group(1) if m else None
    return _run_async(go())


def test_reset_password_full_round_trip(api_client):
    email = f"fptest-{int(time.time())}-{uuid.uuid4().hex[:4]}@example.com"
    orig = "OrigPass123"
    _register(api_client, email, orig)
    try:
        api_client.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": email})
        raw = _extract_raw_token_from_queue(email)
        assert raw, "raw token should be embedded in the queued email HTML"

        # Valid reset
        r = api_client.post(f"{BASE_URL}/api/auth/reset-password", json={"token": raw, "new_password": "NewPass123"})
        assert r.status_code == 200, r.text
        assert r.json().get("status") == "reset"

        # Old password fails
        r = api_client.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": orig})
        assert r.status_code == 401

        # New password works
        r = api_client.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": "NewPass123"})
        assert r.status_code == 200, r.text

        # Replay rejected
        r = api_client.post(f"{BASE_URL}/api/auth/reset-password", json={"token": raw, "new_password": "Another12"})
        assert r.status_code == 400
        assert "already been used" in r.json().get("detail", "")
    finally:
        _cleanup(email)


def test_reset_password_rejects_weak_password(api_client):
    email = f"fptest-{int(time.time())}-{uuid.uuid4().hex[:4]}@example.com"
    _register(api_client, email)
    try:
        api_client.post(f"{BASE_URL}/api/auth/forgot-password", json={"email": email})
        raw = _extract_raw_token_from_queue(email)
        assert raw

        # No digit -> rejected
        r = api_client.post(f"{BASE_URL}/api/auth/reset-password", json={"token": raw, "new_password": "nodigits"})
        assert r.status_code in (400, 422), r.text
        # No letter -> rejected
        r = api_client.post(f"{BASE_URL}/api/auth/reset-password", json={"token": raw, "new_password": "12345678"})
        assert r.status_code in (400, 422), r.text
    finally:
        _cleanup(email)


def test_reset_password_bad_token_returns_400(api_client):
    r = api_client.post(f"{BASE_URL}/api/auth/reset-password", json={"token": "bogus-" + uuid.uuid4().hex, "new_password": "abc12345"})
    assert r.status_code == 400


# ---------- admin bootstrap ----------

def test_admin_bootstrap_requires_auth(api_client):
    r = api_client.post(f"{BASE_URL}/api/admin/bootstrap", json={"secret": "whatever"})
    assert r.status_code in (401, 403)


def test_admin_bootstrap_wrong_secret_rejected(api_client):
    if not BOOTSTRAP_SECRET:
        pytest.skip("ADMIN_BOOTSTRAP_SECRET not configured in local env — can't test wrong-secret path")
    email = f"bstest-{int(time.time())}-{uuid.uuid4().hex[:4]}@example.com"
    token = _register(api_client, email)['token']
    try:
        r = api_client.post(
            f"{BASE_URL}/api/admin/bootstrap",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"secret": "DEFINITELY-WRONG-" + uuid.uuid4().hex},
        )
        assert r.status_code == 403, r.text
        assert "Invalid bootstrap secret" in r.json().get("detail", "")
    finally:
        _cleanup(email)


def test_admin_bootstrap_happy_path_and_idempotent(api_client):
    if not BOOTSTRAP_SECRET:
        pytest.skip("ADMIN_BOOTSTRAP_SECRET not configured in local env — happy path test skipped")
    email = f"bstest-{int(time.time())}-{uuid.uuid4().hex[:4]}@example.com"
    reg = _register(api_client, email)
    token = reg['token']
    try:
        # First call: promoted
        r = api_client.post(
            f"{BASE_URL}/api/admin/bootstrap",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"secret": BOOTSTRAP_SECRET},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body == {"status": "promoted", "role": "admin"}

        # /auth/me now reflects admin role
        r = api_client.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json().get("role") == "admin"

        # Second call: already_admin, no error
        r = api_client.post(
            f"{BASE_URL}/api/admin/bootstrap",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"secret": BOOTSTRAP_SECRET},
        )
        assert r.status_code == 200
        assert r.json() == {"status": "already_admin", "role": "admin"}
    finally:
        _cleanup(email)
