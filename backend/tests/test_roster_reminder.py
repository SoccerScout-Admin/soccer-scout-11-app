"""
Tests for iter74: empty-roster reminder admin tool.

Endpoints:
  - GET  /api/admin/empty-roster-matches?days=N&limit=K
  - POST /api/admin/empty-roster-matches/send-reminder body: {match_id}

Both are admin-only. List endpoint joins videos + players + users to surface
"completed video but 0 players" — high-leverage triage because AI tactical
attribution silently produces 0 player-credited events on these matches.
Send-reminder is de-duped via roster_reminder_sent collection.
"""
import os
import uuid
import asyncio
import requests
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

BASE_URL = os.environ.get("BASE_URL") or "https://scout-lens.preview.emergentagent.com"
TEST_EMAIL = "testcoach@demo.com"
TEST_PASS = "password123"


def _login():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASS}, timeout=15,
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


def _seed_empty_roster_match(coach_user_id, label="Sentinel"):
    """Create a match + a 'completed' video with NO players in players
    collection. Returns the match_id for cleanup."""
    mid = f"sentinel-match-{uuid.uuid4().hex[:8]}"
    vid = f"sentinel-vid-{uuid.uuid4().hex[:8]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    async def go(db):
        await db.matches.insert_one({
            "id": mid, "user_id": coach_user_id,
            "team_home": f"{label} A", "team_away": f"{label} B",
            "date": "2026-05-16",
            "created_at": now_iso,
        })
        await db.videos.insert_one({
            "id": vid, "match_id": mid, "user_id": coach_user_id,
            "processing_status": "completed",
            "uploaded_at": now_iso,
            "filename": "x.mp4",
        })

    _run_mongo(go)
    return mid, vid


def _cleanup(mid, vid):
    async def go(db):
        await db.matches.delete_many({"id": mid})
        await db.videos.delete_many({"id": vid})
        await db.players.delete_many({"match_id": mid})
        await db.roster_reminder_sent.delete_many({"match_id": mid})

    _run_mongo(go)


def test_list_empty_roster_requires_admin():
    r = requests.get(f"{BASE_URL}/api/admin/empty-roster-matches", timeout=10)
    assert r.status_code in (401, 403)


def test_send_reminder_requires_admin():
    r = requests.post(
        f"{BASE_URL}/api/admin/empty-roster-matches/send-reminder",
        json={"match_id": "anything"}, timeout=10,
    )
    assert r.status_code in (401, 403)


def test_list_returns_seeded_empty_roster_match():
    """A match with completed video + 0 players must surface in the list."""
    headers, payload = _login()
    user_id = payload["user"]["id"]
    mid, vid = _seed_empty_roster_match(user_id)
    try:
        r = requests.get(
            f"{BASE_URL}/api/admin/empty-roster-matches?days=2&limit=50",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        ids = [m["match_id"] for m in body["matches"]]
        assert mid in ids
        row = next(m for m in body["matches"] if m["match_id"] == mid)
        assert row["coach_email"] == TEST_EMAIL
        assert row["reminder_sent_at"] is None
    finally:
        _cleanup(mid, vid)


def test_list_excludes_matches_with_players():
    """If we add even 1 player to the match, it must drop out of the list."""
    headers, payload = _login()
    user_id = payload["user"]["id"]
    mid, vid = _seed_empty_roster_match(user_id, label="HasPlayers")

    # Add a player
    _run_mongo(lambda db: db.players.insert_one({
        "id": str(uuid.uuid4()), "match_id": mid, "user_id": user_id,
        "name": "Sentinel Player", "number": 10,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))

    try:
        r = requests.get(
            f"{BASE_URL}/api/admin/empty-roster-matches?days=2&limit=50",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200
        ids = [m["match_id"] for m in r.json()["matches"]]
        assert mid not in ids
    finally:
        _cleanup(mid, vid)


def test_send_reminder_404_on_unknown_match():
    headers, _ = _login()
    r = requests.post(
        f"{BASE_URL}/api/admin/empty-roster-matches/send-reminder",
        json={"match_id": f"nonexistent-{uuid.uuid4().hex}"},
        headers=headers, timeout=10,
    )
    assert r.status_code == 404


def test_send_reminder_skipped_when_roster_already_populated():
    """If the coach attached players between dashboard load and admin click,
    the endpoint must skip — don't send a stale reminder."""
    headers, payload = _login()
    user_id = payload["user"]["id"]
    mid, vid = _seed_empty_roster_match(user_id, label="Race")
    # Populate the roster RIGHT before sending
    _run_mongo(lambda db: db.players.insert_one({
        "id": str(uuid.uuid4()), "match_id": mid, "user_id": user_id,
        "name": "Late Arrival", "number": 7,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }))

    try:
        r = requests.post(
            f"{BASE_URL}/api/admin/empty-roster-matches/send-reminder",
            json={"match_id": mid}, headers=headers, timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "skipped"
        assert "no longer needed" in body["reason"]
    finally:
        _cleanup(mid, vid)


def test_send_reminder_dedupes_repeat_clicks():
    """Pre-seed a roster_reminder_sent row → next call returns
    `already_sent` with the prior timestamp, never sends a second email."""
    headers, payload = _login()
    user_id = payload["user"]["id"]
    mid, vid = _seed_empty_roster_match(user_id, label="DedupeCheck")
    prior_iso = datetime.now(timezone.utc).isoformat()
    _run_mongo(lambda db: db.roster_reminder_sent.insert_one({
        "id": f"rr-{mid}", "match_id": mid,
        "to_email": "ghost@example.com",
        "sent_at": prior_iso, "sent_by_admin_id": "prior",
    }))

    try:
        r = requests.post(
            f"{BASE_URL}/api/admin/empty-roster-matches/send-reminder",
            json={"match_id": mid}, headers=headers, timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "already_sent"
        assert body["to_email"] == "ghost@example.com"
        assert body["sent_at"] == prior_iso
    finally:
        _cleanup(mid, vid)


def test_list_surfaces_reminder_sent_flag():
    """After a reminder has been sent, the list endpoint must include
    `reminder_sent_at` so the UI can render '✓ Sent' instead of the button."""
    headers, payload = _login()
    user_id = payload["user"]["id"]
    mid, vid = _seed_empty_roster_match(user_id, label="SentFlag")
    sent_iso = datetime.now(timezone.utc).isoformat()
    _run_mongo(lambda db: db.roster_reminder_sent.insert_one({
        "id": f"rr-{mid}", "match_id": mid,
        "to_email": "x@example.com", "sent_at": sent_iso,
    }))

    try:
        r = requests.get(
            f"{BASE_URL}/api/admin/empty-roster-matches?days=2&limit=50",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200
        row = next((m for m in r.json()["matches"] if m["match_id"] == mid), None)
        assert row is not None
        assert row["reminder_sent_at"] == sent_iso
    finally:
        _cleanup(mid, vid)
