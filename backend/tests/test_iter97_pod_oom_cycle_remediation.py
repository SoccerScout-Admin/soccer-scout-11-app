"""
iter97 — Pod-OOM-cycle remediation for sub-2GB videos.

Real production bug 2026-05-27, video 1140ed3a (1.04 GB / 1:47:48 / 1080p30):
The user followed all iter79 HandBrake compression advice (10 GB → 1 GB) and
got the upload to finish, but processing got stuck at 0% with the
"Server restarted — processing resumed automatically" banner reappearing
every few seconds. The pod was OOM-killing within seconds of ffmpeg starting
because the file landed in the iter63 <2GB tier (360p/12fps) instead of the
≥2GB tier (180p/5fps). The iter75 guard caught it eventually but only after
3 cycles (~30 min of user pain).

Three fixes shipped:
  1. Aggressive-tier threshold lowered 2 GB → 800 MB so 1 GB files start at
     the safe 180p/5fps preset.
  2. ffmpeg memory guards (-threads 1, -bufsize 16M, -max_muxing_queue_size,
     -fflags +discardcorrupt) slash peak RAM.
  3. Rapid-cycle detector in resume_interrupted_processing trips at attempt 2
     if the two cycles happened within 5 min (unambiguous OOM-loop signal —
     waiting for attempt 3 would just burn another 10-15 min of user pain).
  4. Frontend yellow "may not finish" warning banner when pod cycles ≥ 2x
     within 5 min so the user is told what's coming.
"""
import os
import sys
import uuid
import re
from datetime import datetime, timezone, timedelta

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


# ---------------------------------------------------------------------------
# Backend code-level guards (grep against the source)
# ---------------------------------------------------------------------------

def test_processing_threshold_dropped_to_800mb():
    """The aggressive-tier branch must trigger at 800 MB, not 2 GB."""
    src = open("/app/backend/services/processing.py").read()
    # The exact line determining tier should now use 0.8, not 2
    assert "video_size_gb > 0.8" in src, "tier threshold must be 0.8 GB (800 MB) post-iter97"
    assert "video_size_gb > 2" not in src or "video_size_gb > 2:" not in src, (
        "old >2 GB threshold must be removed"
    )


def test_ffmpeg_memory_guards_present():
    """ffmpeg command must include the iter97 memory guards."""
    src = open("/app/backend/services/processing.py").read()
    # -threads 1 prevents libx264 from spawning 8 worker threads
    assert '"-threads", "1"' in src, "ffmpeg must run with -threads 1"
    # max_muxing_queue caps muxer-side memory
    assert "-max_muxing_queue_size" in src
    # bufsize bounds the rate-controller buffer
    assert "-bufsize" in src
    # discardcorrupt avoids buffering corrupt packets waiting for clean GOPs
    assert "+discardcorrupt" in src


def test_rapid_oom_cycle_detection_present():
    """resume_interrupted_processing must short-circuit at attempt 2 when both
    happened within 5 min."""
    src = open("/app/backend/server.py").read()
    # The guard must consider `last_resume_at` and the 5-min window
    assert "last_resume_at" in src
    assert "rapid_loop" in src or "rapid-cycle" in src.lower() or "Rapid" in src
    # 300 seconds = 5 min
    assert "300" in src and "prior_attempts >= 2" in src
    # And the loop must stamp last_resume_at on resume bump
    assert '"last_resume_at"' in src


def test_resume_attempts_projection_includes_last_resume_at():
    """The Mongo projection in stuck_videos must select last_resume_at so
    the in-memory rapid-cycle check works."""
    src = open("/app/backend/server.py").read()
    # Find the resume_interrupted_processing function and verify its
    # stuck_videos projection includes last_resume_at.
    fn_start = src.find("async def resume_interrupted_processing")
    assert fn_start >= 0, "resume_interrupted_processing not found"
    # Inspect the next 2 KB of the function body
    body = src[fn_start:fn_start + 2000]
    assert "stuck_videos = await db.videos.find" in body
    assert '"last_resume_at": 1' in body, (
        "stuck_videos projection must include last_resume_at: 1"
    )


# ---------------------------------------------------------------------------
# Frontend yellow banner
# ---------------------------------------------------------------------------

def test_frontend_hook_exposes_pod_cycling():
    src = open("/app/frontend/src/pages/components/hooks/useVideoProcessing.js").read()
    assert "isPodCycling" in src
    assert "restartCount" in src
    # 5-min window
    assert "5 * 60 * 1000" in src or "300000" in src
    # restartCount >= 2 is the trigger
    assert "restartCount >= 2" in src or "restartCount >=  2" in src


def test_frontend_header_renders_pod_cycling_warning():
    src = open("/app/frontend/src/pages/components/VideoAnalysisHeader.js").read()
    assert "isPodCycling" in src, "header must accept the isPodCycling prop"
    # iter103 — replaced "re-compress with HandBrake" guidance with the
    # blameless "falling back to lighter settings" message. Either form of
    # actionable copy is acceptable here.
    assert (
        "re-compress" in src.lower()
        or "recompress" in src.lower()
        or "lighter" in src.lower()
        or "safe tier" in src.lower()
    ), "cycling banner must mention SOME fallback/recompress action"
    # Yellow palette (#FBBF24) distinguishes from blue (#007AFF) processing banner
    assert "#FBBF24" in src


def test_frontend_video_analysis_passes_is_pod_cycling_to_header():
    src = open("/app/frontend/src/pages/VideoAnalysis.js").read()
    assert "isPodCycling" in src, "VideoAnalysis must destructure isPodCycling from the hook"
    # Passed as a prop down to the header
    assert "isPodCycling={isPodCycling}" in src


# ---------------------------------------------------------------------------
# Backwards compatibility: existing iter75 3-attempt guard still works
# ---------------------------------------------------------------------------

def test_iter75_max_attempts_constant_preserved():
    src = open("/app/backend/server.py").read()
    # The 3-attempt fallback for slow-progress videos that aren't in a rapid
    # cycle is still the safety net
    assert "_MAX_RESUME_ATTEMPTS" in src
    assert "prior_attempts >= _MAX_RESUME_ATTEMPTS and prior_progress == 0" in src


def test_build_version_bumped_to_iter97():
    src = open("/app/backend/server.py").read()
    # iter97 features must still be shipped (this is the contract — version
    # number itself moves forward with future iterations).
    assert "aggressive-tier-threshold-800mb" in src
    assert "rapid-oom-cycle-detection-2-attempts-5min" in src
    # BUILD_VERSION must be at least iter97 (numerically — string compare works
    # for iter97, iter98, iter99 but bricks at iter100; explicit guard)
    m = re.search(r'BUILD_VERSION\s*=\s*"iter(\d+)"', src)
    assert m, "BUILD_VERSION constant not found"
    assert int(m.group(1)) >= 97


# ---------------------------------------------------------------------------
# Live endpoint reflects the new build
# ---------------------------------------------------------------------------

def test_deploy_endpoint_advertises_iter97_features():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            body = r.json()
            # Build version is at least iter97 (forward-compatible)
            m = re.match(r'iter(\d+)', body["build"] or "")
            assert m and int(m.group(1)) >= 97, f"build must be >= iter97, got {body['build']}"
            features = set(body["features"])
            assert "aggressive-tier-threshold-800mb" in features
            assert "ffmpeg-memory-guards-threads1-bufsize" in features
            assert "rapid-oom-cycle-detection-2-attempts-5min" in features
            assert "pod-cycling-yellow-warning-banner" in features
    _run_async(run())
