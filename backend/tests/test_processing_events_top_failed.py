"""
Tests for iter68: top-largest-failed-videos triage endpoint.

Endpoint: GET /api/admin/processing-events/top-failed?hours=N&limit=K

Behavior:
  - Admin-only (returns 401/403 otherwise).
  - Returns up to `limit` videos sorted by source_size_gb DESC.
  - Dedupes by video_id — multiple final_failure events for the same video
    only show up once.
  - Enriches each row with the source video filename, parent match label,
    and the coach's email/name so admin can DM them in one click.
  - Window is bounded by `hours` (cap 168). Anything older than that is
    excluded entirely.

These tests seed events directly into Mongo (same pattern as
test_processing_events.py) and clean up after with a sentinel video_id.
"""
import os
import uuid
import requests
import asyncio
from datetime import datetime, timedelta, timezone

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
    return {"Authorization": f"Bearer {r.json()['token']}"}


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


def _seed(events=None, videos=None, matches=None, users=None):
    async def go(db):
        if events:
            await db.processing_events.insert_many(events)
        if videos:
            await db.videos.insert_many(videos)
        if matches:
            await db.matches.insert_many(matches)
        if users:
            await db.users.insert_many(users)

    _run_mongo(go)


def _cleanup(sentinel_tag):
    async def go(db):
        await db.processing_events.delete_many({"video_id": {"$regex": f"^{sentinel_tag}"}})
        await db.videos.delete_many({"id": {"$regex": f"^{sentinel_tag}"}})
        await db.matches.delete_many({"id": {"$regex": f"^{sentinel_tag}"}})
        await db.users.delete_many({"id": {"$regex": f"^{sentinel_tag}"}})

    _run_mongo(go)


def test_top_failed_sorts_by_size_and_dedupes():
    """Three videos failed, one of them failed twice. Endpoint must return
    them sorted by size DESC and dedupe the repeat-failer."""
    headers = _login()
    tag = f"sentinel-{uuid.uuid4().hex[:8]}"
    vid_big = f"{tag}-big"
    vid_mid = f"{tag}-mid"
    vid_small = f"{tag}-small"
    coach_id = f"{tag}-coach"
    match_id = f"{tag}-match"
    now = datetime.now(timezone.utc).isoformat()

    events = [
        # Big video failed once at 8.5 GB
        {"id": str(uuid.uuid4()), "video_id": vid_big, "user_id": coach_id,
         "event_type": "final_failure", "tier_idx": 1, "tier_label": "180p/6fps [retry-1]",
         "failure_mode": "oom", "source_size_gb": 8.5, "duration_seconds": 412.0,
         "error_message": "ffmpeg killed (signal 9)", "created_at": now},
        # Mid video failed twice — only the bigger event should show
        {"id": str(uuid.uuid4()), "video_id": vid_mid, "user_id": coach_id,
         "event_type": "final_failure", "tier_idx": 0, "tier_label": "360p/12fps",
         "failure_mode": "timeout", "source_size_gb": 3.2,
         "created_at": now},
        {"id": str(uuid.uuid4()), "video_id": vid_mid, "user_id": coach_id,
         "event_type": "final_failure", "tier_idx": 1, "tier_label": "180p/6fps [retry-1]",
         "failure_mode": "oom", "source_size_gb": 3.2,
         "created_at": now},
        # Small video
        {"id": str(uuid.uuid4()), "video_id": vid_small, "user_id": coach_id,
         "event_type": "final_failure", "tier_idx": 0, "tier_label": "360p/12fps",
         "failure_mode": "moov_missing", "source_size_gb": 0.8,
         "created_at": now},
    ]
    videos = [
        {"id": vid_big, "filename": "big_game.mp4", "match_id": match_id, "user_id": coach_id},
        {"id": vid_mid, "filename": "mid_game.mp4", "match_id": match_id, "user_id": coach_id},
        {"id": vid_small, "filename": "tiny_game.mp4", "match_id": match_id, "user_id": coach_id},
    ]
    matches = [{
        "id": match_id, "user_id": coach_id,
        "team_home": "Sentinel United", "team_away": "Sentinel City", "date": "2026-05-15",
    }]
    users = [{"id": coach_id, "email": "sentinel-coach@test.local", "name": "Sentinel Coach"}]

    _seed(events=events, videos=videos, matches=matches, users=users)
    try:
        r = requests.get(
            f"{BASE_URL}/api/admin/processing-events/top-failed?hours=24&limit=5",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["window_hours"] == 24

        # Our 3 sentinel videos must appear, in size order, deduped
        sentinel_rows = [v for v in body["videos"] if v["video_id"].startswith(tag)]
        ids = [v["video_id"] for v in sentinel_rows]
        # Must include all three; mid must appear ONCE (deduped)
        assert vid_big in ids
        assert vid_mid in ids
        assert vid_small in ids
        assert ids.count(vid_mid) == 1

        # Order: big > mid > small among our sentinels
        big_pos = ids.index(vid_big)
        mid_pos = ids.index(vid_mid)
        small_pos = ids.index(vid_small)
        assert big_pos < mid_pos < small_pos

        # Enrichment must be present
        big_row = sentinel_rows[big_pos]
        assert big_row["filename"] == "big_game.mp4"
        assert big_row["coach_email"] == "sentinel-coach@test.local"
        assert big_row["match_label"] == "Sentinel United vs Sentinel City"
        assert big_row["failure_mode"] == "oom"
        assert big_row["size_gb"] == 8.5
    finally:
        _cleanup(tag)


def test_top_failed_respects_window():
    """An old failure (outside the `hours` window) must NOT appear."""
    headers = _login()
    tag = f"sentinel-{uuid.uuid4().hex[:8]}"
    vid_old = f"{tag}-old"
    vid_recent = f"{tag}-recent"
    coach_id = f"{tag}-coach"
    now = datetime.now(timezone.utc)
    old_iso = (now - timedelta(hours=72)).isoformat()
    recent_iso = now.isoformat()

    events = [
        {"id": str(uuid.uuid4()), "video_id": vid_old, "user_id": coach_id,
         "event_type": "final_failure", "tier_idx": 0,
         "failure_mode": "oom", "source_size_gb": 9.9,  # huge but old — must NOT appear
         "created_at": old_iso},
        {"id": str(uuid.uuid4()), "video_id": vid_recent, "user_id": coach_id,
         "event_type": "final_failure", "tier_idx": 0,
         "failure_mode": "timeout", "source_size_gb": 1.1,
         "created_at": recent_iso},
    ]
    videos = [
        {"id": vid_old, "filename": "old.mp4", "user_id": coach_id},
        {"id": vid_recent, "filename": "recent.mp4", "user_id": coach_id},
    ]
    _seed(events=events, videos=videos)
    try:
        r = requests.get(
            f"{BASE_URL}/api/admin/processing-events/top-failed?hours=24&limit=10",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200
        ids = [v["video_id"] for v in r.json()["videos"]]
        assert vid_old not in ids
        assert vid_recent in ids
    finally:
        _cleanup(tag)


def test_top_failed_handles_missing_joins():
    """Video doc was hard-deleted before admin opened the panel. Row must
    still appear with filename '(deleted)' instead of crashing."""
    headers = _login()
    tag = f"sentinel-{uuid.uuid4().hex[:8]}"
    vid_orphan = f"{tag}-orphan"
    coach_id = f"{tag}-coach"
    now_iso = datetime.now(timezone.utc).isoformat()

    events = [{
        "id": str(uuid.uuid4()), "video_id": vid_orphan, "user_id": coach_id,
        "event_type": "final_failure", "tier_idx": 0,
        "failure_mode": "no_space", "source_size_gb": 5.0,
        "created_at": now_iso,
    }]
    # NO videos document seeded — the video was "deleted"
    _seed(events=events)
    try:
        r = requests.get(
            f"{BASE_URL}/api/admin/processing-events/top-failed?hours=24&limit=10",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200
        orphans = [v for v in r.json()["videos"] if v["video_id"] == vid_orphan]
        assert len(orphans) == 1
        assert orphans[0]["filename"] == "(deleted)"
        assert orphans[0]["size_gb"] == 5.0
    finally:
        _cleanup(tag)


def test_top_failed_requires_admin():
    """Unauthenticated callers must be rejected."""
    r = requests.get(f"{BASE_URL}/api/admin/processing-events/top-failed", timeout=15)
    assert r.status_code in (401, 403)
