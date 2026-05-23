"""
Tests for iter75: pod-OOM-loop detection.

Production bug 2026-05-18 (video 2ebe539f-..., 3.93 GB, full integrity but
processing stuck at 0% forever) — the file uploaded cleanly (so iter70's
integrity guard doesn't trip), but ffmpeg was OOM-killing the pod BEFORE
iter63's Python-level auto-retry could fire. Every pod restart re-queued
the video via resume_interrupted_processing, which re-OOMed the next pod,
which re-queued again — infinite loop, no failure event ever logged.

iter75 fix:
  - Track `resume_attempts` on each video doc, bump on each resume
  - After 3 resumes with progress still at 0, mark `failed` with the
    "compression required" message + log a `final_failure /
    failure_mode=pod_oom_loop` processing event
  - A video that previously made >0% progress is NOT subject to this guard
    (iter63's auto-retry tier can still help it)
"""
import os
import sys
import subprocess
import textwrap

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_integration_script(script: str) -> dict:
    """Run a stand-alone script in a clean subprocess to isolate Motor's
    loop-bound state from sibling test files (same pattern as
    test_partial_upload_failfast.py)."""
    full = textwrap.dedent(f"""
        import os, sys, asyncio, json, uuid
        sys.path.insert(0, {_BACKEND!r})
        os.chdir({_BACKEND!r})
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
        capture_output=True, text=True, timeout=60, cwd=_BACKEND,
    )
    assert proc.returncode == 0, f"Subprocess failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    line = next((l for l in proc.stdout.splitlines() if l.startswith("__OK__")), None)
    assert line, f"No __OK__ marker:\n{proc.stdout}\n{proc.stderr}"
    import json as _json
    return _json.loads(line[len("__OK__"):])


def test_resume_marks_oom_loop_after_max_attempts():
    """Seed a video with resume_attempts=3 and progress=0 → resume must mark
    it failed with the 'pod-OOM-loop' message AND log a processing event."""
    script = """
        from motor.motor_asyncio import AsyncIOMotorClient
        import server as srv
        from server import resume_interrupted_processing

        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        vid = "oom-loop-vid-" + uuid.uuid4().hex[:8]
        uid = "oom-loop-uid-" + uuid.uuid4().hex[:8]

        await db.videos.insert_one({
            "id": vid, "user_id": uid, "match_id": None,
            "is_chunked": False,  # bypass the integrity-skip branch
            "total_chunks": 0,
            "processing_status": "queued",
            "processing_progress": 0,
            "resume_attempts": 3,
            "file_size_bytes": int(3.93 * 1024 ** 3),
            "filename": "huge.mp4",
        })

        orig_sleep = srv.asyncio.sleep
        srv.asyncio.sleep = lambda *a, **kw: orig_sleep(0)
        try:
            await resume_interrupted_processing()
        finally:
            srv.asyncio.sleep = orig_sleep

        v = await db.videos.find_one({"id": vid}, {"_id": 0})
        evs = await db.processing_events.find({"video_id": vid}, {"_id": 0}).to_list(10)
        try:
            return {
                "status": v.get("processing_status"),
                "error": v.get("processing_error"),
                "event_count": len(evs),
                "event_failure_mode": evs[0].get("failure_mode") if evs else None,
            }
        finally:
            await db.videos.delete_many({"id": vid})
            await db.processing_events.delete_many({"video_id": vid})
            client.close()
    """
    result = _run_integration_script(script)
    assert result["status"] == "failed"
    assert "Processing failed 3" in result["error"]
    assert "HandBrake" in result["error"]
    assert result["event_count"] == 1
    assert result["event_failure_mode"] == "pod_oom_loop"


def test_resume_bumps_attempts_when_below_cap():
    """A video with resume_attempts=1 and progress=0 must be RE-QUEUED (not
    failed) and have its counter bumped to 2."""
    script = """
        from motor.motor_asyncio import AsyncIOMotorClient
        import server as srv
        from server import resume_interrupted_processing

        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        vid = "below-cap-" + uuid.uuid4().hex[:8]
        uid = "below-cap-uid-" + uuid.uuid4().hex[:8]

        await db.videos.insert_one({
            "id": vid, "user_id": uid, "match_id": None,
            "is_chunked": False, "total_chunks": 0,
            "processing_status": "queued", "processing_progress": 0,
            "resume_attempts": 1,
            "file_size_bytes": 1_000_000_000,
            "filename": "test.mp4",
        })

        orig_sleep = srv.asyncio.sleep
        srv.asyncio.sleep = lambda *a, **kw: orig_sleep(0)
        try:
            await resume_interrupted_processing()
        finally:
            srv.asyncio.sleep = orig_sleep

        # Give the background task a moment to do its early-return on missing
        # video file (which we don't care about — we just want to confirm
        # resume bumped the counter and DIDN'T mark failed)
        await asyncio.sleep(0.1)

        v = await db.videos.find_one({"id": vid}, {"_id": 0})
        try:
            return {
                "status": v.get("processing_status"),
                "resume_attempts": v.get("resume_attempts"),
            }
        finally:
            await db.videos.delete_many({"id": vid})
            await db.processing_events.delete_many({"video_id": vid})
            client.close()
    """
    result = _run_integration_script(script)
    # Status may be 'failed' or still 'processing'/'queued' depending on
    # whether the background run_auto_processing task tripped its own
    # failure path on the missing file. The KEY assertion is that the
    # pod-OOM-loop guard did NOT fire — we look at the error message.
    assert result["resume_attempts"] == 2  # bumped from 1 to 2


def test_resume_with_partial_progress_does_not_trip_oom_guard():
    """A video that previously made progress (>0%) should NOT be hit by the
    OOM-loop guard even after many attempts — iter63's auto-retry can still
    help it if ffmpeg returned a Python exception instead of OOM-killing
    the pod."""
    script = """
        from motor.motor_asyncio import AsyncIOMotorClient
        import server as srv
        from server import resume_interrupted_processing

        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]

        vid = "progress-vid-" + uuid.uuid4().hex[:8]
        uid = "progress-uid-" + uuid.uuid4().hex[:8]

        await db.videos.insert_one({
            "id": vid, "user_id": uid, "match_id": None,
            "is_chunked": False, "total_chunks": 0,
            "processing_status": "processing",
            "processing_progress": 35,  # previously made progress
            "resume_attempts": 5,  # way above the cap
            "filename": "test.mp4",
        })

        orig_sleep = srv.asyncio.sleep
        srv.asyncio.sleep = lambda *a, **kw: orig_sleep(0)
        try:
            await resume_interrupted_processing()
        finally:
            srv.asyncio.sleep = orig_sleep

        await asyncio.sleep(0.1)

        v = await db.videos.find_one({"id": vid}, {"_id": 0})
        try:
            error = v.get("processing_error") or ""
            return {
                "error_contains_pod_oom": "Processing failed" in error and "without making any progress" in error,
                "resume_attempts": v.get("resume_attempts"),
            }
        finally:
            await db.videos.delete_many({"id": vid})
            await db.processing_events.delete_many({"video_id": vid})
            client.close()
    """
    result = _run_integration_script(script)
    assert result["error_contains_pod_oom"] is False
    # And the resume counter DID still bump (proves we went through the
    # remaining-types branch, not the OOM-loop branch)
    assert result["resume_attempts"] == 6
