"""Tests for GET /api/videos/processing-eta-stats."""
import requests
import uuid
from datetime import datetime, timezone, timedelta

from tests.conftest import BASE_URL, run_async as _run


def test_eta_stats_requires_auth():
    r = requests.get(f"{BASE_URL}/api/videos/processing-eta-stats", timeout=15)
    assert r.status_code == 401


def test_eta_stats_empty_when_no_completed_videos(auth_headers):
    """Empty case is well-defined."""
    from db import db
    async def wipe():
        # Save & remove any completed videos for testcoach so this test is deterministic.
        user = await db.users.find_one({"email": "testcoach@demo.com"}, {"_id": 0, "id": 1})
        # Pull aside any completed videos (don't actually delete — just temporarily rename status)
        await db.videos.update_many(
            {"user_id": user["id"], "processing_status": "completed"},
            {"$set": {"_test_orig_status": "completed", "processing_status": "_test_hidden"}},
        )
    async def restore():
        user = await db.users.find_one({"email": "testcoach@demo.com"}, {"_id": 0, "id": 1})
        await db.videos.update_many(
            {"user_id": user["id"], "processing_status": "_test_hidden"},
            [{"$set": {"processing_status": "$_test_orig_status"}}, {"$unset": "_test_orig_status"}],
        )
    _run(wipe())
    try:
        r = requests.get(f"{BASE_URL}/api/videos/processing-eta-stats", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["avg_seconds"] is None
        assert data["samples"] == 0
    finally:
        _run(restore())


def test_eta_stats_averages_completed_durations(auth_headers):
    """Seed 3 fake completed videos with known durations → avg should match."""
    from db import db

    async def seed_and_run():
        user = await db.users.find_one({"email": "testcoach@demo.com"}, {"_id": 0, "id": 1})
        # Hide existing completed videos so the avg is deterministic
        await db.videos.update_many(
            {"user_id": user["id"], "processing_status": "completed"},
            {"$set": {"_test_orig_status": "completed", "processing_status": "_test_hidden"}},
        )
        # Seed 3 completed videos with durations 60s, 120s, 180s → avg = 120
        seeds = []
        base_time = datetime.now(timezone.utc) - timedelta(hours=2)
        for i, dur in enumerate([60, 120, 180]):
            vid = {
                "id": f"test-eta-{uuid.uuid4().hex}",
                "user_id": user["id"],
                "processing_status": "completed",
                "processing_started_at": (base_time + timedelta(minutes=i * 10)).isoformat(),
                "processing_completed_at": (base_time + timedelta(minutes=i * 10, seconds=dur)).isoformat(),
                "filename": f"seed-{i}.mp4",
                "is_deleted": False,
                "_test_seed": True,
            }
            seeds.append(vid)
        await db.videos.insert_many(seeds)
        return seeds

    async def cleanup(seeds):
        user = await db.users.find_one({"email": "testcoach@demo.com"}, {"_id": 0, "id": 1})
        await db.videos.delete_many({"_test_seed": True})
        await db.videos.update_many(
            {"user_id": user["id"], "processing_status": "_test_hidden"},
            [{"$set": {"processing_status": "$_test_orig_status"}}, {"$unset": "_test_orig_status"}],
        )

    seeds = _run(seed_and_run())
    try:
        r = requests.get(f"{BASE_URL}/api/videos/processing-eta-stats", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["samples"] == 3
        assert data["avg_seconds"] == 120.0
    finally:
        _run(cleanup(seeds))


def test_eta_stats_discards_outliers(auth_headers):
    """Durations < 10s or > 7200s should be discarded."""
    from db import db

    async def seed():
        user = await db.users.find_one({"email": "testcoach@demo.com"}, {"_id": 0, "id": 1})
        await db.videos.update_many(
            {"user_id": user["id"], "processing_status": "completed"},
            {"$set": {"_test_orig_status": "completed", "processing_status": "_test_hidden"}},
        )
        base_time = datetime.now(timezone.utc) - timedelta(hours=2)
        seeds = [
            # Keep (normal): 120s
            {"_test_seed": True, "id": f"test-eta-{uuid.uuid4().hex}", "user_id": user["id"],
             "processing_status": "completed", "filename": "ok.mp4", "is_deleted": False,
             "processing_started_at": base_time.isoformat(),
             "processing_completed_at": (base_time + timedelta(seconds=120)).isoformat()},
            # Discard (too short): 5s
            {"_test_seed": True, "id": f"test-eta-{uuid.uuid4().hex}", "user_id": user["id"],
             "processing_status": "completed", "filename": "short.mp4", "is_deleted": False,
             "processing_started_at": base_time.isoformat(),
             "processing_completed_at": (base_time + timedelta(seconds=5)).isoformat()},
            # Discard (too long): 3 hours
            {"_test_seed": True, "id": f"test-eta-{uuid.uuid4().hex}", "user_id": user["id"],
             "processing_status": "completed", "filename": "long.mp4", "is_deleted": False,
             "processing_started_at": base_time.isoformat(),
             "processing_completed_at": (base_time + timedelta(hours=3)).isoformat()},
        ]
        await db.videos.insert_many(seeds)

    async def restore():
        user = await db.users.find_one({"email": "testcoach@demo.com"}, {"_id": 0, "id": 1})
        await db.videos.delete_many({"_test_seed": True})
        await db.videos.update_many(
            {"user_id": user["id"], "processing_status": "_test_hidden"},
            [{"$set": {"processing_status": "$_test_orig_status"}}, {"$unset": "_test_orig_status"}],
        )

    _run(seed())
    try:
        r = requests.get(f"{BASE_URL}/api/videos/processing-eta-stats", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["samples"] == 1  # Only the 120s kept
        assert data["avg_seconds"] == 120.0
    finally:
        _run(restore())
