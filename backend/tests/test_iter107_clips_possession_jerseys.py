"""
iter107 — Clip-from-marker + possession stats + jersey colors.

User request 2026-05-28 (post-iter106 deploy):
  • Add "One-click create clip from marker" on the MarkersPanel
  • Add pass strings + possession as a Veo-style highlighted stat
  • Add jersey colors to match creation so the AI can disambiguate teams

Three coordinated changes:

1. **Match model** gains `team_home_jersey_color` + `team_away_jersey_color`
   optional string fields. `build_analysis_prompts` injects a kit-color
   preamble into every prompt when set.

2. **New `possession_stats` analysis type** — Gemini returns a structured
   JSON object (possession%, longest pass string, total passes, summary).
   Wired into `run_auto_processing` so it generates alongside the existing
   4 analyses. Manual `_run_generate_analysis` now uses the shared
   `build_analysis_prompts` helper too (fixes a bug where manual
   regenerates used simplified inline prompts that lacked iter99+iter107
   improvements).

3. **Clip-from-marker** — MarkersPanel scissor button → POST /api/clips
   with start = marker.time - 7, end = marker.time + 8, title built from
   the marker label + player attribution.
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
    return {"email": f"iter107-{s}@example.com", "password": "Iter107Pass!", "name": f"Iter107 {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


# ---------------------------------------------------------------------------
# 1. Match model accepts jersey colors
# ---------------------------------------------------------------------------

def test_create_match_accepts_jersey_colors():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            r = await c.post("/api/matches", json={
                "team_home": "LFC", "team_away": "AYSO",
                "date": "2026-05-28",
                "team_home_jersey_color": "red",
                "team_away_jersey_color": "white",
            })
            assert r.status_code in (200, 201), r.text
            match = r.json()
            assert match["team_home_jersey_color"] == "red"
            assert match["team_away_jersey_color"] == "white"
            # Persisted to MongoDB
            stored = await db.matches.find_one({"id": match["id"]}, {"_id": 0})
            assert stored["team_home_jersey_color"] == "red"
            assert stored["team_away_jersey_color"] == "white"
            # User isolation
            assert stored["user_id"] == me["id"]
        finally:
            await c.aclose()
    _run_async(run())


def test_create_match_works_without_jersey_colors():
    """Jersey colors are optional — existing matches must keep working."""
    async def run():
        c = await _client(_payload())
        try:
            r = await c.post("/api/matches", json={
                "team_home": "Team A", "team_away": "Team B", "date": "2026-05-28",
            })
            assert r.status_code in (200, 201), r.text
            match = r.json()
            # Optional fields can be None
            assert match.get("team_home_jersey_color") is None
            assert match.get("team_away_jersey_color") is None
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. Prompts inject kit-color preamble when set
# ---------------------------------------------------------------------------

def test_prompts_inject_jersey_colors_when_both_set():
    from services.processing import build_analysis_prompts
    prompts = build_analysis_prompts(
        match={
            "team_home": "LFC", "team_away": "AYSO",
            "team_home_jersey_color": "red",
            "team_away_jersey_color": "white",
        },
        roster_context="",
        segment_preamble="",
    )
    for kind in ("tactical", "player_performance", "highlights", "timeline_markers", "possession_stats"):
        p = prompts[kind]
        assert "TEAM KIT COLORS" in p, f"{kind} prompt missing kit preamble"
        assert "red" in p.lower(), f"{kind} prompt missing home kit color"
        assert "white" in p.lower(), f"{kind} prompt missing away kit color"


def test_prompts_skip_kit_preamble_when_not_set():
    from services.processing import build_analysis_prompts
    prompts = build_analysis_prompts(
        match={"team_home": "LFC", "team_away": "AYSO"},
        roster_context="",
        segment_preamble="",
    )
    for kind in ("tactical", "timeline_markers", "possession_stats"):
        assert "TEAM KIT COLORS" not in prompts[kind], (
            f"{kind} must omit kit preamble when colors not configured"
        )


def test_prompts_inject_kit_preamble_with_only_one_color():
    from services.processing import build_analysis_prompts
    prompts = build_analysis_prompts(
        match={
            "team_home": "LFC", "team_away": "AYSO",
            "team_home_jersey_color": "navy",
            # away omitted
        },
        roster_context="",
        segment_preamble="",
    )
    p = prompts["timeline_markers"]
    assert "TEAM KIT COLORS" in p
    assert "navy" in p.lower()


# ---------------------------------------------------------------------------
# 3. possession_stats prompt has the right structured spec
# ---------------------------------------------------------------------------

def test_possession_stats_prompt_specifies_json_schema():
    from services.processing import build_analysis_prompts
    prompts = build_analysis_prompts(
        match={"team_home": "LFC", "team_away": "AYSO"},
        roster_context="",
        segment_preamble="",
    )
    p = prompts["possession_stats"]
    # All required output fields documented
    for field in (
        "team_home_possession_pct",
        "team_away_possession_pct",
        "team_home_longest_pass_string",
        "team_away_longest_pass_string",
        "team_home_total_passes_estimate",
        "team_away_total_passes_estimate",
        "summary",
    ):
        assert field in p, f"possession_stats prompt missing field: {field}"
    # Methodology hints explain pass string + possession definition
    assert "pass string" in p.lower() or "pass-string" in p.lower()
    assert "out of bounds" in p.lower() or "out-of-play" in p.lower()
    # Must demand JSON only (no markdown noise)
    assert "JSON object" in p or "json object" in p.lower()


def test_possession_stats_is_in_auto_processing_pipeline():
    """run_auto_processing must include possession_stats so it generates
    automatically alongside the other 4 analyses."""
    src = open("/app/backend/services/processing.py").read()
    # The all_types list must include possession_stats
    assert '"possession_stats"' in src
    assert '"tactical", "player_performance", "highlights", "timeline_markers", "possession_stats"' in src


def test_server_remaining_types_includes_possession_stats():
    src = open("/app/backend/server.py").read()
    # The "remaining types" computation in the reprocess endpoint
    assert '"possession_stats"' in src


# ---------------------------------------------------------------------------
# 4. Manual /analysis/generate uses shared prompt builder
# ---------------------------------------------------------------------------

def test_run_generate_analysis_uses_shared_prompt_builder():
    """The inline prompt dict in `_run_generate_analysis` was duplicating
    (and simplifying) what `build_analysis_prompts` already does. iter107
    routes through the shared builder so manual regenerates get the same
    iter99+iter107 quality."""
    src = open("/app/backend/server.py").read()
    # Find the _run_generate_analysis function
    fn_start = src.find("async def _run_generate_analysis")
    assert fn_start >= 0
    body = src[fn_start:fn_start + 3000]
    assert "build_analysis_prompts" in body, (
        "_run_generate_analysis must import + use the shared prompt builder"
    )
    # And NOT the old inline simplified prompts
    assert '"Analyze this soccer match video between {match' not in body


# ---------------------------------------------------------------------------
# 5. Frontend: clip-from-marker button + handler
# ---------------------------------------------------------------------------

def test_markers_panel_has_clip_button():
    src = open("/app/frontend/src/pages/components/MarkersPanel.js").read()
    assert 'data-testid={`marker-row-clip-' in src
    assert "Scissors" in src, "must import the Scissors icon"
    assert "handleCreateClipFromMarker" in src


def test_clip_from_marker_centers_15_seconds_on_timestamp():
    """The handler must build a 15-sec window (7 before + 8 after) clamped
    to >= 0 so marker at time=3 doesn't produce a clip starting at -4."""
    src = open("/app/frontend/src/pages/components/MarkersPanel.js").read()
    assert "marker.time - 7" in src
    assert "marker.time + 8" in src
    assert "Math.max(0," in src


def test_clip_from_marker_uses_player_attribution_in_title():
    src = open("/app/frontend/src/pages/components/MarkersPanel.js").read()
    assert "marker.player_number" in src and "marker.player_name" in src
    # Builds an enriched title with #N + name
    assert "#${marker.player_number}" in src


def test_video_analysis_wires_video_id_and_clip_callback_to_panel():
    src = open("/app/frontend/src/pages/VideoAnalysis.js").read()
    assert "videoId={videoId}" in src
    assert "onClipCreated=" in src


# ---------------------------------------------------------------------------
# 6. Frontend: MatchStatsCard + jersey color form
# ---------------------------------------------------------------------------

def test_match_stats_card_exists_and_renders_possession():
    p = "/app/frontend/src/pages/components/MatchStatsCard.js"
    assert os.path.exists(p), f"{p} missing"
    src = open(p).read()
    assert 'data-testid="match-stats-card"' in src
    assert 'data-testid="possession-bar-home"' in src
    assert 'data-testid="possession-bar-away"' in src
    # pass-string testids are passed via prop to PassStringCard — verify
    # both the prop call sites and the destination data-testid binding
    assert 'testid="pass-string-home"' in src
    assert 'testid="pass-string-away"' in src
    assert "data-testid={testid}" in src
    # Reads from the analyses array and finds possession_stats type
    assert "analysis_type === 'possession_stats'" in src
    # Parses Gemini JSON response (handles markdown fence wrapping)
    assert "JSON.parse" in src


def test_match_stats_card_handles_missing_data():
    """If no possession_stats analysis exists yet, the card must return null
    (not render an empty stub)."""
    src = open("/app/frontend/src/pages/components/MatchStatsCard.js").read()
    assert "return null" in src


def test_match_stats_card_uses_jersey_colors_for_visualization():
    """When jersey colors are set, the possession bar must color-code each
    team's segment with their actual kit color."""
    src = open("/app/frontend/src/pages/components/MatchStatsCard.js").read()
    assert "team_home_jersey_color" in src
    assert "team_away_jersey_color" in src
    # Common color name → hex mapping
    assert "red" in src and "navy" in src and "white" in src


def test_video_analysis_mounts_match_stats_card():
    src = open("/app/frontend/src/pages/VideoAnalysis.js").read()
    assert "import MatchStatsCard" in src
    assert "<MatchStatsCard" in src


def test_create_match_modal_has_jersey_color_inputs():
    src = open("/app/frontend/src/pages/components/CreateMatchModal.js").read()
    assert 'data-testid="home-jersey-color-input"' in src
    assert 'data-testid="away-jersey-color-input"' in src
    assert "team_home_jersey_color" in src
    assert "team_away_jersey_color" in src


# ---------------------------------------------------------------------------
# 7. Deploy endpoint advertises iter107 features
# ---------------------------------------------------------------------------

def test_deploy_endpoint_advertises_iter107_features():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            features = set(r.json()["features"])
            assert "clip-from-marker-one-click" in features
            assert "possession-stats-veo-style-card" in features
            assert "jersey-color-team-disambiguation" in features
            assert "shared-prompt-builder-on-manual-regenerate" in features
    _run_async(run())
