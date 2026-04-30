"""Tests for iter18: Platform avg processing-time chip on /api/coach-network/benchmarks."""
import requests
import uuid
from datetime import datetime, timezone, timedelta

from tests.conftest import BASE_URL, run_async as _run


def test_benchmarks_includes_processing_time_shape(auth_headers):
    r = requests.get(f"{BASE_URL}/api/coach-network/benchmarks", headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "processing_time" in data
    pt = data["processing_time"]
    for k in ("platform_avg_seconds", "your_avg_seconds", "your_samples"):
        assert k in pt, f"processing_time missing key {k}: {pt}"
    assert "samples" in data
    assert "processing_durations_aggregated" in data["samples"]


def test_benchmarks_processing_time_with_seeds(auth_headers):
    """Seed a mix of testcoach + other-user completed videos and confirm the avg math."""
    from db import db

    async def seed():
        u = await db.users.find_one({"email": "testcoach@demo.com"}, {"_id": 0, "id": 1})
        # Hide any existing completed videos (testcoach or otherwise) for determinism
        await db.videos.update_many(
            {"processing_status": "completed"},
            {"$set": {"_test_orig_status": "completed", "processing_status": "_test_hidden"}},
        )
        base = datetime.now(timezone.utc) - timedelta(hours=2)
        seeds = []
        # 2 testcoach durations → avg 90s
        for i, dur in enumerate([60, 120]):
            seeds.append({
                "id": f"test-cn-{uuid.uuid4().hex}", "user_id": u["id"], "_test_cn_seed": True,
                "processing_status": "completed", "filename": f"my-{i}.mp4", "is_deleted": False,
                "processing_started_at": base.isoformat(),
                "processing_completed_at": (base + timedelta(seconds=dur)).isoformat(),
            })
        # 3 other-user durations → combined platform avg with testcoach = (60+120+100+200+300)/5 = 156
        for i, dur in enumerate([100, 200, 300]):
            seeds.append({
                "id": f"test-cn-{uuid.uuid4().hex}", "user_id": f"synthetic-user-{i}", "_test_cn_seed": True,
                "processing_status": "completed", "filename": f"other-{i}.mp4", "is_deleted": False,
                "processing_started_at": base.isoformat(),
                "processing_completed_at": (base + timedelta(seconds=dur)).isoformat(),
            })
        await db.videos.insert_many(seeds)

    async def cleanup():
        await db.videos.delete_many({"_test_cn_seed": True})
        await db.videos.update_many(
            {"processing_status": "_test_hidden"},
            [{"$set": {"processing_status": "$_test_orig_status"}}, {"$unset": "_test_orig_status"}],
        )

    _run(seed())
    try:
        r = requests.get(f"{BASE_URL}/api/coach-network/benchmarks", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        pt = r.json()["processing_time"]
        assert pt["your_samples"] == 2
        assert pt["your_avg_seconds"] == 90.0
        assert pt["platform_avg_seconds"] == 156.0
        assert r.json()["samples"]["processing_durations_aggregated"] == 5
    finally:
        _run(cleanup())


def test_benchmarks_processing_time_discards_outliers(auth_headers):
    """Outliers (<10s or >2h) must be excluded from both avgs."""
    from db import db

    async def seed():
        u = await db.users.find_one({"email": "testcoach@demo.com"}, {"_id": 0, "id": 1})
        await db.videos.update_many(
            {"processing_status": "completed"},
            {"$set": {"_test_orig_status": "completed", "processing_status": "_test_hidden"}},
        )
        base = datetime.now(timezone.utc) - timedelta(hours=2)
        # Keep: 120s. Discard: 3s, 3h.
        docs = [
            {"id": f"test-cn-{uuid.uuid4().hex}", "user_id": u["id"], "_test_cn_seed": True,
             "processing_status": "completed", "filename": "k.mp4", "is_deleted": False,
             "processing_started_at": base.isoformat(),
             "processing_completed_at": (base + timedelta(seconds=120)).isoformat()},
            {"id": f"test-cn-{uuid.uuid4().hex}", "user_id": u["id"], "_test_cn_seed": True,
             "processing_status": "completed", "filename": "short.mp4", "is_deleted": False,
             "processing_started_at": base.isoformat(),
             "processing_completed_at": (base + timedelta(seconds=3)).isoformat()},
            {"id": f"test-cn-{uuid.uuid4().hex}", "user_id": u["id"], "_test_cn_seed": True,
             "processing_status": "completed", "filename": "long.mp4", "is_deleted": False,
             "processing_started_at": base.isoformat(),
             "processing_completed_at": (base + timedelta(hours=3)).isoformat()},
        ]
        await db.videos.insert_many(docs)

    async def cleanup():
        await db.videos.delete_many({"_test_cn_seed": True})
        await db.videos.update_many(
            {"processing_status": "_test_hidden"},
            [{"$set": {"processing_status": "$_test_orig_status"}}, {"$unset": "_test_orig_status"}],
        )

    _run(seed())
    try:
        r = requests.get(f"{BASE_URL}/api/coach-network/benchmarks", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        pt = r.json()["processing_time"]
        # Only 120s kept
        assert pt["your_samples"] == 1
        assert pt["your_avg_seconds"] == 120.0
        assert pt["platform_avg_seconds"] == 120.0
    finally:
        _run(cleanup())
