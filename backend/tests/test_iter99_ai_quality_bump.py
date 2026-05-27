"""
iter99 — AI quality bump for goal/player recognition.

User feedback 2026-05-27: "I'm not seeing very robust tagging in the video
I recently uploaded. none of the three goals are captured, and there is no
player recognition."

Root causes identified:
  • Coverage gap: 12 × 60s segments = 12 min of a 107-min match. A 30s goal
    sequence (build-up + score + celebration) could fall entirely in the
    50-min of un-sampled footage. 25% chance of missing each goal.
  • Resolution gap: 480p means jersey numbers are ~15 px tall. Gemini
    Vision can NOT read them reliably at that size.
  • Prompt gap: timeline_markers prompt said "be thorough" but didn't tell
    Gemini WHAT cues to look for or to include player attribution.

Five fixes shipped:
  1. Segments 12×60s → 18×45s (denser sampling, 13.5min coverage)
  2. Scale 480p → 720p (jersey numbers go from ~15px → ~22px tall)
  3. Frame rate 12fps → 15fps (better motion continuity for goal events)
  4. Marker prompt: explicit goal-detection cues (net bulge, celebrations,
     kickoff-from-center restart, scoreboard change) + player_number +
     player_name fields
  5. player_performance prompt: "identify by jersey number FIRST" directive
"""
import os
import sys
import uuid

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Denser sampling (more segments, shorter each)
# ---------------------------------------------------------------------------

def test_segments_count_and_duration_bumped():
    """18 × 45s instead of 12 × 60s — denser coverage of the match."""
    src = open("/app/backend/services/processing.py").read()
    # Find the prepare_video_segments_720p body
    fn_start = src.find("async def prepare_video_segments_720p")
    body = src[fn_start:fn_start + 4000]
    assert "segment_duration = 45" in body
    assert "num_segments = 18" in body
    # Old values must be gone
    assert "segment_duration = 60" not in body
    assert "num_segments = 12" not in body


# ---------------------------------------------------------------------------
# 2. 720p resolution (actually 720p now, not 480p as the function name lied)
# ---------------------------------------------------------------------------

def test_segments_scale_bumped_to_720p():
    src = open("/app/backend/services/processing.py").read()
    fn_start = src.find("async def prepare_video_segments_720p")
    body = src[fn_start:fn_start + 8000]
    assert '"scale=-2:720"' in body, "segment scale must be 720p"
    assert '"scale=-2:480"' not in body, "old 480p scale must be removed"


def test_segments_fps_bumped_to_15():
    src = open("/app/backend/services/processing.py").read()
    fn_start = src.find("async def prepare_video_segments_720p")
    body = src[fn_start:fn_start + 8000]
    # Look for the -r argument inside the seg_cmd
    assert '"-r", "15"' in body
    assert '"-r", "12"' not in body


def test_segments_keep_iter97_memory_guards():
    """When bumping resolution/fps, the iter97 memory guards must stay so
    we don't reintroduce the OOM crash that iter97 fixed."""
    src = open("/app/backend/services/processing.py").read()
    fn_start = src.find("async def prepare_video_segments_720p")
    body = src[fn_start:fn_start + 8000]
    assert '"-threads", "1"' in body
    assert '"-max_muxing_queue_size"' in body
    assert '"-bufsize"' in body
    assert "+discardcorrupt" in body


# ---------------------------------------------------------------------------
# 3. Stronger marker prompt — goal-detection cues + player attribution fields
# ---------------------------------------------------------------------------

def test_marker_prompt_has_goal_detection_cues():
    src = open("/app/backend/services/processing.py").read()
    # Build the prompt dict with realistic match/roster
    from services.processing import build_analysis_prompts
    prompts = build_analysis_prompts(
        match={"team_home": "Test FC", "team_away": "Demo United"},
        roster_context="",
        segment_preamble="",
    )
    p = prompts["timeline_markers"]
    # Must mention explicit goal cues
    cues = [
        "goal line",
        "celebrat",
        "kickoff",
        "center circle",
        "scoreboard",
    ]
    missing = [c for c in cues if c.lower() not in p.lower()]
    assert not missing, f"marker prompt missing goal-detection cues: {missing}"
    # Must call out that goals are critical
    assert "do NOT miss" in p or "do not miss" in p.lower() or "critical" in p.lower()


def test_marker_prompt_requires_player_attribution_fields():
    from services.processing import build_analysis_prompts
    prompts = build_analysis_prompts(
        match={"team_home": "Test FC", "team_away": "Demo United"},
        roster_context="",
        segment_preamble="",
    )
    p = prompts["timeline_markers"]
    assert "player_number" in p
    assert "player_name" in p
    # The output spec must include both fields explicitly
    assert '"player_number"' in p
    assert '"player_name"' in p


def test_marker_prompt_asks_for_20_to_35_events():
    """Bumped from 15-30 to 20-35 — denser sampling should produce more events."""
    from services.processing import build_analysis_prompts
    prompts = build_analysis_prompts(
        match={"team_home": "Test FC", "team_away": "Demo United"},
        roster_context="",
        segment_preamble="",
    )
    p = prompts["timeline_markers"]
    assert "20-35" in p or "20 to 35" in p or "20–35" in p


# ---------------------------------------------------------------------------
# 4. Player performance prompt — jersey-number-first directive
# ---------------------------------------------------------------------------

def test_player_performance_prompt_emphasizes_jersey_numbers():
    from services.processing import build_analysis_prompts
    prompts = build_analysis_prompts(
        match={"team_home": "Test FC", "team_away": "Demo United"},
        roster_context="\n\n**Known Players on the Roster:**\n#7 Marcus Lopez",
        segment_preamble="",
    )
    p = prompts["player_performance"]
    # Must instruct to lead with jersey number
    assert "jersey number" in p.lower()
    assert "ALWAYS" in p or "always" in p.lower()
    # Must reference the roster context
    assert "Marcus Lopez" in p or "roster" in p.lower()


# ---------------------------------------------------------------------------
# 5. Marker parser persists player_number + player_name
# ---------------------------------------------------------------------------

def test_marker_parser_persists_player_attribution():
    async def run():
        from db import db
        from services.processing import parse_and_store_markers

        video_id = str(uuid.uuid4())
        match_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        # Simulate Gemini response with new fields
        gemini_response = (
            '[{"time": 1234.5, "type": "goal", "label": "Header from corner",'
            ' "team": "Test FC", "importance": 5, "player_number": 9,'
            ' "player_name": "Striker Jones"},'
            ' {"time": 2000, "type": "shot", "label": "Long range",'
            ' "team": "Test FC", "importance": 3, "player_number": "11",'
            ' "player_name": "Winger Smith"},'
            ' {"time": 3000, "type": "chance", "label": "Counter",'
            ' "team": "Demo United", "importance": 2,'
            ' "player_number": null, "player_name": null}]'
        )
        count = await parse_and_store_markers(
            gemini_response, video_id, match_id, user_id,
        )
        assert count == 3

        goal = await db.markers.find_one(
            {"video_id": video_id, "type": "goal"}, {"_id": 0}
        )
        assert goal is not None
        assert goal["player_number"] == 9
        assert goal["player_name"] == "Striker Jones"

        # String "11" should be coerced to int
        shot = await db.markers.find_one(
            {"video_id": video_id, "type": "shot"}, {"_id": 0}
        )
        assert shot["player_number"] == 11
        assert shot["player_name"] == "Winger Smith"

        # null fields should land as Python None
        chance = await db.markers.find_one(
            {"video_id": video_id, "type": "chance"}, {"_id": 0}
        )
        assert chance["player_number"] is None
        assert chance["player_name"] is None

        # Clean up
        await db.markers.delete_many({"video_id": video_id})
    _run_async(run())


def test_marker_parser_tolerates_missing_player_fields():
    """Backwards compat: legacy responses without player_number/name must
    still parse — we just store None."""
    async def run():
        from db import db
        from services.processing import parse_and_store_markers

        video_id = str(uuid.uuid4())
        match_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        legacy = (
            '[{"time": 100, "type": "save", "label": "Diving stop",'
            ' "team": "Test FC", "importance": 4}]'
        )
        count = await parse_and_store_markers(legacy, video_id, match_id, user_id)
        assert count == 1
        doc = await db.markers.find_one({"video_id": video_id}, {"_id": 0})
        assert doc["player_number"] is None
        assert doc["player_name"] is None

        await db.markers.delete_many({"video_id": video_id})
    _run_async(run())


def test_marker_parser_handles_bad_player_number():
    async def run():
        from db import db
        from services.processing import parse_and_store_markers

        video_id = str(uuid.uuid4())
        match_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())

        garbage = (
            '[{"time": 100, "type": "shot", "label": "x", "team": "x",'
            ' "importance": 3, "player_number": "garbage",'
            ' "player_name": "  Trimmed Name  "}]'
        )
        count = await parse_and_store_markers(garbage, video_id, match_id, user_id)
        assert count == 1
        doc = await db.markers.find_one({"video_id": video_id}, {"_id": 0})
        assert doc["player_number"] is None  # garbage coerces to None
        assert doc["player_name"] == "Trimmed Name"  # stripped
        await db.markers.delete_many({"video_id": video_id})
    _run_async(run())


# ---------------------------------------------------------------------------
# 6. Frontend marker tooltip surfaces player attribution
# ---------------------------------------------------------------------------

def test_frontend_marker_tooltip_includes_player_attribution():
    src = open("/app/frontend/src/pages/components/VideoPlayerWithMarkers.js").read()
    assert "player_name" in src
    assert "player_number" in src
    # Building the tooltip suffix
    assert "playerTag" in src or "player_tag" in src


# ---------------------------------------------------------------------------
# 7. Deploy endpoint advertises iter99 features
# ---------------------------------------------------------------------------

def test_deploy_endpoint_advertises_iter99_features():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            features = set(r.json()["features"])
            assert "ai-segments-18x45s-denser-coverage" in features
            assert "ai-segments-720p-legible-jersey-numbers" in features
            assert "ai-prompt-explicit-goal-detection-cues" in features
            assert "ai-marker-player-number-and-name-fields" in features
            assert "ai-player-performance-jersey-first-prompt" in features
    _run_async(run())
