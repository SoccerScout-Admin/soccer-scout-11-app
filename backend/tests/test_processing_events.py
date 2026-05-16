"""
Tests for iter64: processing_events analytics endpoints.

Two admin-only endpoints:
  - GET /api/admin/processing-events/stats?days=N → aggregated counts + rates
  - GET /api/admin/processing-events/recent?limit=N&event_type=...&failure_mode=...

These power the admin's view of:
  - How often the iter63 auto-retry actually saves a user (retry_save_rate)
  - Whether OOMs are creeping up (justifies bumping pod memory)
  - The slowest tier label (for sizing decisions)
"""
import os
import uuid
import requests
from datetime import datetime, timezone

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


def _seed_events(events):
    """Insert events directly via Motor. Tests run side-by-side with prod data
    so we always tag with a unique sentinel video_id and clean up after."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv()
    import asyncio

    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        await db.processing_events.insert_many(events)
        client.close()

    asyncio.get_event_loop().run_until_complete(run())


def _delete_sentinel(sentinel_video_id):
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv()
    import asyncio

    async def run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        await db.processing_events.delete_many({"video_id": sentinel_video_id})
        client.close()

    asyncio.get_event_loop().run_until_complete(run())


def test_stats_returns_aggregated_counts():
    headers = _login()
    sentinel = f"sentinel-{uuid.uuid4()}"
    now_iso = datetime.now(timezone.utc).isoformat()
    events = [
        {"id": str(uuid.uuid4()), "video_id": sentinel, "user_id": "u1",
         "event_type": "tier_attempt", "tier_idx": 0, "tier_label": "360p/12fps/crf35",
         "failure_mode": None, "source_size_gb": 1.5, "created_at": now_iso},
        {"id": str(uuid.uuid4()), "video_id": sentinel, "user_id": "u1",
         "event_type": "tier_failed", "tier_idx": 0, "tier_label": "360p/12fps/crf35",
         "failure_mode": "oom", "source_size_gb": 1.5, "created_at": now_iso},
        {"id": str(uuid.uuid4()), "video_id": sentinel, "user_id": "u1",
         "event_type": "tier_succeeded", "tier_idx": 1, "tier_label": "180p/6fps/crf42 [retry-1]",
         "failure_mode": None, "source_size_gb": 1.5, "output_size_mb": 45.2,
         "created_at": now_iso},
        {"id": str(uuid.uuid4()), "video_id": sentinel, "user_id": "u1",
         "event_type": "final_success", "tier_idx": 1, "tier_label": "180p/6fps/crf42 [retry-1]",
         "source_size_gb": 1.5, "output_size_mb": 45.2, "created_at": now_iso},
    ]
    _seed_events(events)
    try:
        r = requests.get(f"{BASE_URL}/api/admin/processing-events/stats?days=7", headers=headers, timeout=15)
        assert r.status_code == 200
        body = r.json()

        # The endpoint window is 7 days, and we just inserted 4 events. They
        # MAY share the window with other test runs / real data, so we check
        # >= rather than ==.
        assert body["total_events"] >= 4
        assert body["by_event_type"].get("tier_attempt", 0) >= 1
        assert body["by_event_type"].get("tier_failed", 0) >= 1
        assert body["by_event_type"].get("tier_succeeded", 0) >= 1
        assert body["by_event_type"].get("final_success", 0) >= 1
        assert body["by_failure_mode"].get("oom", 0) >= 1
        assert body["summary"]["tier0_oom_count"] >= 1
        assert body["summary"]["tier1_recoveries"] >= 1
        # Retry save rate should be calculable now (>= 1 oom + >= 1 recovery)
        assert body["summary"]["retry_save_rate_pct"] is not None
    finally:
        _delete_sentinel(sentinel)


def test_recent_filter_by_event_type():
    headers = _login()
    sentinel = f"sentinel-{uuid.uuid4()}"
    now_iso = datetime.now(timezone.utc).isoformat()
    events = [
        {"id": str(uuid.uuid4()), "video_id": sentinel, "user_id": "u1",
         "event_type": "tier_failed", "tier_idx": 0, "tier_label": "360p/12fps/crf35",
         "failure_mode": "oom", "source_size_gb": 1.5, "created_at": now_iso},
        {"id": str(uuid.uuid4()), "video_id": sentinel, "user_id": "u1",
         "event_type": "final_success", "tier_idx": 0, "tier_label": "360p/12fps/crf35",
         "source_size_gb": 1.5, "created_at": now_iso},
    ]
    _seed_events(events)
    try:
        r = requests.get(
            f"{BASE_URL}/api/admin/processing-events/recent?event_type=tier_failed&limit=20",
            headers=headers, timeout=15,
        )
        assert r.status_code == 200
        out = r.json()
        # Every returned event should match the filter
        for ev in out:
            assert ev["event_type"] == "tier_failed"
        # And our sentinel event must be in there
        sentinels = [e for e in out if e.get("video_id") == sentinel]
        assert len(sentinels) >= 1
    finally:
        _delete_sentinel(sentinel)


def test_stats_requires_admin():
    """Non-admins must be rejected (no info leakage about pipeline health)."""
    r = requests.get(f"{BASE_URL}/api/admin/processing-events/stats", timeout=15)
    # Unauthenticated → 401, or 403 if some default user grants partial access
    assert r.status_code in (401, 403)


def test_recent_requires_admin():
    r = requests.get(f"{BASE_URL}/api/admin/processing-events/recent", timeout=15)
    assert r.status_code in (401, 403)
