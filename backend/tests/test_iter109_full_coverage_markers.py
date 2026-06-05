"""iter109 — Full-match coverage for AI timeline markers.

Root-cause fix: long matches were only ~13% sampled (18x45s windows) so goals
outside those windows were never shown to Gemini → ~1 marker for a whole match.
The new pipeline transcodes the ENTIRE match into contiguous low-res chunks,
runs Gemini per chunk, offsets per-chunk timestamps to absolute match time, and
merges + dedupes the events.

These tests cover the deterministic pieces (window math, parsing+offset, dedupe,
prompt) plus an end-to-end orchestration test with Gemini mocked.
"""
import re
import uuid
import json
import httpx
import pytest

from conftest import BASE_URL, run_async

from services import processing as P


# ---------------------------------------------------------------------------
# 1. Coverage window math — must cover 100% of the match with no gaps
# ---------------------------------------------------------------------------

def test_coverage_windows_long_match_full_coverage():
    duration = 6180.0  # 1h43m — the real failing match
    wins = P._compute_coverage_windows(duration, chunk_seconds=1500, overlap=10)
    assert len(wins) == 5, f"expected 5 chunks for 103min/25min, got {len(wins)}"
    # First window starts at 0, last window ends at duration (no missed tail)
    assert wins[0][0] == 0.0
    last_start, last_len = wins[-1]
    assert abs((last_start + last_len) - duration) < 1.5
    # No coverage gaps: each window starts at/before the previous window's end
    for i in range(1, len(wins)):
        prev_end = wins[i - 1][0] + wins[i - 1][1]
        assert wins[i][0] <= prev_end + 0.01, f"gap before window {i}"


def test_coverage_windows_short_match_single_chunk():
    wins = P._compute_coverage_windows(600.0, chunk_seconds=1500, overlap=10)
    assert len(wins) == 1
    assert wins[0] == (0.0, 600.0)


def test_coverage_windows_two_chunks_with_overlap():
    wins = P._compute_coverage_windows(3000.0, chunk_seconds=1500, overlap=10)
    assert len(wins) == 2
    # second window starts 10s early (overlap) so a boundary goal isn't split
    assert wins[1][0] == pytest.approx(1490.0, abs=0.1)


def test_coverage_windows_zero_duration():
    assert P._compute_coverage_windows(0) == []


# ---------------------------------------------------------------------------
# 2. Marker parsing — offset application + robustness
# ---------------------------------------------------------------------------

def test_parse_markers_applies_time_offset():
    resp = json.dumps([
        {"time": 12, "type": "goal", "label": "Header", "team": "LFC", "importance": 5,
         "player_number": 9, "player_name": "Sam"},
        {"time": 300, "type": "save", "label": "Tip over", "team": "Dayton", "importance": 4},
    ])
    out = P._parse_markers_response(resp, time_offset=3000.0)
    assert len(out) == 2
    assert out[0]["time"] == 3012.0  # 12 + 3000 offset → absolute match time
    assert out[1]["time"] == 3300.0
    assert out[0]["type"] == "goal"
    assert out[0]["player_number"] == 9


def test_parse_markers_strips_code_fences_and_handles_garbage():
    fenced = "```json\n[{\"time\": 5, \"type\": \"shot\", \"importance\": 3}]\n```"
    out = P._parse_markers_response(fenced, time_offset=0)
    assert len(out) == 1 and out[0]["type"] == "shot"
    # garbage / non-list → empty list, never raises
    assert P._parse_markers_response("not json at all") == []
    assert P._parse_markers_response(json.dumps({"not": "a list"})) == []
    assert P._parse_markers_response("") == []


def test_parse_markers_clamps_importance_and_player_number():
    resp = json.dumps([
        {"time": 1, "type": "goal", "importance": 99, "player_number": "abc"},
        {"time": 2, "type": "foul", "importance": 0, "player_number": ""},
    ])
    out = P._parse_markers_response(resp)
    assert out[0]["importance"] == 5  # clamped to max 5
    assert out[0]["player_number"] is None  # non-numeric → None (no guessing)
    assert out[1]["importance"] == 1  # clamped to min 1
    assert out[1]["player_number"] is None


# ---------------------------------------------------------------------------
# 3. Dedupe across chunk boundaries
# ---------------------------------------------------------------------------

def test_dedupe_merges_boundary_duplicates_keeps_higher_importance():
    markers = [
        {"time": 1495.0, "type": "goal", "label": "blurry", "team": "LFC", "importance": 4,
         "player_number": None, "player_name": None},
        # same goal seen again in the overlapping next chunk, higher importance + number
        {"time": 1497.0, "type": "goal", "label": "clear", "team": "LFC", "importance": 5,
         "player_number": 9, "player_name": "Sam"},
        # a genuinely different event far away
        {"time": 2400.0, "type": "goal", "label": "second goal", "team": "Dayton", "importance": 5,
         "player_number": None, "player_name": None},
    ]
    out = P._dedupe_markers(markers, window_sec=7.0)
    assert len(out) == 2  # the two 1495/1497 goals merged into one
    merged = [m for m in out if m["time"] < 2000][0]
    assert merged["importance"] == 5 and merged["player_number"] == 9  # kept the better copy


def test_dedupe_keeps_distinct_types_at_same_time():
    markers = [
        {"time": 100.0, "type": "shot", "label": "", "team": "LFC", "importance": 3,
         "player_number": None, "player_name": None},
        {"time": 101.0, "type": "goal", "label": "", "team": "LFC", "importance": 5,
         "player_number": None, "player_name": None},
    ]
    out = P._dedupe_markers(markers)
    assert len(out) == 2  # different types are NOT merged


# ---------------------------------------------------------------------------
# 4. Chunk prompt — clip-relative timing + match-time window context
# ---------------------------------------------------------------------------

def test_chunk_prompt_requests_clip_relative_time():
    match = {"team_home": "LFC 2007B", "team_away": "Dayton Cobras",
             "team_home_jersey_color": "red", "team_away_jersey_color": "white"}
    prompt = P.build_timeline_markers_chunk_prompt(match, "", 3000.0, 4500.0)
    assert "FROM THE START OF THIS CLIP" in prompt
    assert "50:00 to 75:00" in prompt  # 3000s..4500s window in mm:ss
    assert "LFC 2007B" in prompt and "Dayton Cobras" in prompt
    assert "red" in prompt and "white" in prompt  # kit colors injected
    assert "goal" in prompt.lower()


# ---------------------------------------------------------------------------
# 5. End-to-end orchestration with Gemini + chunk-prep mocked
# ---------------------------------------------------------------------------

def test_full_coverage_orchestration_merges_and_stores(monkeypatch):
    video_id = f"iter109-vid-{uuid.uuid4().hex[:8]}"
    match_id = f"iter109-match-{uuid.uuid4().hex[:8]}"
    user_id = f"iter109-user-{uuid.uuid4().hex[:8]}"

    # 2 fake chunks: match-time 0-1500 and 1490-3000
    fake_chunks = [("/tmp/_nonexistent_cov0.mp4", 0.0, 1500.0),
                   ("/tmp/_nonexistent_cov1.mp4", 1490.0, 1510.0)]

    async def fake_prepare(video):
        return fake_chunks

    # chunk 0 reports a goal at clip-second 600 (→ absolute 600)
    # chunk 1 reports a goal at clip-second 910 (→ absolute 1490+910 = 2400)
    # iter111 — session_id is now "markers-{video_id}-{idx}-{attempt}", so key by idx.
    responses_by_idx = {
        "0": json.dumps([
            {"time": 600, "type": "goal", "label": "G1", "team": "LFC", "importance": 5}
        ]),
        "1": json.dumps([
            {"time": 910, "type": "goal", "label": "G2", "team": "Dayton", "importance": 5}
        ]),
    }

    async def fake_send(video_file_path, prompt, session_id, system_message=None):
        # "markers-<video_id>-<idx>-<attempt>" → second-to-last token is the idx
        idx = session_id.rsplit("-", 2)[-2]
        return responses_by_idx[idx]

    monkeypatch.setattr(P, "prepare_full_coverage_chunks", fake_prepare)
    monkeypatch.setattr(P, "_send_video_to_gemini", fake_send)

    clip_calls = {"n": 0}

    async def fake_clip_cb(vid, uid, mid):
        clip_calls["n"] += 1

    match = {"id": match_id, "team_home": "LFC 2007B", "team_away": "Dayton Cobras"}
    video = {"id": video_id, "match_id": match_id, "original_filename": "m.mp4"}

    async def run_and_check():
        import os as _os
        from motor.motor_asyncio import AsyncIOMotorClient
        # Fresh client created inside the running loop so Motor binds to it
        # (avoids cross-loop errors from the shared module-level db client).
        client = AsyncIOMotorClient(_os.environ["MONGO_URL"])
        testdb = client[_os.environ["DB_NAME"]]
        monkeypatch.setattr(P, "db", testdb)
        try:
            count = await P.run_timeline_markers_full_coverage(
                video, match, "", video_id, user_id, match_id, fake_clip_cb
            )
            assert count == 2, f"expected 2 merged goals, got {count}"
            markers = await testdb.markers.find(
                {"video_id": video_id}, {"_id": 0}
            ).to_list(50)
            times = sorted(m["time"] for m in markers)
            # absolute match times: 600 (chunk0) and 2400 (chunk1 offset applied)
            assert times == [600.0, 2400.0], f"absolute times wrong: {times}"
            assert all(m["type"] == "goal" for m in markers)
            assert clip_calls["n"] == 1  # auto-clip callback fired exactly once
            an = await testdb.analyses.find_one(
                {"video_id": video_id, "analysis_type": "timeline_markers"}, {"_id": 0}
            )
            assert an and an["status"] == "completed"
        finally:
            await testdb.markers.delete_many({"video_id": video_id})
            await testdb.analyses.delete_many({"video_id": video_id})
            client.close()

    run_async(run_and_check())


# ---------------------------------------------------------------------------
# 6. Build version + deploy flags
# ---------------------------------------------------------------------------

def test_build_version_is_iter109_or_newer():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            m = re.search(r"iter(\d+)", r.json()["build"])
            assert m and int(m.group(1)) >= 109
    run_async(run())


def test_deploy_advertises_full_coverage_flags():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            features = set(r.json()["features"])
            assert "full-match-coverage-timeline-markers" in features
            assert "timeline-markers-chunked-full-coverage" in features
            assert "timeline-markers-merge-dedupe" in features
    run_async(run())
