"""iter110 — Full-match coverage for the PROSE/STAT analyses.

Root-cause fix (production 2026-06-04): tactical / player_performance /
highlights / possession_stats sent the ENTIRE 1h43m match as a SINGLE Gemini
call (~1.6M video tokens) → Gemini rejected it with
`400 INVALID_ARGUMENT "Request contains an invalid argument."`.

The fix reuses iter109's full-coverage chunks (25-min, sub-limit) and runs each
prose prompt per chunk (MAP) then synthesizes one cohesive report with a cheap
text-only call (REDUCE). possession_stats is reduced by deterministic numeric
aggregation instead of an LLM call.

These tests cover the deterministic pieces (possession aggregation, segment
note, single-vs-multi-chunk reduce) plus an end-to-end orchestration test with
Gemini mocked against real Mongo, and the deploy flags.
"""
import re
import json
import uuid
import httpx
import pytest

from conftest import BASE_URL, run_async
from services import processing as P


# ---------------------------------------------------------------------------
# 1. Possession numeric aggregation (deterministic reduce, no LLM)
# ---------------------------------------------------------------------------

def _poss(home, away, hp, ap, hs, as_, summary=None):
    d = {
        "team_home_possession_pct": home,
        "team_away_possession_pct": away,
        "team_home_total_passes_estimate": hp,
        "team_away_total_passes_estimate": ap,
        "team_home_longest_pass_string": hs,
        "team_away_longest_pass_string": as_,
    }
    if summary:
        d["summary"] = summary
    return json.dumps(d)


def test_aggregate_possession_combines_segments():
    match = {"team_home": "LFC", "team_away": "Dayton"}
    # two equal-length segments → possession averaged; passes summed; strings maxed
    partials = [
        (0.0, 1500.0, _poss(60, 40, 200, 120, 8, 5, "LFC on top")),
        (1500.0, 1500.0, _poss(40, 60, 150, 180, 6, 11)),
    ]
    out = json.loads(P._aggregate_possession(partials, match))
    assert out["team_home_possession_pct"] + out["team_away_possession_pct"] == 100
    assert out["team_home_possession_pct"] == 50  # (60+40)/2
    assert out["team_home_total_passes_estimate"] == 350  # 200+150 summed
    assert out["team_away_total_passes_estimate"] == 300  # 120+180 summed
    assert out["team_home_longest_pass_string"] == 8       # max(8,6)
    assert out["team_away_longest_pass_string"] == 11       # max(5,11)
    assert out["summary"] == "LFC on top"


def test_aggregate_possession_duration_weighted():
    match = {"team_home": "LFC", "team_away": "Dayton"}
    # a long 80% segment + a short 20% segment — weighted toward the long one
    partials = [
        (0.0, 1800.0, _poss(70, 30, 0, 0, 0, 0)),
        (1800.0, 200.0, _poss(10, 90, 0, 0, 0, 0)),
    ]
    out = json.loads(P._aggregate_possession(partials, match))
    # weighted home = (70*1800 + 10*200)/2000 = 64 → should be well above 50
    assert out["team_home_possession_pct"] >= 60


def test_aggregate_possession_strips_fences_and_tolerates_garbage():
    match = {"team_home": "LFC", "team_away": "Dayton"}
    fenced = "```json\n" + _poss(55, 45, 100, 90, 7, 6) + "\n```"
    partials = [
        (0.0, 1500.0, fenced),
        (1500.0, 1500.0, "totally not json"),  # ignored, not crash
    ]
    out = json.loads(P._aggregate_possession(partials, match))
    assert out["team_home_possession_pct"] == 55
    assert out["team_home_total_passes_estimate"] == 100


def test_aggregate_possession_all_unparseable_returns_first_raw():
    match = {"team_home": "LFC", "team_away": "Dayton"}
    partials = [(0.0, 1500.0, "garbage A"), (1500.0, 1500.0, "garbage B")]
    out = P._aggregate_possession(partials, match)
    assert out == "garbage A"  # frontend card can attempt its own parse


# ---------------------------------------------------------------------------
# 2. Segment note preamble
# ---------------------------------------------------------------------------

def test_segment_note_has_index_and_match_time_range():
    note = P._segment_note("tactical", 2, 5, 3000.0, 1500.0)
    assert "segment 3 of 5" in note  # idx is 0-based → +1
    assert "50:00" in note and "75:00" in note
    # prose types do NOT get the possession-only directive
    assert "scale up to the full match" not in note


def test_segment_note_possession_gets_no_scale_directive():
    note = P._segment_note("possession_stats", 0, 3, 0.0, 1500.0)
    assert "THIS SEGMENT ONLY" in note
    assert "Do NOT" in note and "scale up" in note


# ---------------------------------------------------------------------------
# 3. run_chunked_text_analysis orchestration (Gemini mocked, real Mongo)
# ---------------------------------------------------------------------------

def _make_db(monkeypatch):
    import os as _os
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(_os.environ["MONGO_URL"])
    testdb = client[_os.environ["DB_NAME"]]
    monkeypatch.setattr(P, "db", testdb)
    return client, testdb


def test_prose_multi_chunk_maps_then_reduces(monkeypatch):
    video_id = f"i110-vid-{uuid.uuid4().hex[:8]}"
    match_id = f"i110-match-{uuid.uuid4().hex[:8]}"
    user_id = f"i110-user-{uuid.uuid4().hex[:8]}"
    match = {"id": match_id, "team_home": "LFC", "team_away": "Dayton"}
    chunks = [("/tmp/_nope0.mp4", 0.0, 1500.0), ("/tmp/_nope1.mp4", 1490.0, 1510.0)]

    sent_video = []
    sent_text = []

    async def fake_video(path, prompt, session_id, system_message=None):
        sent_video.append(session_id)
        return f"segment notes for {session_id}"

    async def fake_text(prompt, session_id, system_message="x"):
        sent_text.append((session_id, prompt))
        return "FINAL COHESIVE TACTICAL REPORT"

    monkeypatch.setattr(P, "_send_video_to_gemini", fake_video)
    monkeypatch.setattr(P, "_send_text_to_gemini", fake_text)

    async def run():
        client, testdb = _make_db(monkeypatch)
        try:
            content = await P.run_chunked_text_analysis(
                chunks, match, "tactical", "BASE PROMPT",
                video_id, user_id, match_id,
            )
            # mapped over BOTH chunks
            assert len(sent_video) == 2
            # reduced exactly once (multi-chunk)
            assert len(sent_text) == 1
            # the reduce prompt carried BOTH segment notes
            assert "segment notes for tactical-%s-0" % video_id in sent_text[0][1]
            assert "segment notes for tactical-%s-1" % video_id in sent_text[0][1]
            assert content == "FINAL COHESIVE TACTICAL REPORT"
            # stored exactly one completed doc
            docs = await testdb.analyses.find(
                {"video_id": video_id, "analysis_type": "tactical"}, {"_id": 0}
            ).to_list(10)
            assert len(docs) == 1
            assert docs[0]["status"] == "completed"
            assert docs[0]["content"] == "FINAL COHESIVE TACTICAL REPORT"
        finally:
            await testdb.analyses.delete_many({"video_id": video_id})
            client.close()

    run_async(run())


def test_prose_single_chunk_skips_reduce(monkeypatch):
    video_id = f"i110-vid-{uuid.uuid4().hex[:8]}"
    match = {"id": "m", "team_home": "LFC", "team_away": "Dayton"}
    chunks = [("/tmp/_nope0.mp4", 0.0, 600.0)]  # short match → 1 chunk

    async def fake_video(path, prompt, session_id, system_message=None):
        return "ONLY SEGMENT ANALYSIS"

    reduce_called = {"n": 0}

    async def fake_text(prompt, session_id, system_message="x"):
        reduce_called["n"] += 1
        return "should not be used"

    monkeypatch.setattr(P, "_send_video_to_gemini", fake_video)
    monkeypatch.setattr(P, "_send_text_to_gemini", fake_text)

    async def run():
        client, testdb = _make_db(monkeypatch)
        try:
            content = await P.run_chunked_text_analysis(
                chunks, match, "highlights", "BASE", video_id, "u", "m",
            )
            assert reduce_called["n"] == 0  # no reduce call for single chunk
            assert content == "ONLY SEGMENT ANALYSIS"
        finally:
            await testdb.analyses.delete_many({"video_id": video_id})
            client.close()

    run_async(run())


def test_possession_uses_numeric_aggregate_not_llm(monkeypatch):
    video_id = f"i110-vid-{uuid.uuid4().hex[:8]}"
    match = {"id": "m", "team_home": "LFC", "team_away": "Dayton"}
    chunks = [("/tmp/_nope0.mp4", 0.0, 1500.0), ("/tmp/_nope1.mp4", 1500.0, 1500.0)]

    async def fake_video(path, prompt, session_id, system_message=None):
        # session_id ends with -0 / -1
        if session_id.endswith("-0"):
            return _poss(60, 40, 200, 100, 9, 4)
        return _poss(40, 60, 150, 200, 5, 10)

    reduce_called = {"n": 0}

    async def fake_text(prompt, session_id, system_message="x"):
        reduce_called["n"] += 1
        return "nope"

    monkeypatch.setattr(P, "_send_video_to_gemini", fake_video)
    monkeypatch.setattr(P, "_send_text_to_gemini", fake_text)

    async def run():
        client, testdb = _make_db(monkeypatch)
        try:
            content = await P.run_chunked_text_analysis(
                chunks, match, "possession_stats", "BASE", video_id, "u", "m",
            )
            assert reduce_called["n"] == 0  # possession never calls the LLM reduce
            data = json.loads(content)
            assert data["team_home_possession_pct"] == 50
            assert data["team_home_total_passes_estimate"] == 350
            assert data["team_away_longest_pass_string"] == 10
            docs = await testdb.analyses.find(
                {"video_id": video_id, "analysis_type": "possession_stats"}, {"_id": 0}
            ).to_list(10)
            assert len(docs) == 1 and docs[0]["status"] == "completed"
        finally:
            await testdb.analyses.delete_many({"video_id": video_id})
            client.close()

    run_async(run())


def test_all_chunks_fail_raises(monkeypatch):
    match = {"id": "m", "team_home": "LFC", "team_away": "Dayton"}
    chunks = [("/tmp/_nope0.mp4", 0.0, 1500.0)]

    async def boom(path, prompt, session_id, system_message=None):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(P, "_send_video_to_gemini", boom)

    async def run():
        client, testdb = _make_db(monkeypatch)
        try:
            with pytest.raises(Exception):
                await P.run_chunked_text_analysis(
                    chunks, match, "tactical", "BASE",
                    f"i110-{uuid.uuid4().hex[:6]}", "u", "m",
                )
        finally:
            client.close()

    run_async(run())


def test_prior_analysis_replaced_not_duplicated(monkeypatch):
    """A second run of the same analysis_type must REPLACE the prior doc
    (delete-prior + insert), not pile up duplicate rows."""
    video_id = f"i110-vid-{uuid.uuid4().hex[:8]}"
    match = {"id": "m", "team_home": "LFC", "team_away": "Dayton"}
    chunks = [("/tmp/_nope0.mp4", 0.0, 600.0)]

    counter = {"n": 0}

    async def fake_video(path, prompt, session_id, system_message=None):
        counter["n"] += 1
        return f"run {counter['n']}"

    monkeypatch.setattr(P, "_send_video_to_gemini", fake_video)

    async def run():
        client, testdb = _make_db(monkeypatch)
        try:
            await P.run_chunked_text_analysis(chunks, match, "tactical", "B", video_id, "u", "m")
            await P.run_chunked_text_analysis(chunks, match, "tactical", "B", video_id, "u", "m")
            docs = await testdb.analyses.find(
                {"video_id": video_id, "analysis_type": "tactical"}, {"_id": 0}
            ).to_list(10)
            assert len(docs) == 1  # replaced, not duplicated
            assert docs[0]["content"] == "run 2"
        finally:
            await testdb.analyses.delete_many({"video_id": video_id})
            client.close()

    run_async(run())


# ---------------------------------------------------------------------------
# 4. Source-code wiring guards (auto-processing + manual share chunks)
# ---------------------------------------------------------------------------

def test_auto_processing_uses_chunked_text_and_shared_chunks():
    import inspect
    src = inspect.getsource(P.run_auto_processing)
    assert "prepare_full_coverage_chunks" in src  # builds chunks once
    assert "run_chunked_text_analysis" in src      # prose path
    assert "_markers_from_chunks" in src           # markers reuse shared chunks
    assert "_cleanup_chunks" in src                # single cleanup
    # the old full-match single-sample path is no longer CALLED in auto-processing
    assert "await prepare_video_sample(" not in src


# ---------------------------------------------------------------------------
# 5. Deploy flags + build version
# ---------------------------------------------------------------------------

def test_build_version_is_iter110_or_newer():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            m = re.search(r"iter(\d+)", r.json()["build"])
            assert m and int(m.group(1)) >= 110
    run_async(run())


def test_deploy_advertises_iter110_flags():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            features = set(r.json()["features"])
            assert "full-match-coverage-prose-analyses" in features
            assert "chunked-text-analysis-map-reduce" in features
            assert "possession-stats-numeric-aggregate" in features
    run_async(run())
