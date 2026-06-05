"""iter111 — Marker recall + coverage + resilience.

Production feedback (2026-06-04): full games produced only 5-10 markers (expected
60-80) and the AI output referenced only a single ~20-25 min "segment provided" —
i.e. most chunks were being SILENTLY DROPPED on the 4 GB pod, so only ~a quarter
of the match was analyzed. Types were also frequently mislabeled.

Fixes verified here:
  • 480p (was 360p) + audio re-enabled + crf30 + tighter 18-min chunks
  • per-chunk transcode retry tier (480p → 360p) so chunks stop being dropped
  • per-chunk Gemini retry so a transient failure doesn't drop a segment
  • strict event-type decision guide + audio cues + exhaustiveness in the prompt
  • coverage telemetry persisted on the timeline_markers analysis doc + surfaced
"""
import re
import json
import uuid
import inspect
import httpx

from conftest import BASE_URL, run_async
from services import processing as P


# ---------------------------------------------------------------------------
# 1. Tightened chunk constants (recall + sharper frames)
# ---------------------------------------------------------------------------

def test_chunk_constants_tightened_for_recall():
    assert P._FULL_COVERAGE_CHUNK_SECONDS == 1080   # 18 min (was 1500/25 min)
    assert P._FULL_COVERAGE_SCALE == "scale=-2:480"  # 480p (was 360p)
    assert P._FULL_COVERAGE_CRF == "30"              # sharper (was 32)
    assert P._FULL_COVERAGE_FALLBACK_SCALE == "scale=-2:360"  # retry tier exists


def test_long_match_now_makes_more_chunks():
    # 103-min match: 25-min chunks → 5; 18-min chunks → 6 (more granular recall)
    wins = P._compute_coverage_windows(6180.0)  # uses the new default 1080s
    assert len(wins) >= 6
    # still covers 100% (last window ends at duration)
    assert abs((wins[-1][0] + wins[-1][1]) - 6180.0) < 2.0


# ---------------------------------------------------------------------------
# 2. Audio re-enabled + retry tier in the transcoder source
# ---------------------------------------------------------------------------

def test_chunk_transcode_has_audio_and_retry_tier():
    src = inspect.getsource(P.prepare_full_coverage_chunks)
    assert '"-c:a", "aac"' in src           # audio re-enabled for event cues
    assert "_FULL_COVERAGE_FALLBACK_SCALE" in src  # 360p retry tier
    assert "with_audio" in src              # audio toggle present
    # two attempt tiers (480p+audio, then 360p no-audio)
    assert "attempts = [" in src


# ---------------------------------------------------------------------------
# 3. Strict event-type decision guide + audio cues in the prompt
# ---------------------------------------------------------------------------

def test_marker_prompt_has_strict_type_guide_and_audio():
    match = {"team_home": "LFC", "team_away": "Dayton"}
    prompt = P.build_timeline_markers_chunk_prompt(match, "", 0.0, 1080.0)
    low = prompt.lower()
    # event-type disambiguation
    assert "decision guide" in low
    assert "keeper touched it" in low and "save" in low
    assert "if it went in, it is a goal" in low
    # audio cues
    assert "whistle" in low and "crowd roar" in low
    # exhaustiveness target
    assert "exhaustive" in low
    assert "12" in prompt and "20" in prompt  # the 12-20+ events target


# ---------------------------------------------------------------------------
# 4. Coverage telemetry + per-chunk Gemini retry (mocked Gemini, real Mongo)
# ---------------------------------------------------------------------------

def _make_db(monkeypatch):
    import os as _os
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(_os.environ["MONGO_URL"])
    testdb = client[_os.environ["DB_NAME"]]
    monkeypatch.setattr(P, "db", testdb)
    return client, testdb


def test_markers_persist_coverage_telemetry(monkeypatch):
    video_id = f"i111-vid-{uuid.uuid4().hex[:8]}"
    match_id = "m"
    user_id = "u"
    match = {"id": match_id, "team_home": "LFC", "team_away": "Dayton"}
    chunks = [("/tmp/_n0.mp4", 0.0, 1080.0), ("/tmp/_n1.mp4", 1070.0, 1080.0)]

    async def fake_send(path, prompt, session_id, system_message=None):
        idx = session_id.rsplit("-", 2)[-2]
        if idx == "0":
            return json.dumps([{"time": 100, "type": "goal", "importance": 5},
                               {"time": 300, "type": "shot", "importance": 3}])
        return json.dumps([{"time": 50, "type": "save", "importance": 4}])

    monkeypatch.setattr(P, "_send_video_to_gemini", fake_send)

    async def run():
        client, testdb = _make_db(monkeypatch)
        try:
            await P._markers_from_chunks(chunks, match, "", video_id, user_id, match_id)
            doc = await testdb.analyses.find_one(
                {"video_id": video_id, "analysis_type": "timeline_markers"}, {"_id": 0}
            )
            cov = doc["coverage"]
            assert cov["chunks_total"] == 2
            assert cov["chunks_errored"] == 0
            assert cov["events_per_chunk"] == [2, 1]
            assert cov["covered_from_sec"] == 0.0
            assert cov["covered_to_sec"] == 1070.0 + 1080.0
        finally:
            await testdb.markers.delete_many({"video_id": video_id})
            await testdb.analyses.delete_many({"video_id": video_id})
            client.close()

    run_async(run())


def test_gemini_retry_recovers_transient_failure(monkeypatch):
    video_id = f"i111-vid-{uuid.uuid4().hex[:8]}"
    match = {"id": "m", "team_home": "LFC", "team_away": "Dayton"}
    chunks = [("/tmp/_n0.mp4", 0.0, 1080.0)]
    calls = {"n": 0}

    async def flaky_send(path, prompt, session_id, system_message=None):
        # attempt 0 raises, attempt 1 succeeds
        if session_id.endswith("-0"):
            calls["n"] += 1
            raise RuntimeError("transient 503")
        return json.dumps([{"time": 10, "type": "goal", "importance": 5}])

    monkeypatch.setattr(P, "_send_video_to_gemini", flaky_send)

    async def run():
        client, testdb = _make_db(monkeypatch)
        try:
            count = await P._markers_from_chunks(chunks, match, "", video_id, "u", "m")
            assert count == 1  # recovered via the retry attempt
            doc = await testdb.analyses.find_one(
                {"video_id": video_id, "analysis_type": "timeline_markers"}, {"_id": 0}
            )
            assert doc["coverage"]["chunks_errored"] == 0
        finally:
            await testdb.markers.delete_many({"video_id": video_id})
            await testdb.analyses.delete_many({"video_id": video_id})
            client.close()

    run_async(run())


def test_chunk_fully_failed_counts_as_errored(monkeypatch):
    video_id = f"i111-vid-{uuid.uuid4().hex[:8]}"
    match = {"id": "m", "team_home": "LFC", "team_away": "Dayton"}
    chunks = [("/tmp/_n0.mp4", 0.0, 1080.0), ("/tmp/_n1.mp4", 1080.0, 1080.0)]

    async def partly_dead(path, prompt, session_id, system_message=None):
        idx = session_id.rsplit("-", 2)[-2]
        if idx == "1":
            raise RuntimeError("always down")
        return json.dumps([{"time": 5, "type": "goal", "importance": 5}])

    monkeypatch.setattr(P, "_send_video_to_gemini", partly_dead)

    async def run():
        client, testdb = _make_db(monkeypatch)
        try:
            await P._markers_from_chunks(chunks, match, "", video_id, "u", "m")
            doc = await testdb.analyses.find_one(
                {"video_id": video_id, "analysis_type": "timeline_markers"}, {"_id": 0}
            )
            cov = doc["coverage"]
            assert cov["chunks_errored"] == 1          # chunk 1 gave up
            assert cov["events_per_chunk"] == [1, 0]   # chunk 0 ok, chunk 1 empty
        finally:
            await testdb.markers.delete_many({"video_id": video_id})
            await testdb.analyses.delete_many({"video_id": video_id})
            client.close()

    run_async(run())


# ---------------------------------------------------------------------------
# 5. Frontend wiring guard + deploy flags
# ---------------------------------------------------------------------------

def test_markers_panel_renders_coverage():
    with open("/app/frontend/src/pages/components/MarkersPanel.js") as f:
        src = f.read()
    assert "coverage" in src
    assert 'data-testid="markers-coverage"' in src
    assert "markers-coverage-warning" in src  # failed-segment warning surfaced


def test_video_analysis_passes_coverage():
    with open("/app/frontend/src/pages/VideoAnalysis.js") as f:
        src = f.read()
    assert "markersCoverage" in src
    assert "coverage={markersCoverage}" in src


def test_deploy_advertises_iter111_flags():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert int(re.search(r"iter(\d+)", r.json()["build"]).group(1)) >= 111
            features = set(r.json()["features"])
            assert "markers-480p-audio-coverage" in features
            assert "markers-strict-type-guide" in features
            assert "markers-coverage-telemetry" in features
    run_async(run())
