"""
iter95 — Broaden orphan detection to catch the actual leak sources.

Real production data shows the user's storage was reported as "clean" by
iter93/94 even after many failed uploads. Investigation against our own
preview DB earlier (PRD.md iter93 section) confirmed three orphan paths
that the iter93 endpoint completely missed:

  - chunked_uploads with status="completed" but no live video doc → 10 GB
  - chunked_uploads stuck in_progress / initialized → 10 GB
  - videos that ffmpeg OOM-killed mid-processing (status stays "pending"
    or "processing" instead of moving to "failed")

These three buckets are now first-class citizens of the report:
`abandoned_uploads`, `completed_uploads_without_video`, `stuck_videos`.
"""
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


def _payload():
    s = uuid.uuid4().hex[:10]
    return {"email": f"iter95-{s}@example.com", "password": "Iter95Pass!", "name": f"Iter95 {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


def _stale_iso(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# 1. New buckets are present in the report shape
# ---------------------------------------------------------------------------

def test_report_includes_all_iter95_buckets():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            for k in (
                "dismissed_sessions",
                "abandoned_uploads",
                "completed_uploads_without_video",
                "failed_videos",
                "stuck_videos",
                "deleted_videos",
                "lost_chunks",
            ):
                assert k in body["buckets"], f"bucket {k} missing from report"
                assert k in body["summary"]["by_bucket"]
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. Abandoned in_progress uploads (the iter93 blind spot)
# ---------------------------------------------------------------------------

def test_abandoned_uploads_caught_when_stale():
    """An in_progress chunked_upload that's >6h old and never dismissed is
    the most common production leak. iter93 missed these entirely."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "abandoned.mp4",
                "file_size": 100 * 1024 * 1024, "status": "in_progress",
                "chunk_paths": {"0": "soccer-analysis/abd/0.bin", "1": "soccer-analysis/abd/1.bin"},
                "chunk_backends": {"0": "storage", "1": "storage"},
                "created_at": _stale_iso(hours=10),  # 10h old → stale
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["by_bucket"]["abandoned_uploads"] == 2
            assert body["summary"]["total_orphan_chunks"] == 2
        finally:
            await c.aclose()
    _run_async(run())


def test_abandoned_uploads_skips_fresh_in_progress():
    """A recent in_progress upload (the user is mid-flight) must NOT be
    flagged as abandoned — that would tell support to delete chunks for
    an active session."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "active.mp4",
                "file_size": 100 * 1024 * 1024, "status": "in_progress",
                "chunk_paths": {"0": "soccer-analysis/active/0.bin"},
                "chunk_backends": {"0": "storage"},
                "created_at": datetime.now(timezone.utc).isoformat(),  # fresh
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["by_bucket"]["abandoned_uploads"] == 0, (
                "Fresh in_progress upload must not be flagged as abandoned"
            )
        finally:
            await c.aclose()
    _run_async(run())


def test_abandoned_uploads_skips_dismissed():
    """A dismissed session belongs in `dismissed_sessions`, NOT in
    `abandoned_uploads` — even if it would otherwise qualify."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "dismissed.mp4",
                "file_size": 100 * 1024 * 1024, "status": "in_progress",
                "chunk_paths": {"0": "soccer-analysis/dis/0.bin"},
                "chunk_backends": {"0": "storage"},
                "created_at": _stale_iso(hours=20),
                "dismissed_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["by_bucket"]["abandoned_uploads"] == 0
            assert body["summary"]["by_bucket"]["dismissed_sessions"] == 1
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 3. Completed uploads with no video record (the second iter93 blind spot)
# ---------------------------------------------------------------------------

def test_completed_uploads_without_video_caught():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            ghost_video_id = str(uuid.uuid4())  # never inserted into videos
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "ghost.mp4",
                "file_size": 30 * 1024 * 1024, "status": "completed",
                "video_id": ghost_video_id,
                "chunk_paths": {"0": "soccer-analysis/ghost/0.bin", "1": "soccer-analysis/ghost/1.bin"},
                "chunk_backends": {"0": "storage", "1": "storage"},
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["by_bucket"]["completed_uploads_without_video"] == 2
        finally:
            await c.aclose()
    _run_async(run())


def test_completed_uploads_skipped_when_video_exists():
    """If the completed upload's video record still exists, those chunks
    are NOT orphans — they're powering an active video."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            vid = str(uuid.uuid4())
            await db.videos.insert_one({
                "id": vid, "user_id": uid, "match_id": "m1",
                "original_filename": "live.mp4", "is_chunked": True, "is_deleted": False,
                "total_chunks": 1, "chunk_size": 10 * 1024 * 1024,
                "chunk_paths": {"0": "soccer-analysis/live/0.bin"},
                "chunk_backends": {"0": "storage"},
                "processing_status": "completed",
                "storage_path": "chunked:test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "live.mp4",
                "file_size": 10 * 1024 * 1024, "status": "completed",
                "video_id": vid,
                "chunk_paths": {"0": "soccer-analysis/live/0.bin"},
                "chunk_backends": {"0": "storage"},
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["by_bucket"]["completed_uploads_without_video"] == 0
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 4. Stuck videos (the third iter93 blind spot)
# ---------------------------------------------------------------------------

def test_stuck_videos_caught_when_processing_too_long():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            # A video stuck in "processing" for 4 hours (ffmpeg pod killed)
            await db.videos.insert_one({
                "id": str(uuid.uuid4()), "user_id": uid, "match_id": "m1",
                "original_filename": "stuck.mp4", "is_chunked": True, "is_deleted": False,
                "total_chunks": 3, "chunk_size": 10 * 1024 * 1024,
                "chunk_paths": {
                    "0": "soccer-analysis/stuck/0.bin",
                    "1": "soccer-analysis/stuck/1.bin",
                    "2": "soccer-analysis/stuck/2.bin",
                },
                "chunk_backends": {"0": "storage", "1": "storage", "2": "storage"},
                "processing_status": "processing",
                "storage_path": "chunked:test",
                "created_at": _stale_iso(hours=4),
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["by_bucket"]["stuck_videos"] == 3
        finally:
            await c.aclose()
    _run_async(run())


def test_stuck_videos_skips_fresh_processing():
    """A video that just started processing (<2h ago) is still legitimately
    being worked on — don't flag it as orphan."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await db.videos.insert_one({
                "id": str(uuid.uuid4()), "user_id": uid, "match_id": "m1",
                "original_filename": "fresh.mp4", "is_chunked": True, "is_deleted": False,
                "total_chunks": 1, "chunk_size": 10 * 1024 * 1024,
                "chunk_paths": {"0": "soccer-analysis/fresh/0.bin"},
                "chunk_backends": {"0": "storage"},
                "processing_status": "processing",
                "storage_path": "chunked:test",
                "created_at": _stale_iso(hours=1),  # only 1h
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["by_bucket"]["stuck_videos"] == 0
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 5. mark-orphans persists across the new buckets (uses shared helper)
# ---------------------------------------------------------------------------

def test_mark_orphans_persists_iter95_buckets():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            # Seed one of each new bucket
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "abandoned.mp4",
                "file_size": 10 * 1024 * 1024, "status": "in_progress",
                "chunk_paths": {"0": "soccer-analysis/p-abd/0.bin"},
                "chunk_backends": {"0": "storage"},
                "created_at": _stale_iso(hours=10),
            })
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "ghost.mp4",
                "file_size": 10 * 1024 * 1024, "status": "completed",
                "video_id": str(uuid.uuid4()),
                "chunk_paths": {"0": "soccer-analysis/p-ghost/0.bin"},
                "chunk_backends": {"0": "storage"},
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            await db.videos.insert_one({
                "id": str(uuid.uuid4()), "user_id": uid, "match_id": "m1",
                "original_filename": "stuck.mp4", "is_chunked": True, "is_deleted": False,
                "total_chunks": 1, "chunk_size": 10 * 1024 * 1024,
                "chunk_paths": {"0": "soccer-analysis/p-stuck/0.bin"},
                "chunk_backends": {"0": "storage"},
                "processing_status": "pending",
                "storage_path": "chunked:test",
                "created_at": _stale_iso(hours=5),
            })

            r = await c.post("/api/admin/storage-cleanup/mark-orphans")
            body = r.json()
            assert body["newly_marked"] == 3, f"expected 3 marked, got {body}"

            # Verify each was tagged with the right bucket
            buckets_seen = set()
            async for doc in db.orphan_chunks.find({"user_id": uid}, {"_id": 0, "bucket": 1}):
                buckets_seen.add(doc["bucket"])
            assert "abandoned_uploads" in buckets_seen
            assert "completed_uploads_without_video" in buckets_seen
            assert "stuck_videos" in buckets_seen
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 6. Frontend bucket labels exist for every new key
# ---------------------------------------------------------------------------

def test_frontend_admin_page_labels_iter95_buckets():
    src = open("/app/frontend/src/pages/AdminStorageCleanup.js").read()
    for key in ("abandoned_uploads", "completed_uploads_without_video", "stuck_videos"):
        assert key in src, f"frontend BUCKET_LABELS missing key '{key}'"
