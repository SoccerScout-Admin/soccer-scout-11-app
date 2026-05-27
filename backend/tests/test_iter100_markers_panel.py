"""
iter100 — Rich Markers Panel UI.

Adds a scannable list view of every AI-generated timeline event next to the
video player. Each row shows type icon + label + match-time chip + jersey
avatar (iter99 attribution). Type-filter pills let coaches answer questions
like "show me all 3 goals" in one click. Click any row → seeks the video.

Backend changes: NONE (the existing `/api/markers/video/{video_id}` already
returns the iter99 attribution fields via `{"_id": 0}` projection).

Frontend changes:
  - New `pages/components/MarkersPanel.js`
  - Wired into VideoAnalysis right sidebar above ClipsSidebar
"""
import os
import sys

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


# ---------------------------------------------------------------------------
# Component existence + structure
# ---------------------------------------------------------------------------

def test_markers_panel_component_exists():
    p = "/app/frontend/src/pages/components/MarkersPanel.js"
    assert os.path.exists(p), f"{p} must exist"
    src = open(p).read()
    # Critical testids the testing agent + future tests rely on
    assert 'data-testid="markers-panel"' in src
    assert 'data-testid="markers-panel-total"' in src
    assert 'data-testid="filter-pill-all"' in src
    assert 'data-testid="filter-pill-' in src  # per-type pills
    assert 'data-testid={`marker-row-' in src  # row testid


def test_markers_panel_renders_all_event_types():
    """Every type Gemini can emit must have an icon + color + label so we
    don't fall back to a gray 'unknown' for goals or shots."""
    src = open("/app/frontend/src/pages/components/MarkersPanel.js").read()
    for t in (
        "goal", "shot", "save", "chance",
        "foul", "card", "substitution", "tactical",
    ):
        assert f"{t}:" in src, f"TYPE_META missing key '{t}'"


def test_markers_panel_uses_iter99_attribution():
    src = open("/app/frontend/src/pages/components/MarkersPanel.js").read()
    assert "marker.player_number" in src or "player_number" in src
    assert "marker.player_name" in src or "player_name" in src
    # The jersey avatar circle
    assert 'data-testid={`marker-row-jersey-' in src


def test_markers_panel_click_seeks_video():
    src = open("/app/frontend/src/pages/components/MarkersPanel.js").read()
    # onClick must invoke onSeek with the marker time
    assert "onSeek(marker.time)" in src


def test_markers_panel_filter_pills_track_counts():
    src = open("/app/frontend/src/pages/components/MarkersPanel.js").read()
    # countsByType groups markers per type for the pill counters
    assert "countsByType" in src
    # Pill must show count per type (e.g., "Goals · 3")
    assert "countsByType[t]" in src


def test_markers_panel_empty_state_returns_null():
    """When the video has no markers, the panel should render NOTHING
    (not an empty card cluttering the sidebar)."""
    src = open("/app/frontend/src/pages/components/MarkersPanel.js").read()
    assert "if (!sorted.length) return null" in src


# ---------------------------------------------------------------------------
# Wiring into VideoAnalysis
# ---------------------------------------------------------------------------

def test_video_analysis_imports_markers_panel():
    src = open("/app/frontend/src/pages/VideoAnalysis.js").read()
    assert "import MarkersPanel" in src
    # Placed in the right sidebar, ABOVE ClipsSidebar (highest signal)
    assert "<MarkersPanel" in src
    panel_idx = src.find("<MarkersPanel")
    clips_idx = src.find("<ClipsSidebar")
    assert panel_idx < clips_idx, (
        "MarkersPanel must render BEFORE ClipsSidebar in the right column "
        "(higher signal for game review)"
    )


def test_video_analysis_passes_seek_to_markers_panel():
    src = open("/app/frontend/src/pages/VideoAnalysis.js").read()
    # The seek handler must be wired through so clicks scrub the video
    assert "<MarkersPanel markers={markers} onSeek={seekTo} />" in src


# ---------------------------------------------------------------------------
# Backend endpoint still returns iter99 attribution (regression guard)
# ---------------------------------------------------------------------------

def test_markers_endpoint_projects_player_attribution_fields():
    """The `/api/markers/video/{id}` endpoint must use `{_id: 0}` so iter99's
    `player_number` and `player_name` reach the frontend. If a future agent
    adds a tighter projection, this test catches it."""
    src = open("/app/backend/routes/analysis.py").read()
    fn_start = src.find("async def get_markers")
    assert fn_start >= 0
    body = src[fn_start:fn_start + 600]
    assert '{"_id": 0}' in body, (
        "get_markers must use {'_id': 0} so iter99 attribution fields "
        "(player_number, player_name) reach the frontend"
    )


# ---------------------------------------------------------------------------
# Deploy endpoint advertises iter100 feature flags
# ---------------------------------------------------------------------------

def test_deploy_endpoint_advertises_iter100_features():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            body = r.json()
            features = set(body["features"])
            assert "markers-panel-scannable-list" in features
            assert "markers-panel-type-filter-pills" in features
            assert "markers-panel-jersey-avatars" in features
            assert "markers-panel-click-to-seek" in features
    _run_async(run())
