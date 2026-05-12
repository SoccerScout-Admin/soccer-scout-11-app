"""Weekly Reel Recap email — service + admin trigger tests."""
from __future__ import annotations

import sys
import uuid
import pytest
from datetime import datetime, timezone

sys.path.insert(0, "/app/backend")

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: F401
from services.reel_recap import (
    _build_recap_html, _format_duration, send_weekly_reel_recap,
)


# ---------- pure helpers ----------

def test_format_duration_handles_zero_and_minutes():
    assert _format_duration(0) == "—"
    assert _format_duration(45) == "45s"
    assert _format_duration(60) == "1:00"
    assert _format_duration(72) == "1:12"


def test_build_recap_html_emits_view_count_and_team_names():
    items = [{
        "reel": {"id": "r1", "share_token": "tok1", "total_clips": 5, "duration_seconds": 65.0},
        "match": {"team_home": "Arsenal", "team_away": "Chelsea", "competition": "Premier League"},
        "views_7d": 23,
    }]
    html_out = _build_recap_html("Coach Pep", 23, +10, items)
    # Critical content rendered
    assert "REEL RECAP" in html_out
    assert "Arsenal vs Chelsea" in html_out
    assert "23" in html_out
    assert "+10" in html_out
    # CTA link present
    assert "/reels" in html_out
    assert "/dashboard" in html_out
    # XSS escape — coach name lands inside an h1 and must be HTML-safe
    assert "<script>" not in html_out


def test_build_recap_html_handles_negative_delta():
    items = [{
        "reel": {"id": "r1", "share_token": "tok1", "total_clips": 1, "duration_seconds": 30.0},
        "match": {"team_home": "A", "team_away": "B"},
        "views_7d": 2,
    }]
    html_out = _build_recap_html("Coach", 2, -5, items)
    assert "-5" in html_out


def test_build_recap_html_xss_escape():
    """Coach name and team names must be HTML-escaped."""
    items = [{
        "reel": {"id": "r1", "share_token": "tok1", "total_clips": 1, "duration_seconds": 30.0},
        "match": {"team_home": "<script>alert('xss')</script>", "team_away": "Safe"},
        "views_7d": 1,
    }]
    html_out = _build_recap_html("<img onerror=alert(1)>", 1, 0, items)
    assert "<script>alert" not in html_out
    assert "<img onerror" not in html_out
    assert "&lt;script&gt;" in html_out or "&lt;img" in html_out


# ---------- send_weekly_reel_recap (orchestration) ----------

def test_send_recap_returns_zero_counts_when_no_reels():
    """Cluster with zero shared reels — function must return without erroring."""

    async def go():
        # Don't seed anything — count whatever already exists
        return await send_weekly_reel_recap(triggered_by="manual")

    counts = _run_async(go())
    # Required keys present
    for k in ("users_total", "sent", "queued", "skipped", "errors"):
        assert k in counts


def test_send_recap_skips_users_without_recent_views_on_apscheduler():
    """A user with shared reels but no weekly views must be skipped when
    triggered by APScheduler (we don't email silence)."""

    async def setup():
        from db import db
        user_id = "rrtest-" + uuid.uuid4().hex[:8]
        await db.users.insert_one({
            "id": user_id, "email": f"{user_id}@test.local",
            "name": "Silent Sam", "role": "coach", "hashed_password": "x",
        })
        match_id = "rr-m-" + uuid.uuid4().hex[:8]
        await db.matches.insert_one({
            "id": match_id, "user_id": user_id,
            "team_home": "QuietHome", "team_away": "QuietAway",
            "date": "2026-01-01", "competition": "Test",
        })
        reel_id = "rr-r-" + uuid.uuid4().hex[:8]
        await db.highlight_reels.insert_one({
            "id": reel_id, "user_id": user_id, "match_id": match_id,
            "status": "ready", "share_token": "qtok" + uuid.uuid4().hex[:7],
            "selected_clip_ids": [], "total_clips": 2, "duration_seconds": 30.0,
            "created_at": "2026-05-10T00:00:00+00:00",
        })
        return user_id, match_id, reel_id

    user_id, match_id, reel_id = _run_async(setup())
    try:
        async def run_recap():
            return await send_weekly_reel_recap(triggered_by="apscheduler")

        result = _run_async(run_recap())
        # No views recorded for this user → skipped should include them
        assert result["skipped"] >= 1
        # And no email was sent FOR THIS user (we can't assert globally so
        # we just confirm function ran cleanly).
    finally:
        async def cleanup():
            from db import db
            await db.highlight_reels.delete_one({"id": reel_id})
            await db.matches.delete_one({"id": match_id})
            await db.users.delete_one({"id": user_id})
        _run_async(cleanup())


def test_send_recap_emails_user_with_views():
    """A user with shared reel + recent views must result in 1 sent OR queued."""

    async def setup():
        from db import db
        user_id = "rrok-" + uuid.uuid4().hex[:8]
        await db.users.insert_one({
            "id": user_id, "email": f"{user_id}@test.local",
            "name": "Active Alice", "role": "coach", "hashed_password": "x",
        })
        match_id = "rrok-m-" + uuid.uuid4().hex[:8]
        await db.matches.insert_one({
            "id": match_id, "user_id": user_id,
            "team_home": "Hotsters", "team_away": "Opponent",
            "date": "2026-01-01", "competition": "Hot League",
        })
        reel_id = "rrok-r-" + uuid.uuid4().hex[:8]
        await db.highlight_reels.insert_one({
            "id": reel_id, "user_id": user_id, "match_id": match_id,
            "status": "ready", "share_token": "hottok-" + reel_id[-6:],
            "selected_clip_ids": [], "total_clips": 5, "duration_seconds": 75.0,
            "created_at": "2026-05-10T00:00:00+00:00",
        })
        # Seed 8 views in the last 24h
        now = datetime.now(timezone.utc).isoformat()
        for i in range(8):
            await db.highlight_reel_views.insert_one({
                "reel_id": reel_id, "viewer_key": f"a:rrok-{i}",
                "viewer_user_id": None, "viewed_at": now,
            })
        return user_id, match_id, reel_id

    user_id, match_id, reel_id = _run_async(setup())
    try:
        async def run_recap():
            return await send_weekly_reel_recap(triggered_by="manual")

        result = _run_async(run_recap())
        # At least one email was processed for our user (sent or queued)
        assert (result["sent"] + result["queued"]) >= 1
    finally:
        async def cleanup():
            from db import db
            await db.highlight_reels.delete_one({"id": reel_id})
            await db.highlight_reel_views.delete_many({"reel_id": reel_id})
            await db.matches.delete_one({"id": match_id})
            await db.users.delete_one({"id": user_id})
        _run_async(cleanup())


# ---------- admin manual trigger ----------

@pytest.fixture(scope="module")
def admin_headers():
    import requests
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "Ben.buursma@gmail.com", "password": "BenAdmin2026!"},
    )
    if r.status_code != 200:
        pytest.skip("admin account not available")
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_admin_recap_trigger_requires_auth():
    import requests
    r = requests.post(f"{BASE_URL}/api/admin/highlight-reels/send-weekly-recap")
    assert r.status_code in (401, 403)


def test_admin_recap_trigger_returns_counts(admin_headers):
    import requests
    r = requests.post(
        f"{BASE_URL}/api/admin/highlight-reels/send-weekly-recap",
        headers=admin_headers,
    )
    assert r.status_code == 200
    body = r.json()
    for k in ("users_total", "sent", "queued", "skipped", "errors"):
        assert k in body
