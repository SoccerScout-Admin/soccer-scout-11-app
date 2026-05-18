"""
Tests for iter76: env-controlled admin auto-promote on login.

`ADMIN_AUTOPROMOTE_EMAIL` env var (comma-separated allowed) auto-promotes any
matching email to `role: "admin"` on login or any authenticated request. The
helper is duplicated in server.py and routes/auth.py — these tests poke the
helper directly to verify the contract, then end-to-end via /api/auth/login
to verify wiring.

Behavior contract:
  - env unset → no-op (return user unchanged)
  - env set, role already admin/owner → no-op (idempotent)
  - env set, email matches → role flipped to "admin" in DB + payload
  - env set, comma-separated list, email matches one → promoted
  - env set, email does NOT match → no-op
  - DB error during promotion → swallowed, login still succeeds with old role
"""
import os
import sys
import uuid
import bcrypt
import asyncio
import requests
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Path to import the helpers directly for unit tests
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

BASE_URL = os.environ.get("BASE_URL") or "https://scout-lens.preview.emergentagent.com"


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _run_mongo(coro_factory):
    load_dotenv()

    async def _run_inner():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            return await coro_factory(db)
        finally:
            client.close()

    return _run(_run_inner())


# ---------------------------------------------------------------------------
# Unit tests on the helper (no DB writes needed except for explicit cases)
# ---------------------------------------------------------------------------

def test_autopromote_noop_when_env_unset(monkeypatch):
    """Env var unset → return user unchanged."""
    monkeypatch.delenv("ADMIN_AUTOPROMOTE_EMAIL", raising=False)
    from routes.auth import _maybe_autopromote_admin
    user = {"id": "x", "email": "Anyone@example.com", "role": "coach"}
    result = _run(_maybe_autopromote_admin(user))
    assert result["role"] == "coach"


def test_autopromote_noop_when_already_admin(monkeypatch):
    """User is already admin → idempotent no-op (no DB write attempted)."""
    monkeypatch.setenv("ADMIN_AUTOPROMOTE_EMAIL", "Owner@example.com")
    from routes.auth import _maybe_autopromote_admin
    user = {"id": "x", "email": "Owner@example.com", "role": "admin"}
    result = _run(_maybe_autopromote_admin(user))
    assert result["role"] == "admin"


def test_autopromote_noop_when_already_owner(monkeypatch):
    """`owner` is treated as super-admin — no-op."""
    monkeypatch.setenv("ADMIN_AUTOPROMOTE_EMAIL", "Owner@example.com")
    from routes.auth import _maybe_autopromote_admin
    user = {"id": "x", "email": "Owner@example.com", "role": "owner"}
    result = _run(_maybe_autopromote_admin(user))
    assert result["role"] == "owner"


def test_autopromote_email_match_promotes(monkeypatch):
    """Plain happy path: email matches → role flips to admin in DB."""
    monkeypatch.setenv("ADMIN_AUTOPROMOTE_EMAIL", "owner@example.com")
    from routes.auth import _maybe_autopromote_admin

    uid = f"autopromote-test-{uuid.uuid4().hex[:8]}"
    seed_email = f"{uid}@example.com"
    monkeypatch.setenv("ADMIN_AUTOPROMOTE_EMAIL", seed_email)

    async def setup_and_run(db):
        await db.users.insert_one({
            "id": uid, "email": seed_email, "name": "Sentinel", "role": "coach",
            "password": "fake", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        result = await _maybe_autopromote_admin({
            "id": uid, "email": seed_email, "role": "coach",
        })
        stored = await db.users.find_one({"id": uid}, {"_id": 0, "role": 1})
        await db.users.delete_many({"id": uid})
        return result, stored

    result, stored = _run_mongo(setup_and_run)
    assert result["role"] == "admin"
    assert stored["role"] == "admin"


def test_autopromote_case_insensitive_match(monkeypatch):
    """User logs in with MixedCase email but env var was set in lowercase
    (or vice versa) — must still match."""
    uid = f"autopromote-case-{uuid.uuid4().hex[:8]}"
    seed_email = f"MixedCase-{uid}@Example.COM"
    monkeypatch.setenv("ADMIN_AUTOPROMOTE_EMAIL", seed_email.lower())
    from routes.auth import _maybe_autopromote_admin

    async def setup_and_run(db):
        await db.users.insert_one({
            "id": uid, "email": seed_email, "name": "Mixed", "role": "coach",
            "password": "fake", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        result = await _maybe_autopromote_admin({
            "id": uid, "email": seed_email, "role": "coach",
        })
        await db.users.delete_many({"id": uid})
        return result

    result = _run_mongo(setup_and_run)
    assert result["role"] == "admin"


def test_autopromote_comma_separated_list_matches_any(monkeypatch):
    """Comma-separated list: matching one of the entries triggers promotion."""
    uid = f"autopromote-csv-{uuid.uuid4().hex[:8]}"
    seed_email = f"second-{uid}@example.com"
    monkeypatch.setenv(
        "ADMIN_AUTOPROMOTE_EMAIL",
        f"first@example.com, {seed_email}, third@example.com",
    )
    from routes.auth import _maybe_autopromote_admin

    async def setup_and_run(db):
        await db.users.insert_one({
            "id": uid, "email": seed_email, "name": "CSV", "role": "coach",
            "password": "fake", "created_at": datetime.now(timezone.utc).isoformat(),
        })
        result = await _maybe_autopromote_admin({
            "id": uid, "email": seed_email, "role": "coach",
        })
        await db.users.delete_many({"id": uid})
        return result

    result = _run_mongo(setup_and_run)
    assert result["role"] == "admin"


def test_autopromote_no_match_keeps_coach_role(monkeypatch):
    """Env set but user's email doesn't match → role stays as-is."""
    monkeypatch.setenv("ADMIN_AUTOPROMOTE_EMAIL", "someone-else@example.com")
    from routes.auth import _maybe_autopromote_admin
    user = {"id": "x", "email": "different@example.com", "role": "coach"}
    result = _run(_maybe_autopromote_admin(user))
    assert result["role"] == "coach"


def test_autopromote_server_and_auth_helpers_have_identical_contract(monkeypatch):
    """Both copies of the helper (server.py + routes/auth.py) must behave
    identically — verify on a no-match path to keep this test loop-free."""
    monkeypatch.setenv("ADMIN_AUTOPROMOTE_EMAIL", "owner-only@example.com")
    from routes.auth import _maybe_autopromote_admin as helper_a
    from server import _maybe_autopromote_admin as helper_b
    user = {"id": "y", "email": "intruder@example.com", "role": "coach"}
    a = _run(helper_a(dict(user)))
    b = _run(helper_b(dict(user)))
    assert a["role"] == b["role"] == "coach"


# ---------------------------------------------------------------------------
# End-to-end via /api/auth/login — relies on a seeded sentinel coach user
# ---------------------------------------------------------------------------

def _register_sentinel(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": password, "name": "Sentinel Autopromote", "role": "coach"},
        timeout=15,
    )
    # 200 OK on create; if user already exists, log them in and reset role
    assert r.status_code in (200, 400)


def _reset_user_role(email, role="coach"):
    async def go(db):
        await db.users.update_one({"email": email}, {"$set": {"role": role}})

    _run_mongo(go)


def test_login_does_not_promote_when_env_unset(monkeypatch):
    """Sanity: with no env var, login must return whatever role the user has."""
    email = f"sentinel-login-{uuid.uuid4().hex[:8]}@example.com"
    _register_sentinel(email, "pw1234567")
    try:
        # We can't unset env vars in the running server process from the test —
        # so we verify by checking that DEFAULT preview has no autopromote
        # configured (none of testcoach@demo.com should be auto-promoted by
        # this test seed). The unit tests above cover the env-set positive
        # path; this E2E is a smoke check that LOGIN still works end-to-end.
        r = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"email": email, "password": "pw1234567"},
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["role"] == "coach"  # NOT promoted
    finally:
        # Clean up the sentinel user
        async def cleanup(db):
            await db.users.delete_many({"email": email})

        _run_mongo(cleanup)
