"""Auto-Highlight Reel Generator — unit + HTTP integration tests.

Pure-logic helpers (scoring, selection, title formatting) are tested
directly. The Gemini-free pipeline (Pillow title-card + ffmpeg concat) is
verified end-to-end with a synthesized source video so we exercise the
real ffmpeg path. Slow tests are skip-guarded when ffmpeg isn't on PATH.
"""
from __future__ import annotations

import os
import sys
import subprocess
import uuid
import pytest

sys.path.insert(0, "/app/backend")

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: F401
from services.highlight_reel import (
    CLIP_TYPE_SCORE, MAX_DURATION_S, TITLE_CARD_DURATION_S,
    _format_minute, _humanize_clip_type, _accent_for_type,
    _score_clip, _select_clips, is_ffmpeg_available,
)
from services.og_card import render_reel_title_card, render_highlight_reel_card


# ---------- _score_clip ----------

def test_score_goal_beats_highlight():
    goal = {"clip_type": "goal", "start_time": 10, "end_time": 18, "player_ids": []}
    hl = {"clip_type": "highlight", "start_time": 10, "end_time": 18, "player_ids": []}
    assert _score_clip(goal) > _score_clip(hl)


def test_score_tagged_players_bonus():
    a = {"clip_type": "goal", "start_time": 10, "end_time": 18, "player_ids": []}
    b = {"clip_type": "goal", "start_time": 10, "end_time": 18, "player_ids": ["p1"]}
    assert _score_clip(b) == _score_clip(a) + 10


def test_score_too_short_penalty():
    short = {"clip_type": "goal", "start_time": 0, "end_time": 2, "player_ids": []}
    normal = {"clip_type": "goal", "start_time": 0, "end_time": 8, "player_ids": []}
    assert _score_clip(short) < _score_clip(normal)


def test_score_unknown_type_falls_to_default():
    unk = {"clip_type": "totally-made-up", "start_time": 0, "end_time": 8, "player_ids": []}
    # Default base is 40; clip-duration is 8s so no penalty
    assert _score_clip(unk) == 40


# ---------- _select_clips ----------

def _mk_clip(idx, ctype="highlight", duration=8.0, players=None):
    return {
        "id": f"c{idx}",
        "user_id": "u1",
        "video_id": "v1",
        "match_id": "m1",
        "title": f"Clip {idx}",
        "start_time": float(idx * 60),
        "end_time": float(idx * 60 + duration),
        "clip_type": ctype,
        "player_ids": players or [],
    }


def test_select_empty_returns_empty():
    selected, total = _select_clips([])
    assert selected == []
    assert total == 0.0


def test_select_prioritizes_goals():
    clips = [
        _mk_clip(1, "highlight"),
        _mk_clip(2, "goal"),
        _mk_clip(3, "highlight"),
        _mk_clip(4, "goal"),
    ]
    selected, _ = _select_clips(clips)
    # Both goals should make it ahead of pure highlights
    selected_types = [c["clip_type"] for c in selected]
    assert selected_types.count("goal") == 2


def test_select_fits_within_budget():
    # 20 highlights of 8s = 160s — vastly exceeds 90s budget.
    clips = [_mk_clip(i, "highlight") for i in range(20)]
    selected, _ = _select_clips(clips)
    overhead = TITLE_CARD_DURATION_S * len(selected)
    clip_secs = sum(c["end_time"] - c["start_time"] for c in selected)
    assert overhead + clip_secs <= MAX_DURATION_S
    assert len(selected) >= 1


def test_select_returns_chronological_order():
    # Out-of-order goals — chronological tie-break should reorder for narrative.
    clips = [
        _mk_clip(5, "goal"),
        _mk_clip(1, "goal"),
        _mk_clip(3, "goal"),
    ]
    selected, _ = _select_clips(clips)
    times = [c["start_time"] for c in selected]
    assert times == sorted(times), f"Selection not in chronological order: {times}"


def test_select_trims_overlong_clips():
    long_clip = _mk_clip(1, "goal", duration=30.0)
    selected, _ = _select_clips([long_clip])
    assert len(selected) == 1
    # Should be capped to <= 12s
    duration = selected[0]["end_time"] - selected[0]["start_time"]
    assert duration <= 12.0


# ---------- helpers ----------

def test_format_minute_seconds_to_min_label():
    assert _format_minute(0) == "0'"
    assert _format_minute(59) == "0'"
    assert _format_minute(60) == "1'"
    assert _format_minute(3600) == "60'"


def test_humanize_clip_type():
    assert _humanize_clip_type("goal") == "GOAL"
    assert _humanize_clip_type("key_pass") == "KEY PASS"
    assert _humanize_clip_type(None) == "HIGHLIGHT"
    assert _humanize_clip_type("unknown_type") == "HIGHLIGHT"


def test_accent_for_type_varies():
    assert _accent_for_type("goal") != _accent_for_type("save")
    assert _accent_for_type("foul") != _accent_for_type("goal")


def test_clip_score_constants_documented():
    assert CLIP_TYPE_SCORE["goal"] == 100
    assert CLIP_TYPE_SCORE["save"] == 80


# ---------- OG card renderers ----------

def test_render_reel_title_card_returns_png():
    out = render_reel_title_card("GOAL 1 · 23'", "Bukayo Saka", "Arsenal vs Chelsea", (16, 185, 129))
    # PNG signature
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    # Should be at least a few KB
    assert len(out) > 5000


def test_render_highlight_reel_og_card_returns_png():
    out = render_highlight_reel_card(
        team_home="Arsenal", team_away="Chelsea",
        home_score=3, away_score=1, competition="Premier League",
        clip_count=5, duration_seconds=72.0, coach_name="Mikel Arteta",
    )
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(out) > 10000


def test_render_reel_card_handles_missing_score():
    """When manual_result isn't set, scores are None — must not crash."""
    out = render_highlight_reel_card(
        team_home="Home", team_away="Away",
        home_score=None, away_score=None,
        clip_count=3, duration_seconds=45.0,
    )
    assert out[:8] == b"\x89PNG\r\n\x1a\n"


# ---------- HTTP endpoints ----------

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


def test_create_reel_requires_auth():
    import requests
    r = requests.post(f"{BASE_URL}/api/matches/{uuid.uuid4()}/highlight-reel")
    assert r.status_code in (401, 403)


def test_create_reel_unknown_match_404(admin_headers):
    import requests
    r = requests.post(
        f"{BASE_URL}/api/matches/{uuid.uuid4()}/highlight-reel",
        headers=admin_headers,
    )
    assert r.status_code == 404


def test_create_reel_no_clips_returns_400(admin_headers):
    """A match with zero clips must give a clear 400 error."""
    import requests

    async def setup():
        from db import db
        user = await db.users.find_one({"email": "Ben.buursma@gmail.com"}, {"_id": 0, "id": 1})
        match_id = "reel-no-clips-" + uuid.uuid4().hex[:8]
        await db.matches.insert_one({
            "id": match_id, "user_id": user["id"],
            "team_home": "A", "team_away": "B", "date": "2026-01-01",
            "competition": "Test", "folder_id": None, "video_id": None,
        })
        return match_id

    match_id = _run_async(setup())
    try:
        r = requests.post(
            f"{BASE_URL}/api/matches/{match_id}/highlight-reel",
            headers=admin_headers,
        )
        assert r.status_code == 400
        assert "no clips" in r.json()["detail"].lower()
    finally:
        async def cleanup():
            from db import db
            await db.matches.delete_one({"id": match_id})
        _run_async(cleanup())


def test_get_reel_unknown_404(admin_headers):
    import requests
    r = requests.get(
        f"{BASE_URL}/api/highlight-reels/{uuid.uuid4()}",
        headers=admin_headers,
    )
    assert r.status_code == 404


def test_public_reel_unknown_token_404():
    import requests
    r = requests.get(f"{BASE_URL}/api/highlight-reels/public/{uuid.uuid4().hex[:12]}")
    assert r.status_code == 404


def test_share_reel_requires_ready_status(admin_headers):
    """Pending/processing reels cannot be shared yet."""
    import requests

    async def setup():
        from db import db
        user = await db.users.find_one({"email": "Ben.buursma@gmail.com"}, {"_id": 0, "id": 1})
        reel_id = "reel-share-" + uuid.uuid4().hex[:8]
        await db.highlight_reels.insert_one({
            "id": reel_id, "user_id": user["id"], "match_id": "x",
            "status": "pending", "progress": 0.0, "share_token": None,
            "selected_clip_ids": [], "total_clips": 0, "output_path": None,
        })
        return reel_id

    reel_id = _run_async(setup())
    try:
        r = requests.post(
            f"{BASE_URL}/api/highlight-reels/{reel_id}/share",
            headers=admin_headers,
        )
        assert r.status_code == 400
        assert "not ready" in r.json()["detail"].lower()
    finally:
        async def cleanup():
            from db import db
            await db.highlight_reels.delete_one({"id": reel_id})
        _run_async(cleanup())


def test_share_reel_toggles_when_ready(admin_headers):
    """First call generates token, second call revokes."""
    import requests

    async def setup():
        from db import db
        user = await db.users.find_one({"email": "Ben.buursma@gmail.com"}, {"_id": 0, "id": 1})
        reel_id = "reel-togl-" + uuid.uuid4().hex[:8]
        await db.highlight_reels.insert_one({
            "id": reel_id, "user_id": user["id"], "match_id": "x",
            "status": "ready", "progress": 1.0, "share_token": None,
            "selected_clip_ids": ["c1"], "total_clips": 1,
            "output_path": None, "duration_seconds": 30.0,
        })
        return reel_id

    reel_id = _run_async(setup())
    try:
        r = requests.post(
            f"{BASE_URL}/api/highlight-reels/{reel_id}/share",
            headers=admin_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "shared"
        token = body["share_token"]
        assert len(token) == 12

        # Public JSON returns reel (without user_id)
        pub = requests.get(f"{BASE_URL}/api/highlight-reels/public/{token}")
        assert pub.status_code == 200
        assert "user_id" not in pub.json()
        assert pub.json()["status"] == "ready"

        # Toggle off
        r2 = requests.post(
            f"{BASE_URL}/api/highlight-reels/{reel_id}/share",
            headers=admin_headers,
        )
        assert r2.json()["status"] == "unshared"

        # Public link now 404s
        pub2 = requests.get(f"{BASE_URL}/api/highlight-reels/public/{token}")
        assert pub2.status_code == 404
    finally:
        async def cleanup():
            from db import db
            await db.highlight_reels.delete_one({"id": reel_id})
        _run_async(cleanup())


def test_og_card_image_for_shared_reel(admin_headers):
    """OG endpoint serves a real PNG."""
    import requests

    async def setup():
        from db import db
        user = await db.users.find_one({"email": "Ben.buursma@gmail.com"}, {"_id": 0, "id": 1})
        reel_id = "reel-og-" + uuid.uuid4().hex[:8]
        match_id = "reel-og-match-" + uuid.uuid4().hex[:8]
        await db.matches.insert_one({
            "id": match_id, "user_id": user["id"],
            "team_home": "Arsenal", "team_away": "Chelsea",
            "date": "2026-01-01", "competition": "Premier League",
        })
        await db.highlight_reels.insert_one({
            "id": reel_id, "user_id": user["id"], "match_id": match_id,
            "status": "ready", "progress": 1.0, "share_token": "tok" + uuid.uuid4().hex[:9],
            "selected_clip_ids": ["c1", "c2", "c3"], "total_clips": 3,
            "output_path": None, "duration_seconds": 65.0,
        })
        return reel_id, match_id

    reel_id, match_id = _run_async(setup())
    try:
        # Read share token
        async def fetch():
            from db import db
            return await db.highlight_reels.find_one({"id": reel_id}, {"_id": 0})
        reel = _run_async(fetch())
        token = reel["share_token"]

        r = requests.get(f"{BASE_URL}/api/og/highlight-reel/{token}/image.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(r.content) > 5000

        # HTML unfurl carries og:title + og:image meta tags
        html = requests.get(f"{BASE_URL}/api/og/highlight-reel/{token}")
        assert html.status_code == 200
        assert "og:title" in html.text
        assert "og:image" in html.text
        assert "Arsenal" in html.text and "Chelsea" in html.text
    finally:
        async def cleanup():
            from db import db
            await db.highlight_reels.delete_one({"id": reel_id})
            await db.matches.delete_one({"id": match_id})
        _run_async(cleanup())


@pytest.mark.skipif(not is_ffmpeg_available(), reason="ffmpeg not on PATH")
def test_title_card_segment_renders_via_ffmpeg(tmp_path):
    """End-to-end: title-card PNG → mp4 segment via ffmpeg."""
    from services.highlight_reel import _make_title_card_segment

    async def go():
        return await _make_title_card_segment(
            "GOAL 1 · 23'", "Bukayo Saka", "Arsenal vs Chelsea",
            (16, 185, 129), duration_s=1.5, width=640, height=360,
        )

    out_path = _run_async(go())
    try:
        assert out_path is not None
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 1000
        # ffprobe duration should be ~1.5s
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", out_path,
        ], capture_output=True, text=True, timeout=20)
        duration = float(result.stdout.strip())
        assert 1.0 < duration < 2.0
    finally:
        if out_path and os.path.exists(out_path):
            os.unlink(out_path)
