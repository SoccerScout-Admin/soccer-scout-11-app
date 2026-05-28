"""
iter103 — Segment encoder tier-down for >800 MB files.

Production bug 2026-05-28: re-uploaded the LFC 2007B vs AYSO video on
iter102 → pod-cycling banner fires within seconds → no processing progress.
Root cause: iter101 introduced 720p segments + scdet pre-pass which
together push total processing memory above the cgroup limit on the
production pod. iter99 worked (480p / no scdet); iter102 doesn't.

Fix: same threshold logic as iter97's single-sample path. >800 MB files
drop to the iter99-era settings (480p / 12fps / CRF 28) AND skip the
scdet pre-pass entirely, using even spacing. ≤800 MB files keep the
iter101 high-quality 720p + scdet path because they have memory headroom.

Bonus: cycling-banner UX rewrite. The previous "your file is too heavy
— re-compress with HandBrake" message blamed the user; iter103 says
"falling back to lighter encoding — your file is fine, this is on us"
which is accurate (the user IS already at HandBrake's recommended preset).
"""
import os
import re
import sys

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


# ---------------------------------------------------------------------------
# 1. Heavy-file tier-down is wired into the segment path
# ---------------------------------------------------------------------------

def test_segments_threshold_uses_iter97_800mb_constant():
    """The segment-path tier-down must use the same 0.8 GB threshold as
    iter97's single-sample tier-down — keeps them in lockstep."""
    src = open("/app/backend/services/processing.py").read()
    fn_start = src.find("async def prepare_video_segments_720p")
    body = src[fn_start:fn_start + 6000]
    assert "video_size_gb > 0.8" in body, (
        "segment path must tier-down at 800 MB (matches iter97 single-sample threshold)"
    )
    assert "heavy_file" in body


def test_heavy_files_use_iter99_safe_segment_params():
    """For >800 MB sources the segments must drop to 480p / 12fps / CRF 28
    (the iter99 settings that were proven to work on the production pod)."""
    src = open("/app/backend/services/processing.py").read()
    fn_start = src.find("async def prepare_video_segments_720p")
    body = src[fn_start:fn_start + 6000]
    # Heavy-file branch sets the tier vars
    assert 'seg_scale = "scale=-2:480"' in body
    assert 'seg_fps = "12"' in body
    assert 'seg_crf = "28"' in body
    # Light-file branch keeps iter101 high-quality
    assert 'seg_scale = "scale=-2:720"' in body
    assert 'seg_fps = "15"' in body
    assert 'seg_crf = "24"' in body


def test_heavy_files_skip_scdet_pre_pass():
    """The scdet motion-window pass is itself memory-intensive (full decode
    of the 1+ GB raw file even at 240p). Heavy files must bypass it and
    use even spacing directly."""
    src = open("/app/backend/services/processing.py").read()
    fn_start = src.find("async def prepare_video_segments_720p")
    body = src[fn_start:fn_start + 6000]
    # The heavy branch sets segment_starts = [] BEFORE calling _select_motion_windows
    assert "if heavy_file:" in body
    heavy_branch = body[body.find("if heavy_file:"):body.find("else:", body.find("if heavy_file:"))]
    assert "segment_starts = []" in heavy_branch
    assert "_select_motion_windows" not in heavy_branch, (
        "heavy-file branch must NOT call _select_motion_windows — skip it"
    )


def test_light_files_still_use_scdet():
    src = open("/app/backend/services/processing.py").read()
    fn_start = src.find("async def prepare_video_segments_720p")
    body = src[fn_start:fn_start + 6000]
    # The else branch still calls scdet
    else_start = body.find("else:", body.find("if heavy_file:"))
    light_branch = body[else_start:else_start + 1500]
    assert "_select_motion_windows" in light_branch


def test_seg_cmd_uses_tier_variables_not_hardcoded():
    """The ffmpeg seg_cmd must use the tier-adaptive variables (seg_scale,
    seg_fps, seg_crf) — NOT the old hardcoded 720p/15/24."""
    src = open("/app/backend/services/processing.py").read()
    fn_start = src.find("async def prepare_video_segments_720p")
    body = src[fn_start:fn_start + 8000]
    # Locate seg_cmd construction
    seg_cmd_idx = body.find("seg_cmd = [")
    assert seg_cmd_idx >= 0
    seg_cmd_block = body[seg_cmd_idx:seg_cmd_idx + 1500]
    assert '"-vf", seg_scale' in seg_cmd_block
    assert '"-crf", seg_crf' in seg_cmd_block
    assert '"-r", seg_fps' in seg_cmd_block
    # And the old hardcoded values must be gone from THIS block
    assert '"-vf", "scale=-2:720"' not in seg_cmd_block
    assert '"-crf", "24"' not in seg_cmd_block
    assert '"-r", "15"' not in seg_cmd_block


def test_iter97_memory_guards_still_present():
    """When adding tier vars don't accidentally remove the iter97 memory
    guards that prevent the OOM regression."""
    src = open("/app/backend/services/processing.py").read()
    fn_start = src.find("async def prepare_video_segments_720p")
    body = src[fn_start:fn_start + 8000]
    seg_cmd_idx = body.find("seg_cmd = [")
    seg_cmd_block = body[seg_cmd_idx:seg_cmd_idx + 1500]
    assert '"-threads", "1"' in seg_cmd_block
    assert '"-max_muxing_queue_size"' in seg_cmd_block
    assert '"-bufsize"' in seg_cmd_block
    assert "+discardcorrupt" in seg_cmd_block


# ---------------------------------------------------------------------------
# 2. Cycling banner messaging is blameless
# ---------------------------------------------------------------------------

def test_cycling_banner_no_longer_blames_user_compression():
    src = open("/app/frontend/src/pages/components/VideoAnalysisHeader.js").read()
    # The old "too heavy — re-compress with HandBrake" message must be gone
    assert "too heavy for our encoder" not in src
    assert "HandBrake" not in src or "Fast 720p30" not in src  # outdated guidance
    # The new blameless message
    assert "your file is fine" in src.lower() or "this is on us" in src.lower()


def test_cycling_banner_explains_fallback_action():
    """Whatever the new headline says, the subtitle must tell the user what
    we're DOING (falling back to a lighter tier) so they don't think we're
    just spinning forever."""
    src = open("/app/frontend/src/pages/components/VideoAnalysisHeader.js").read()
    assert "lighter" in src.lower() or "safe tier" in src.lower() or "480p" in src
    assert "Retry Processing" in src or "retry" in src.lower()


# ---------------------------------------------------------------------------
# 3. Deploy endpoint advertises iter103 feature flags
# ---------------------------------------------------------------------------

def test_deploy_endpoint_advertises_iter103_features():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            body = r.json()
            # forward-compat: build at least iter103
            m = re.match(r'iter(\d+)', body["build"] or "")
            assert m and int(m.group(1)) >= 103
            features = set(body["features"])
            assert "segments-tier-down-800mb-480p" in features
            assert "segments-skip-scdet-on-heavy-files" in features
            assert "cycling-banner-blameless-messaging" in features
    _run_async(run())
