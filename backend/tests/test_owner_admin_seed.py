"""
Tests for iter77: one-time owner-admin seed migration on server startup.

User context: production owner couldn't access /admin/processing-events.
The iter76 ADMIN_AUTOPROMOTE_EMAIL env var path is unusable on their
Emergent plan because the secrets UI isn't exposed. iter77 ships a
hardcoded one-time migration that runs on startup, finds the owner email
in the users collection, promotes them to admin, and records a marker in
system_migrations so subsequent restarts are no-ops.

Behavior contract:
  - User registered + role='coach' → promoted to 'admin', marker recorded
  - User already 'admin' → no DB write to users, marker recorded
  - User already 'owner' → no DB write, marker recorded
  - User not registered yet → no marker (will retry on next boot)
  - Marker already present → full no-op
  - DB error during promotion → swallowed, no marker (will retry)

Subprocess-isolated like other iter70/iter75 integration tests so Motor's
event-loop binding doesn't leak between sibling test files.
"""
import os
import sys
import subprocess
import textwrap

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_integration_script(script: str) -> dict:
    full = textwrap.dedent(f"""
        import os, sys, asyncio, json, uuid
        sys.path.insert(0, {_BACKEND!r})
        os.chdir({_BACKEND!r})
        from dotenv import load_dotenv
        load_dotenv()

        async def _main():
{textwrap.indent(textwrap.dedent(script), '            ')}

        try:
            result = asyncio.run(_main())
            print("__OK__" + json.dumps(result))
        except Exception as e:
            print("__ERR__" + repr(e))
            raise
    """)
    proc = subprocess.run(
        [sys.executable, "-c", full],
        capture_output=True, text=True, timeout=60, cwd=_BACKEND,
    )
    assert proc.returncode == 0, f"Subprocess failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    line = next((l for l in proc.stdout.splitlines() if l.startswith("__OK__")), None)
    assert line, f"No __OK__ marker:\n{proc.stdout}\n{proc.stderr}"
    import json as _json
    return _json.loads(line[len("__OK__"):])


def test_seed_promotes_existing_coach_owner():
    """Seed a sentinel user matching the owner email with role=coach. Run the
    migration → user must be flipped to admin AND a marker must be recorded."""
    script = """
        from motor.motor_asyncio import AsyncIOMotorClient
        from server import _seed_owner_admin_once
        import server as srv

        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        # Plant a sentinel user matching the hardcoded owner email. We'll
        # restore the real (or absence of) user after the test.
        OWNER = "ben.buursma@gmail.com"
        sentinel_id = "iter77-test-" + uuid.uuid4().hex[:8]
        existing = await db.users.find_one({"email": {"$regex": "^"+OWNER+"$", "$options": "i"}}, {"_id": 0})

        # If the real owner is already in the DB, snapshot their role + skip
        # the seed insert (we don't want to clobber prod data). Otherwise
        # plant a sentinel coach we can clean up.
        if not existing:
            await db.users.insert_one({
                "id": sentinel_id, "email": OWNER, "role": "coach",
                "name": "Sentinel Owner", "password": "fake",
            })
        else:
            sentinel_id = existing["id"]
            await db.users.update_one({"id": sentinel_id}, {"$set": {"role": "coach"}})

        # Clear any pre-existing marker so the migration actually runs
        await db.system_migrations.delete_many({"id": "iter77_owner_admin_seed"})

        # Patch the sleep so the test doesn't wait 3s
        orig_sleep = srv.asyncio.sleep
        srv.asyncio.sleep = lambda *a, **kw: orig_sleep(0)
        try:
            await _seed_owner_admin_once()
        finally:
            srv.asyncio.sleep = orig_sleep

        promoted = await db.users.find_one({"id": sentinel_id}, {"_id": 0, "role": 1})
        marker = await db.system_migrations.find_one({"id": "iter77_owner_admin_seed"}, {"_id": 0})

        # Cleanup: drop the sentinel if we inserted it; restore real owner role
        if not existing:
            await db.users.delete_many({"id": sentinel_id})
        else:
            await db.users.update_one(
                {"id": sentinel_id}, {"$set": {"role": existing.get("role") or "coach"}}
            )
        await db.system_migrations.delete_many({"id": "iter77_owner_admin_seed"})
        client.close()

        return {"role": promoted.get("role"), "marker_present": marker is not None}
    """
    result = _run_integration_script(script)
    assert result["role"] == "admin"
    assert result["marker_present"] is True


def test_seed_idempotent_when_marker_present():
    """If the marker already exists, the migration must NOT touch the user."""
    script = """
        from motor.motor_asyncio import AsyncIOMotorClient
        from server import _seed_owner_admin_once
        import server as srv
        from datetime import datetime, timezone

        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        OWNER = "ben.buursma@gmail.com"
        sentinel_id = "iter77-idempotent-" + uuid.uuid4().hex[:8]
        existing = await db.users.find_one({"email": {"$regex": "^"+OWNER+"$", "$options": "i"}}, {"_id": 0})

        if not existing:
            await db.users.insert_one({
                "id": sentinel_id, "email": OWNER, "role": "coach",
                "name": "Idempotent Sentinel", "password": "fake",
            })
        else:
            sentinel_id = existing["id"]
            await db.users.update_one({"id": sentinel_id}, {"$set": {"role": "coach"}})

        # Plant the marker so the migration short-circuits
        await db.system_migrations.delete_many({"id": "iter77_owner_admin_seed"})
        await db.system_migrations.insert_one({
            "id": "iter77_owner_admin_seed",
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "promoted_email": OWNER,
        })

        orig_sleep = srv.asyncio.sleep
        srv.asyncio.sleep = lambda *a, **kw: orig_sleep(0)
        try:
            await _seed_owner_admin_once()
        finally:
            srv.asyncio.sleep = orig_sleep

        post = await db.users.find_one({"id": sentinel_id}, {"_id": 0, "role": 1})

        # Cleanup
        if not existing:
            await db.users.delete_many({"id": sentinel_id})
        else:
            await db.users.update_one(
                {"id": sentinel_id}, {"$set": {"role": existing.get("role") or "coach"}}
            )
        await db.system_migrations.delete_many({"id": "iter77_owner_admin_seed"})
        client.close()

        return {"role": post.get("role")}
    """
    result = _run_integration_script(script)
    # Role must STILL be coach — marker prevented the migration from firing
    assert result["role"] == "coach"


def test_seed_skips_when_user_not_registered():
    """If no user matches the owner email, do NOT record a marker — leave
    the migration to retry on a future boot."""
    script = """
        from motor.motor_asyncio import AsyncIOMotorClient
        from server import _seed_owner_admin_once
        import server as srv

        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        OWNER = "ben.buursma@gmail.com"
        existing = await db.users.find_one({"email": {"$regex": "^"+OWNER+"$", "$options": "i"}}, {"_id": 0})
        prior_role = (existing or {}).get("role")

        # Force the no-user condition by temporarily removing the user if
        # they exist (we'll restore after).
        if existing:
            await db.users.update_one(
                {"id": existing["id"]},
                {"$set": {"email": "MOVED_FOR_TEST-" + existing["email"]}},
            )

        await db.system_migrations.delete_many({"id": "iter77_owner_admin_seed"})

        orig_sleep = srv.asyncio.sleep
        srv.asyncio.sleep = lambda *a, **kw: orig_sleep(0)
        try:
            await _seed_owner_admin_once()
        finally:
            srv.asyncio.sleep = orig_sleep

        marker = await db.system_migrations.find_one({"id": "iter77_owner_admin_seed"}, {"_id": 0})

        # Restore
        if existing:
            await db.users.update_one(
                {"id": existing["id"]},
                {"$set": {"email": existing["email"], "role": prior_role}},
            )
        await db.system_migrations.delete_many({"id": "iter77_owner_admin_seed"})
        client.close()

        return {"marker_present": marker is not None}
    """
    result = _run_integration_script(script)
    # No marker — migration must retry on next boot when the user registers
    assert result["marker_present"] is False
