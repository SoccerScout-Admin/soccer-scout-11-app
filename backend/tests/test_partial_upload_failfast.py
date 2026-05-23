"""
Tests for iter70: partial-upload fail-fast guard.

Real production bug 2026-05-16 (video 48823490, 980/991 chunks, 9.67 GB) sat
at 0% forever because:
  - run_auto_processing couldn't detect incomplete uploads → ffmpeg silently
    produced a broken sample or got OOM-killed
  - resume_interrupted_processing on every pod restart re-queued it, hitting
    the same wall

iter70 introduces two guards:
  - services/processing.py::_check_chunk_integrity + fail-fast in
    run_auto_processing — marks failed with "Upload incomplete (...)" error
    instead of trying ffmpeg on a partial file
  - server.py::resume_interrupted_processing skips partial-integrity videos
    on restart, marking them failed once instead of re-queueing forever

This file mixes pure unit tests (which run in-process) with integration tests
that touch Motor's shared `db` (which run in a subprocess to avoid polluting
the shared event loop binding for sibling test files).
"""
import os
import sys
import subprocess
import textwrap
import asyncio
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Pure unit tests on _check_chunk_integrity — no shared-state side effects
# ---------------------------------------------------------------------------

def _run_local(coro):
    """Lightweight in-process runner for pure helpers. Reuses the default loop
    so we don't perturb sibling test files."""
    return asyncio.get_event_loop().run_until_complete(coro)


def test_check_chunk_integrity_full():
    """Non-chunked videos always report 'full'."""
    from services.processing import _check_chunk_integrity
    integrity, _available, _total = _run_local(
        _check_chunk_integrity({"is_chunked": False})
    )
    assert integrity == "full"


def test_check_chunk_integrity_partial():
    """Chunked video with some chunks missing reports 'partial'."""
    from services.processing import _check_chunk_integrity
    video = {
        "is_chunked": True,
        "total_chunks": 10,
        "chunk_paths": {str(i): f"/tmp/fake-{i}.mp4" for i in range(7)},
        "chunk_backends": {str(i): "storage" for i in range(7)},
    }
    integrity, available, total = _run_local(_check_chunk_integrity(video))
    assert integrity == "partial"
    assert available == 7
    assert total == 10


def test_check_chunk_integrity_unavailable():
    """All chunk paths missing → unavailable."""
    from services.processing import _check_chunk_integrity
    integrity, available, total = _run_local(_check_chunk_integrity({
        "is_chunked": True, "total_chunks": 5, "chunk_paths": {}, "chunk_backends": {},
    }))
    assert integrity == "unavailable"
    assert available == 0
    assert total == 5


# ---------------------------------------------------------------------------
# Integration tests — isolated via subprocess so the fresh-loop dance we need
# for Motor cleanup doesn't break sibling test files that share the global
# `db` import (test_processing_alerts in particular).
# ---------------------------------------------------------------------------

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_integration_script(script: str) -> dict:
    """Run a stand-alone script in a clean subprocess and return its JSON
    stdout payload. Each script is responsible for printing a JSON line of
    `{"ok": bool, "result": {...}}` so we can assert without parsing stderr.
    """
    full = textwrap.dedent(f"""
        import os, sys, asyncio, json, uuid
        sys.path.insert(0, {_BACKEND_DIR!r})
        os.chdir({_BACKEND_DIR!r})
        from dotenv import load_dotenv
        load_dotenv()

        async def _main():
{textwrap.indent(textwrap.dedent(script), '            ')}

        try:
            result = asyncio.run(_main())
            print("__OK__" + json.dumps(result))
        except Exception as e:
            print("__ERR__" + repr(e))
            raise
    """)
    proc = subprocess.run(
        [sys.executable, "-c", full],
        capture_output=True, text=True, timeout=60, cwd=_BACKEND_DIR,
    )
    assert proc.returncode == 0, f"Subprocess failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    line = next((l for l in proc.stdout.splitlines() if l.startswith("__OK__")), None)
    assert line, f"No __OK__ marker in subprocess output:\n{proc.stdout}\n{proc.stderr}"
    import json as _json
    return _json.loads(line[len("__OK__"):])


def test_run_auto_processing_fails_fast_on_incomplete():
    """Seed an incomplete chunked video and call run_auto_processing → must
    mark failed with the 'Upload incomplete' error WITHOUT calling ffmpeg."""
    script = """
        from motor.motor_asyncio import AsyncIOMotorClient
        from services.processing import run_auto_processing

        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        vid = "sentinel-vid-" + uuid.uuid4().hex[:8]
        uid = "sentinel-uid-" + uuid.uuid4().hex[:8]
        mid = "sentinel-mid-" + uuid.uuid4().hex[:8]

        await db.videos.insert_one({
            "id": vid, "user_id": uid, "match_id": mid,
            "is_chunked": True, "total_chunks": 991,
            "chunk_paths": {str(i): f"/var/video_chunks/{vid}/{i}.bin" for i in range(980)},
            "chunk_backends": {str(i): "storage" for i in range(980)},
            "processing_status": "queued", "processing_progress": 0,
            "file_size_bytes": 9_670_000_000,
        })
        await db.matches.insert_one({
            "id": mid, "user_id": uid, "team_home": "X", "team_away": "Y", "date": "2026-05-16",
        })

        try:
            await run_auto_processing(vid, uid)
            v = await db.videos.find_one({"id": vid}, {"_id": 0, "processing_status": 1, "processing_error": 1})
            return {"status": v.get("processing_status"), "error": v.get("processing_error")}
        finally:
            await db.videos.delete_many({"id": vid})
            await db.matches.delete_many({"id": mid})
            await db.processing_events.delete_many({"video_id": vid})
            client.close()
    """
    result = _run_integration_script(script)
    assert result["status"] == "failed"
    assert "Upload incomplete" in (result["error"] or "")
    assert "980 of 991" in result["error"]
    assert "Re-upload required" in result["error"]


def test_resume_interrupted_skips_partial():
    """Resume must mark partial videos failed without re-queueing them."""
    script = """
        from motor.motor_asyncio import AsyncIOMotorClient
        import server as srv
        from server import resume_interrupted_processing

        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        vid = "sentinel-resume-" + uuid.uuid4().hex[:8]
        uid = "sentinel-uid-" + uuid.uuid4().hex[:8]

        await db.videos.insert_one({
            "id": vid, "user_id": uid, "match_id": None,
            "is_chunked": True, "total_chunks": 100,
            "chunk_paths": {str(i): "/var/video_chunks/fake.bin" for i in range(85)},
            "chunk_backends": {str(i): "storage" for i in range(85)},
            "processing_status": "queued", "processing_progress": 0,
        })

        orig_sleep = srv.asyncio.sleep
        srv.asyncio.sleep = lambda *a, **kw: orig_sleep(0)
        try:
            await resume_interrupted_processing()
        finally:
            srv.asyncio.sleep = orig_sleep

        try:
            v = await db.videos.find_one({"id": vid}, {"_id": 0, "processing_status": 1, "processing_error": 1})
            return {"status": v.get("processing_status"), "error": v.get("processing_error")}
        finally:
            await db.videos.delete_many({"id": vid})
            client.close()
    """
    result = _run_integration_script(script)
    assert result["status"] == "failed"
    assert "Upload incomplete" in (result["error"] or "")
    assert "85 of 100" in result["error"]
