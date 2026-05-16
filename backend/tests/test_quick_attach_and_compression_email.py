"""
Tests for iter69:
  - GET  /api/me/last-imported-team — backs the "⚡ Quick attach" pill
  - POST /api/admin/processing-events/email-compression-help — backs the
    "Email fix" button on the Top Failed Videos panel

Both flows are stateful (write to user doc / compression_help_sent collection)
so we use sentinel users + clean up after.
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


def _login(email=ADMIN_EMAIL, password=ADMIN_PASS):
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()


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


# ---------------------------------------------------------------------------
# /api/me/last-imported-team
# ---------------------------------------------------------------------------

def test_last_imported_team_returns_null_when_never_used():
    """A coach who has never used the import-team-roster endpoint must get
    `{team_id: null}` (200) so the pill simply hides."""
    headers, payload = _login()
    user_id = payload.get("user", {}).get("id")
    # Ensure clean state — clear the field if any prior test left it
    _run_mongo(lambda db: db.users.update_one(
        {"id": user_id}, {"$unset": {"last_imported_team_id": "", "last_imported_team_at": ""}},
    ))

    r = requests.get(f"{BASE_URL}/api/me/last-imported-team", headers=headers, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["team_id"] is None
    assert body["team_name"] is None


def test_import_team_roster_updates_last_team_pointer():
    """After importing a team's roster into a match, the next call to
    /api/me/last-imported-team must return that team."""
    headers, payload = _login()

    # Create a team + match
    team_name = f"PyQuickAttach-{uuid.uuid4().hex[:6]}"
    team_resp = requests.post(
        f"{BASE_URL}/api/teams",
        params={"name": team_name, "season": "2026"},
        headers=headers, timeout=10,
    )
    team_resp.raise_for_status()
    team_id = team_resp.json()["id"]

    match_resp = requests.post(
        f"{BASE_URL}/api/matches",
        json={"team_home": "QA Home", "team_away": "QA Away", "date": "2026-05-16", "competition": "TEST"},
        headers=headers, timeout=10,
    )
    match_resp.raise_for_status()
    match_id = match_resp.json()["id"]

    try:
        r = requests.post(
            f"{BASE_URL}/api/matches/{match_id}/import-team-roster",
            json={"team_id": team_id}, headers=headers, timeout=15,
        )
        assert r.status_code == 200

        # Now the last-team pointer should reflect this
        r2 = requests.get(f"{BASE_URL}/api/me/last-imported-team", headers=headers, timeout=15)
        assert r2.status_code == 200
        body = r2.json()
        assert body["team_id"] == team_id
        assert body["team_name"] == team_name
        assert body["last_used_at"] is not None
    finally:
        # Cleanup
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=headers, timeout=10)
        requests.delete(f"{BASE_URL}/api/teams/{team_id}", headers=headers, timeout=10)


def test_last_imported_team_self_heals_when_team_deleted():
    """If the team was deleted after being marked as last-used, the endpoint
    must return null and silently clear the stale pointer."""
    headers, payload = _login()
    user_id = payload.get("user", {}).get("id")
    fake_team_id = f"deleted-team-{uuid.uuid4().hex[:8]}"

    # Manually plant a stale pointer
    _run_mongo(lambda db: db.users.update_one(
        {"id": user_id},
        {"$set": {
            "last_imported_team_id": fake_team_id,
            "last_imported_team_at": datetime.now(timezone.utc).isoformat(),
        }},
    ))

    r = requests.get(f"{BASE_URL}/api/me/last-imported-team", headers=headers, timeout=15)
    assert r.status_code == 200
    assert r.json()["team_id"] is None

    # And the pointer should be cleared on the user doc
    user_doc = _run_mongo(lambda db: db.users.find_one({"id": user_id}, {"_id": 0, "last_imported_team_id": 1}))
    assert "last_imported_team_id" not in (user_doc or {})


# ---------------------------------------------------------------------------
# /api/admin/processing-events/email-compression-help
# ---------------------------------------------------------------------------

def _seed_final_failure(video_id, user_id, size_gb=5.0, filename="huge.mp4"):
    async def go(db):
        await db.processing_events.insert_one({
            "id": str(uuid.uuid4()),
            "video_id": video_id,
            "user_id": user_id,
            "event_type": "final_failure",
            "tier_idx": 1,
            "tier_label": "all_tiers_exhausted",
            "failure_mode": "oom",
            "source_size_gb": size_gb,
            "error_message": "ffmpeg killed",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        await db.videos.insert_one({
            "id": video_id, "filename": filename, "user_id": user_id, "match_id": None,
        })

    _run_mongo(go)


def _cleanup_compression(video_id):
    async def go(db):
        await db.processing_events.delete_many({"video_id": video_id})
        await db.videos.delete_many({"id": video_id})
        await db.compression_help_sent.delete_many({"video_id": video_id})

    _run_mongo(go)


def test_compression_email_requires_admin():
    """Unauthenticated callers must be rejected."""
    r = requests.post(
        f"{BASE_URL}/api/admin/processing-events/email-compression-help",
        json={"video_id": "anything"},
        timeout=15,
    )
    assert r.status_code in (401, 403)


def test_compression_email_skips_when_no_email():
    """If the coach has no email on record, the endpoint must skip
    gracefully (NOT raise) and return a reason the admin can show in toast."""
    headers, payload = _login()
    admin_user_id = payload.get("user", {}).get("id")
    sentinel = f"sentinel-vid-{uuid.uuid4().hex[:8]}"

    # Seed an event tied to a fake user with NO email
    fake_uid = f"fake-uid-{uuid.uuid4().hex[:8]}"
    _seed_final_failure(sentinel, fake_uid)

    try:
        r = requests.post(
            f"{BASE_URL}/api/admin/processing-events/email-compression-help",
            json={"video_id": sentinel}, headers=headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Either no_user or no_email — both are graceful skips, not exceptions
        assert body["status"] == "skipped"
        assert "reason" in body
    finally:
        _cleanup_compression(sentinel)


def test_compression_email_404_when_no_failure_event():
    """Calling for a video_id with no final_failure event returns 404."""
    headers, _ = _login()
    r = requests.post(
        f"{BASE_URL}/api/admin/processing-events/email-compression-help",
        json={"video_id": f"nonexistent-{uuid.uuid4().hex}"},
        headers=headers, timeout=15,
    )
    assert r.status_code == 404


def test_compression_email_dedupes_repeat_clicks():
    """Calling twice on the same video MUST NOT email twice — the second call
    returns status 'already_sent'. Tested by pre-seeding the
    compression_help_sent record (simulating a prior successful send)."""
    headers, payload = _login()
    sentinel = f"sentinel-vid-{uuid.uuid4().hex[:8]}"
    fake_uid = f"fake-uid-{uuid.uuid4().hex[:8]}"
    _seed_final_failure(sentinel, fake_uid)

    # Pre-seed compression_help_sent as if we'd already emailed
    prior_sent = datetime.now(timezone.utc).isoformat()
    _run_mongo(lambda db: db.compression_help_sent.insert_one({
        "id": f"ch-{sentinel}",
        "video_id": sentinel,
        "to_email": "ghost@test.local",
        "sent_at": prior_sent,
        "sent_by_admin_id": "prior-admin",
    }))

    try:
        r = requests.post(
            f"{BASE_URL}/api/admin/processing-events/email-compression-help",
            json={"video_id": sentinel}, headers=headers, timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "already_sent"
        assert body["to_email"] == "ghost@test.local"
        assert body["sent_at"] == prior_sent
    finally:
        _cleanup_compression(sentinel)


def test_top_failed_surfaces_compression_sent_flag():
    """The top-failed endpoint must include compression_email_sent_at in each
    row so the frontend can render '✓ Sent' instead of the Email Fix button
    for already-handled rows."""
    headers, _ = _login()
    sentinel = f"sentinel-vid-{uuid.uuid4().hex[:8]}"
    fake_uid = f"fake-uid-{uuid.uuid4().hex[:8]}"
    _seed_final_failure(sentinel, fake_uid, size_gb=9.9)  # huge so it floats to top

    prior_sent = datetime.now(timezone.utc).isoformat()
    _run_mongo(lambda db: db.compression_help_sent.insert_one({
        "id": f"ch-{sentinel}",
        "video_id": sentinel,
        "to_email": "ghost@test.local",
        "sent_at": prior_sent,
    }))

    try:
        r = requests.get(
            f"{BASE_URL}/api/admin/processing-events/top-failed?hours=24&limit=20",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200
        rows = [v for v in r.json()["videos"] if v["video_id"] == sentinel]
        assert len(rows) == 1
        assert rows[0]["compression_email_sent_at"] == prior_sent
    finally:
        _cleanup_compression(sentinel)
