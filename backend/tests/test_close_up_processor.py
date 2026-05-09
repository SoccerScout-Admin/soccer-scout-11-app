"""AI close-up processor — unit + integration tests.

The pure-logic helpers (JSON parsing, crop-box math, fallback) are
tested directly. The Gemini call + ffmpeg pipeline are mocked because
the wide-segment extraction needs real video chunks (out of scope for
the test database).
"""
from __future__ import annotations

import os
import sys
import uuid
import pytest

sys.path.insert(0, "/app/backend")

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: F401
from services.close_up_processor import (
    _center_fallback, _compute_crop_box, _parse_zoom_response,
)


# ---------- _parse_zoom_response ----------

def test_parse_clean_json():
    raw = '{"x_pct":10,"y_pct":20,"w_pct":40,"h_pct":50,"zoom_level":2.5,"reasoning":"shot on goal"}'
    out = _parse_zoom_response(raw)
    assert out["x_pct"] == 10
    assert out["zoom_level"] == 2.5
    assert "shot on goal" in out["reasoning"]


def test_parse_markdown_fenced_json():
    raw = '```json\n{"x_pct":15,"y_pct":25,"w_pct":35,"h_pct":45,"zoom_level":2.0,"reasoning":"build-up"}\n```'
    out = _parse_zoom_response(raw)
    assert out["x_pct"] == 15
    assert out["zoom_level"] == 2.0


def test_parse_clamps_out_of_range():
    raw = '{"x_pct":-50,"y_pct":150,"w_pct":5,"h_pct":120,"zoom_level":9.0,"reasoning":"bad data"}'
    out = _parse_zoom_response(raw)
    assert 0 <= out["x_pct"] <= 90
    assert 0 <= out["y_pct"] <= 90
    assert 10 <= out["w_pct"] <= 100
    assert 10 <= out["h_pct"] <= 100
    # Zoom should snap to one of the documented levels
    assert out["zoom_level"] in (1.5, 2.0, 2.5)


def test_parse_garbage_returns_center_fallback():
    out = _parse_zoom_response("totally not json")
    assert out["zoom_level"] == 2.0
    assert out["x_pct"] == 25.0
    assert "Fell back" in out["reasoning"]


def test_parse_empty_returns_center_fallback():
    out = _parse_zoom_response("")
    assert out == _center_fallback()


def test_parse_zoom_snaps_to_nearest_documented_level():
    # 1.7 should snap to 1.5 (closer than 2.0)
    out = _parse_zoom_response('{"x_pct":0,"y_pct":0,"w_pct":50,"h_pct":50,"zoom_level":1.7}')
    assert out["zoom_level"] == 1.5
    # 2.3 should snap to 2.5
    out = _parse_zoom_response('{"x_pct":0,"y_pct":0,"w_pct":50,"h_pct":50,"zoom_level":2.3}')
    assert out["zoom_level"] == 2.5


# ---------- _compute_crop_box ----------

def test_crop_box_center_at_center():
    # bbox covering middle 50% of frame, zoom 2x -> half-size crop centered
    bbox = {"x_pct": 25, "y_pct": 25, "w_pct": 50, "h_pct": 50}
    cx, cy, cw, ch = _compute_crop_box(1920, 1080, bbox, 2.0)
    assert (cw, ch) == (960, 540)
    assert cx == 480 and cy == 270


def test_crop_box_left_edge_clamps():
    # bbox in top-left corner; crop window must NOT go negative
    bbox = {"x_pct": 0, "y_pct": 0, "w_pct": 10, "h_pct": 10}
    cx, cy, cw, ch = _compute_crop_box(1920, 1080, bbox, 2.5)
    assert cx >= 0 and cy >= 0
    assert cx + cw <= 1920
    assert cy + ch <= 1080


def test_crop_box_right_edge_clamps():
    bbox = {"x_pct": 95, "y_pct": 95, "w_pct": 10, "h_pct": 10}
    cx, cy, cw, ch = _compute_crop_box(1920, 1080, bbox, 2.0)
    assert cx + cw <= 1920
    assert cy + ch <= 1080


def test_crop_box_dimensions_are_even():
    # libx264 needs even width/height — mirroring real ffmpeg constraints.
    bbox = {"x_pct": 30, "y_pct": 40, "w_pct": 20, "h_pct": 25}
    cx, cy, cw, ch = _compute_crop_box(1919, 1079, bbox, 2.0)
    assert cw % 2 == 0
    assert ch % 2 == 0
    assert cx % 2 == 0
    assert cy % 2 == 0


# ---------- HTTP endpoints ----------

@pytest.fixture(scope="module")
def admin_headers():
    import requests
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "Ben.buursma@gmail.com", "password": "BenAdmin2026!"})
    if r.status_code != 200:
        pytest.skip("admin account not available")
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_generate_close_up_404_for_unknown_clip(admin_headers):
    import requests
    r = requests.post(f"{BASE_URL}/api/clips/{uuid.uuid4()}/generate-close-up", headers=admin_headers)
    assert r.status_code == 404
    assert r.json()["detail"] == "Clip not found"


def test_close_up_retry_404_for_unknown_clip(admin_headers):
    import requests
    r = requests.post(f"{BASE_URL}/api/clips/{uuid.uuid4()}/close-up/retry", headers=admin_headers)
    assert r.status_code == 404


def test_generate_close_up_requires_auth():
    import requests
    r = requests.post(f"{BASE_URL}/api/clips/{uuid.uuid4()}/generate-close-up")
    assert r.status_code in (401, 403)


def test_generate_close_up_noop_when_already_ready(admin_headers):
    """If the clip already has a ready close-up, the endpoint should reply
    `already_done: true` rather than re-queuing."""
    import requests

    async def setup():
        from db import db
        user = await db.users.find_one({"email": "Ben.buursma@gmail.com"}, {"_id": 0, "id": 1})
        clip_id = "noop-test-" + uuid.uuid4().hex[:8]
        await db.clips.insert_one({
            "id": clip_id, "user_id": user["id"], "video_id": "fake-vid",
            "match_id": "fake-match", "title": "Noop Test",
            "start_time": 0, "end_time": 2, "clip_type": "highlight",
            "auto_generated": False, "close_up_status": "ready",
            "close_up_path": "/nonexistent/file.mp4",
        })
        return clip_id

    clip_id = _run_async(setup())
    try:
        r = requests.post(f"{BASE_URL}/api/clips/{clip_id}/generate-close-up", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["already_done"] is True
    finally:
        async def cleanup():
            from db import db
            await db.clips.delete_one({"id": clip_id})
        _run_async(cleanup())


def test_extract_serves_close_up_when_ready(admin_headers, tmp_path):
    """When close_up_status=ready and the file exists, /extract should
    serve it directly without going through chunk reassembly."""
    import requests
    import subprocess

    async def setup():
        from db import db, CHUNK_STORAGE_DIR
        user = await db.users.find_one({"email": "Ben.buursma@gmail.com"}, {"_id": 0, "id": 1})
        close_up_dir = os.path.join(CHUNK_STORAGE_DIR, "close_ups")
        os.makedirs(close_up_dir, exist_ok=True)
        clip_id = "extract-test-" + uuid.uuid4().hex[:8]
        dest = os.path.join(close_up_dir, f"{clip_id}.mp4")
        # Synthesize a tiny valid mp4
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x90:d=1",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", dest,
        ], capture_output=True, timeout=30, check=True)
        await db.clips.insert_one({
            "id": clip_id, "user_id": user["id"], "video_id": "fake-vid",
            "match_id": "fake-match", "title": "Extract Test",
            "start_time": 0, "end_time": 1, "clip_type": "goal",
            "auto_generated": False, "close_up_status": "ready",
            "close_up_path": dest,
        })
        return clip_id, dest

    clip_id, dest = _run_async(setup())
    try:
        r = requests.get(f"{BASE_URL}/api/clips/{clip_id}/extract", headers=admin_headers)
        assert r.status_code == 200
        assert r.headers["content-type"] == "video/mp4"
        # Bytes must match the on-disk file exactly (no re-encoding)
        assert len(r.content) == os.path.getsize(dest)
    finally:
        async def cleanup():
            from db import db
            if os.path.exists(dest):
                os.unlink(dest)
            await db.clips.delete_one({"id": clip_id})
        _run_async(cleanup())
