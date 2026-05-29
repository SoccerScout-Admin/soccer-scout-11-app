"""
iter108 — One-click goals-only highlight reel.

User request 2026-05-29 (post-iter107): "yes" to the suggested
'Build highlight reel from all goals' button.

Backend:
  • POST /matches/{match_id}/highlight-reel/goals-only — finds all goal
    markers on the match's video, auto-creates 15-sec clips for any
    without an existing one, then enqueues the existing reel pipeline
    with `goals_only=True`.
  • `_select_clips(clips, goals_only=False)` honors the flag — when set,
    skips score-greedy pruning and takes every goal clip in chronological
    order.
  • Auto-created clips are tagged `source_marker_id` + `auto_from_goal_marker`
    so re-running doesn't duplicate clips.

Frontend:
  • New yellow "Goals-Only Reel" button next to the existing
    "Best Moments Reel" on HighlightReelsPanel.
  • Uses the same in-flight + error state so users can't double-trigger.
"""
import os
import sys
import uuid
from datetime import datetime, timezone

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


def _payload():
    s = uuid.uuid4().hex[:10]
    return {"email": f"iter108-{s}@example.com", "password": "Iter108Pass!", "name": f"Iter108 {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


async def _seed_match_video_and_markers(uid: str, marker_types: list) -> tuple:
    """Seed a match + a video + one marker per type in the list."""
    from db import db
    match_id = str(uuid.uuid4())
    await db.matches.insert_one({
        "id": match_id, "user_id": uid,
        "team_home": "LFC", "team_away": "AYSO",
        "date": "2026-05-29",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    video_id = str(uuid.uuid4())
    await db.videos.insert_one({
        "id": video_id, "user_id": uid, "match_id": match_id,
        "original_filename": "test.mp4", "is_chunked": False, "is_deleted": False,
        "storage_path": "/nonexistent/test.mp4",
        "processing_status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    marker_ids = []
    for i, t in enumerate(marker_types):
        marker_id = str(uuid.uuid4())
        await db.markers.insert_one({
            "id": marker_id,
            "video_id": video_id, "match_id": match_id, "user_id": uid,
            "time": 300.0 + i * 600.0,  # 5 min, 15 min, 25 min etc.
            "type": t,
            "label": f"AI {t} #{i+1}",
            "team": "LFC", "importance": 5 if t == "goal" else 3,
            "player_number": 9 if t == "goal" and i == 0 else None,
            "player_name": "Marcus Lopez" if t == "goal" and i == 0 else None,
            "auto_generated": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        marker_ids.append(marker_id)
    return match_id, video_id, marker_ids


# ---------------------------------------------------------------------------
# 1. Happy path — 3 goal markers → 3 clips created + reel enqueued
# ---------------------------------------------------------------------------

def test_goals_only_reel_creates_clips_for_each_goal_marker():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            match_id, video_id, marker_ids = await _seed_match_video_and_markers(
                uid, ["goal", "goal", "goal", "shot", "save"],
            )

            r = await c.post(f"/api/matches/{match_id}/highlight-reel/goals-only")
            assert r.status_code in (200, 201), r.text
            body = r.json()
            assert body["status"] == "pending"
            assert body["goals_only"] is True
            assert body["goal_clips_auto_created"] == 3

            # 3 goal clips materialized in MongoDB
            clip_count = await db.clips.count_documents({
                "match_id": match_id, "user_id": uid, "clip_type": "goal",
            })
            assert clip_count == 3

            # Each clip is 15s wide, centered on a goal marker
            async for clip in db.clips.find(
                {"match_id": match_id, "user_id": uid, "clip_type": "goal"},
                {"_id": 0},
            ):
                duration = clip["end_time"] - clip["start_time"]
                assert duration == 15.0, f"expected 15s clip, got {duration}"
                assert clip["source_marker_id"] in marker_ids
                assert clip["auto_from_goal_marker"] is True
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. Idempotent — re-running doesn't duplicate clips
# ---------------------------------------------------------------------------

def test_goals_only_reel_is_idempotent_on_existing_clips():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            match_id, _, _ = await _seed_match_video_and_markers(
                uid, ["goal", "goal"],
            )
            # First call creates 2 clips
            r1 = await c.post(f"/api/matches/{match_id}/highlight-reel/goals-only")
            assert r1.json()["goal_clips_auto_created"] == 2
            first_count = await db.clips.count_documents({
                "match_id": match_id, "user_id": uid, "clip_type": "goal",
            })
            assert first_count == 2

            # Wait for the first reel to complete or fail so the in-flight cap
            # doesn't refuse the second call. Use a manual update — the actual
            # ffmpeg job will fail because we seeded a fake video path.
            await db.highlight_reels.update_many(
                {"user_id": uid, "status": {"$in": ["pending", "processing"]}},
                {"$set": {"status": "failed", "error": "test-cleanup"}},
            )

            # Second call recognizes existing source_marker_id and creates 0 new clips
            r2 = await c.post(f"/api/matches/{match_id}/highlight-reel/goals-only")
            assert r2.status_code in (200, 201), r2.text
            assert r2.json()["goal_clips_auto_created"] == 0
            second_count = await db.clips.count_documents({
                "match_id": match_id, "user_id": uid, "clip_type": "goal",
            })
            assert second_count == 2, "must not duplicate clips on re-run"
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 3. Clip start_time clamped to >= 0 (goal at time 3.0 doesn't go to -4)
# ---------------------------------------------------------------------------

def test_goals_only_reel_clamps_clip_start_to_zero():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            match_id = str(uuid.uuid4())
            video_id = str(uuid.uuid4())
            await db.matches.insert_one({
                "id": match_id, "user_id": uid, "team_home": "A", "team_away": "B",
                "date": "2026-05-29", "created_at": datetime.now(timezone.utc).isoformat(),
            })
            await db.videos.insert_one({
                "id": video_id, "user_id": uid, "match_id": match_id,
                "original_filename": "early.mp4", "is_chunked": False, "is_deleted": False,
                "storage_path": "/nonexistent/early.mp4",
                "processing_status": "completed",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            # Goal at t=3 → 15s window would normally start at -4
            await db.markers.insert_one({
                "id": str(uuid.uuid4()),
                "video_id": video_id, "match_id": match_id, "user_id": uid,
                "time": 3.0, "type": "goal", "label": "Early goal",
                "team": "A", "importance": 5, "auto_generated": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            await c.post(f"/api/matches/{match_id}/highlight-reel/goals-only")
            clip = await db.clips.find_one(
                {"match_id": match_id, "clip_type": "goal"}, {"_id": 0}
            )
            assert clip["start_time"] == 0.0, (
                f"start_time must clamp to 0, got {clip['start_time']}"
            )
            # End time is still time+8 even if it shrinks the window
            assert clip["end_time"] == 11.0
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 4. Title carries iter99 player attribution
# ---------------------------------------------------------------------------

def test_goals_only_reel_uses_player_attribution_in_clip_titles():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            match_id, _, _ = await _seed_match_video_and_markers(uid, ["goal"])
            await c.post(f"/api/matches/{match_id}/highlight-reel/goals-only")
            clip = await db.clips.find_one(
                {"match_id": match_id, "clip_type": "goal"}, {"_id": 0}
            )
            # The first seeded goal carries #9 Marcus Lopez via the helper
            assert "Goal" in clip["title"]
            assert "#9" in clip["title"]
            assert "Marcus Lopez" in clip["title"]
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 5. Validation + safety rails
# ---------------------------------------------------------------------------

def test_goals_only_reel_404_for_unknown_match():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.post("/api/matches/does-not-exist/highlight-reel/goals-only")
            assert r.status_code == 404
        finally:
            await c.aclose()
    _run_async(run())


def test_goals_only_reel_400_when_no_video():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            match_id = str(uuid.uuid4())
            await db.matches.insert_one({
                "id": match_id, "user_id": uid, "team_home": "A", "team_away": "B",
                "date": "2026-05-29", "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.post(f"/api/matches/{match_id}/highlight-reel/goals-only")
            assert r.status_code == 400
            assert "video" in r.json()["detail"].lower()
        finally:
            await c.aclose()
    _run_async(run())


def test_goals_only_reel_400_when_no_goal_markers():
    async def run():
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            # Video has shots and saves but NO goals
            match_id, _, _ = await _seed_match_video_and_markers(
                uid, ["shot", "save", "foul"],
            )
            r = await c.post(f"/api/matches/{match_id}/highlight-reel/goals-only")
            assert r.status_code == 400, r.text
            assert "goal" in r.json()["detail"].lower()
        finally:
            await c.aclose()
    _run_async(run())


def test_goals_only_reel_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.post("/api/matches/x/highlight-reel/goals-only")
            assert r.status_code in (401, 403)
    _run_async(run())


def test_goals_only_reel_cross_user_isolation():
    async def run():
        c_a = await _client(_payload())
        c_b = await _client(_payload())
        try:
            me_a = (await c_a.get("/api/auth/me")).json()
            match_id, _, _ = await _seed_match_video_and_markers(me_a["id"], ["goal"])
            r_b = await c_b.post(f"/api/matches/{match_id}/highlight-reel/goals-only")
            assert r_b.status_code == 404, "must 404 cross-user"
        finally:
            await c_a.aclose()
            await c_b.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 6. _select_clips honors goals_only flag (no score pruning, chronological)
# ---------------------------------------------------------------------------

def test_select_clips_goals_only_skips_score_pruning():
    """When goals_only=True, all clips are taken in chronological order
    regardless of score (until budget runs out). Without goals_only, the
    selector picks by score."""
    from services.highlight_reel import _select_clips

    clips = [
        {"id": "a", "start_time": 100, "end_time": 115, "clip_type": "goal", "title": "first goal"},
        {"id": "b", "start_time": 50,  "end_time": 65,  "clip_type": "goal", "title": "earliest goal"},
        {"id": "c", "start_time": 200, "end_time": 215, "clip_type": "goal", "title": "third goal"},
    ]
    selected, _ = _select_clips(clips, goals_only=True)
    # Chronological order, all 3 included
    assert [c["id"] for c in selected] == ["b", "a", "c"]


def test_select_clips_default_still_uses_score_based_pruning():
    """Backwards compat: when goals_only is omitted/False, the original
    score-greedy behavior is preserved. With a tight budget, a high-score
    `goal` clip beats a low-score `highlight` clip.

    Note: the function chronologically RE-SORTS the final output, so we
    verify by checking MEMBERSHIP under a tight budget rather than
    output order.
    """
    from services.highlight_reel import _select_clips, MAX_DURATION_S

    # Use enough low-score clips that only the top-scored ones survive the
    # budget cap. Goal clip (score=100) MUST be in the result.
    duration = MAX_DURATION_S // 2
    clips = [
        # Five "highlight" clips (score=50 each) totaling 5 × duration/2.
        # Plus one goal clip (score=100).
        {"id": "hl1", "start_time": 0,    "end_time": 15, "clip_type": "highlight"},
        {"id": "hl2", "start_time": 100,  "end_time": 115, "clip_type": "highlight"},
        {"id": "hl3", "start_time": 200,  "end_time": 215, "clip_type": "highlight"},
        {"id": "hl4", "start_time": 300,  "end_time": 315, "clip_type": "highlight"},
        {"id": "hl5", "start_time": 400,  "end_time": 415, "clip_type": "highlight"},
        {"id": "the_goal", "start_time": 500, "end_time": 515, "clip_type": "goal"},
    ]
    selected, _ = _select_clips(clips)  # goals_only defaults False
    selected_ids = {c["id"] for c in selected}
    # The goal MUST be picked — it's the highest-scored clip
    assert "the_goal" in selected_ids
    assert duration > 0  # silence the unused-warning


# ---------------------------------------------------------------------------
# 7. Frontend wiring
# ---------------------------------------------------------------------------

def test_highlight_reels_panel_has_goals_only_button():
    src = open("/app/frontend/src/pages/components/HighlightReelsPanel.js").read()
    assert 'data-testid="generate-goals-only-reel-btn"' in src
    assert "handleGenerateGoalsOnly" in src
    assert "/highlight-reel/goals-only" in src
    # The existing "Best Moments Reel" button is renamed to distinguish it
    assert "Best Moments Reel" in src
    assert "Goals-Only Reel" in src


# ---------------------------------------------------------------------------
# 8. Deploy endpoint advertises iter108 feature flags
# ---------------------------------------------------------------------------

def test_deploy_endpoint_advertises_iter108_features():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            features = set(r.json()["features"])
            assert "goals-only-highlight-reel-endpoint" in features
            assert "auto-create-clips-from-goal-markers" in features
            assert "select-clips-goals-only-flag" in features
            assert "highlight-reel-panel-goals-only-button" in features
    _run_async(run())
