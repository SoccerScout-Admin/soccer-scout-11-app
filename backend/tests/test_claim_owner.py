"""
Tests for iter78: POST /api/admin/claim-owner — no-secret self-promote
endpoint reserved for the hardcoded canonical app owner.

Designed as a manual fallback when both iter76 (env-var ADMIN_AUTOPROMOTE)
and iter77 (startup migration) paths fail to promote the owner — e.g., env
var unset on the user's Emergent plan, migration marker recorded before
owner registered, or email-case mismatches.

Behavior:
  - Unauthenticated → 401/403
  - Authenticated user NOT in owner allowlist → 403 (never silent no-op)
  - Authenticated owner with role=coach → role flipped to admin, response
    `{status: "promoted", role: "admin"}`
  - Authenticated owner already admin/owner → idempotent
    `{status: "already_admin", ...}`
"""
import os
import uuid
import asyncio
import requests
import bcrypt
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

BASE_URL = os.environ.get("BASE_URL") or "https://scout-lens.preview.emergentagent.com"


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


def _login(email, password):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password}, timeout=15,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _make_sentinel_user(email, role="coach"):
    """Register a sentinel user with bcrypt-hashed password 'pw1234567'."""
    pw_hash = bcrypt.hashpw(b"pw1234567", bcrypt.gensalt()).decode()
    uid = f"sentinel-{uuid.uuid4().hex[:8]}"

    async def go(db):
        await db.users.delete_many({"email": {"$regex": f"^{email}$", "$options": "i"}})
        await db.users.insert_one({
            "id": uid, "email": email, "name": "Sentinel Owner",
            "password": pw_hash, "role": role,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    _run_mongo(go)
    return uid


def _cleanup_user(email):
    _run_mongo(lambda db: db.users.delete_many({"email": {"$regex": f"^{email}$", "$options": "i"}}))


# ---------------------------------------------------------------------------
# Endpoint behavior
# ---------------------------------------------------------------------------

def test_claim_owner_requires_auth():
    r = requests.post(f"{BASE_URL}/api/admin/claim-owner", timeout=10)
    assert r.status_code in (401, 403)


def test_claim_owner_rejects_non_owner_user():
    """Authenticated user whose email isn't on the hardcoded allowlist must
    get a 403 — never a silent no-op, so we can debug accidental hits."""
    email = f"intruder-{uuid.uuid4().hex[:6]}@example.com"
    _make_sentinel_user(email, role="coach")
    try:
        headers = _login(email, "pw1234567")
        r = requests.post(f"{BASE_URL}/api/admin/claim-owner", headers=headers, timeout=15)
        assert r.status_code == 403
        assert "owner" in r.text.lower()
    finally:
        _cleanup_user(email)


def test_claim_owner_promotes_canonical_owner():
    """Canonical owner email with role=coach → promoted to admin."""
    email = "ben.buursma@gmail.com"
    # Snapshot AND remove any existing user (case-insensitively) so we
    # control the login surface end-to-end. Restored afterward.
    snapshot = _run_mongo(lambda db: db.users.find_one(
        {"email": {"$regex": f"^{email}$", "$options": "i"}}, {"_id": 0},
    ))

    pw_hash = bcrypt.hashpw(b"pw1234567", bcrypt.gensalt()).decode()
    sentinel_uid = f"sentinel-claim-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        # Clear any pre-existing variants (different case, etc.)
        await db.users.delete_many({"email": {"$regex": f"^{email}$", "$options": "i"}})
        await db.users.insert_one({
            "id": sentinel_uid, "email": email, "name": "Sentinel Ben",
            "password": pw_hash, "role": "coach",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    _run_mongo(setup)

    try:
        headers = _login(email, "pw1234567")
        r = requests.post(f"{BASE_URL}/api/admin/claim-owner", headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "promoted"
        assert body["role"] == "admin"

        post = _run_mongo(lambda db: db.users.find_one(
            {"id": sentinel_uid}, {"_id": 0, "role": 1},
        ))
        assert post["role"] == "admin"
    finally:
        # Cleanup: remove sentinel, restore snapshot if any
        async def cleanup(db):
            await db.users.delete_many({"id": sentinel_uid})
            if snapshot:
                # Re-insert original (preserve _id-less form from snapshot)
                await db.users.insert_one(snapshot)

        _run_mongo(cleanup)


def test_claim_owner_idempotent_when_already_admin():
    """Calling for an already-admin owner returns `already_admin`, no error."""
    email = "ben.buursma@gmail.com"
    snapshot = _run_mongo(lambda db: db.users.find_one(
        {"email": {"$regex": f"^{email}$", "$options": "i"}}, {"_id": 0},
    ))
    pw_hash = bcrypt.hashpw(b"pw1234567", bcrypt.gensalt()).decode()
    sentinel_uid = f"sentinel-idem-{uuid.uuid4().hex[:8]}"

    async def setup(db):
        await db.users.delete_many({"email": {"$regex": f"^{email}$", "$options": "i"}})
        await db.users.insert_one({
            "id": sentinel_uid, "email": email, "name": "Idem Ben",
            "password": pw_hash, "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    _run_mongo(setup)

    try:
        headers = _login(email, "pw1234567")
        r = requests.post(f"{BASE_URL}/api/admin/claim-owner", headers=headers, timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "already_admin"
        assert body["role"] == "admin"
    finally:
        async def cleanup(db):
            await db.users.delete_many({"id": sentinel_uid})
            if snapshot:
                await db.users.insert_one(snapshot)

        _run_mongo(cleanup)
