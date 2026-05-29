"""
iter106 — Orphan path dedup + better chunk-size estimation.

Real production issue 2026-05-28: Emergent Support says the user's object
storage quota is 5 GB but our iter95 collector reported ~19 GB of orphans.
Support asked: "From where you checked that chunking size 23 GB and it
store in on our object storage. Because our object storage have only 5 GB
space."

Two bugs in the iter95 collector:

  1. The same `path` could appear in multiple buckets — a chunked_upload
     that finalized into a video, where both `chunked_uploads.chunk_paths`
     AND `videos.chunk_paths` reference the same physical chunk. We counted
     each occurrence as a separate orphan.

  2. Default 10 MB chunk_size estimate inflated legacy chunks that didn't
     have `chunk_sizes` recorded (uploaded pre-iter80 when we started
     persisting that field). Real chunks at the tail end of a file are
     often 1-3 MB, not 10 MB.

Fix:
  • Global path dedup ledger (`seen_paths` set). First bucket the path
    appears in claims it; subsequent buckets skip.
  • Three-tier size estimation: chunk_sizes[idx] → file_size_bytes /
    total_chunks → 10 MB default.

Also ships: "Download manifest (JSON)" button on the admin UI so the user
can attach the audit directly to Support's ticket reply per their request.
"""
import os
import sys
import uuid
from datetime import datetime, timezone

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


def _payload():
    s = uuid.uuid4().hex[:10]
    return {"email": f"iter106-{s}@example.com", "password": "Iter106Pass!", "name": f"Iter106 {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


# ---------------------------------------------------------------------------
# 1. Path dedup across buckets
# ---------------------------------------------------------------------------

def test_same_path_in_two_buckets_counted_once():
    """A chunked_upload that's dismissed AND its derived video that failed
    BOTH carry the same chunk_paths. iter106 must count each path ONCE."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            shared_paths = {
                "0": "soccer-analysis/iter106-dup/0.bin",
                "1": "soccer-analysis/iter106-dup/1.bin",
            }
            shared_backends = {"0": "storage", "1": "storage"}
            shared_sizes = {"0": 5 * 1024 * 1024, "1": 5 * 1024 * 1024}  # 5 MB each

            # Both reference the same paths
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "x.mp4",
                "file_size_bytes": 10 * 1024 * 1024, "total_chunks": 2,
                "status": "in_progress",
                "chunk_paths": dict(shared_paths),
                "chunk_backends": dict(shared_backends),
                "chunk_sizes": dict(shared_sizes),
                "dismissed_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            await db.videos.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1",
                "original_filename": "x.mp4",
                "is_chunked": True, "is_deleted": False,
                "total_chunks": 2,
                "file_size_bytes": 10 * 1024 * 1024,
                "chunk_paths": dict(shared_paths),
                "chunk_backends": dict(shared_backends),
                "chunk_sizes": dict(shared_sizes),
                "processing_status": "failed",
                "storage_path": "chunked:test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            # iter106: 2 unique paths, NOT 4 (which would be 2 in dismissed + 2 in failed)
            assert body["summary"]["total_orphan_chunks"] == 2, (
                f"expected 2 deduped paths, got {body['summary']['total_orphan_chunks']}"
            )
            # First-bucket-wins ordering: dismissed_sessions claims them
            assert body["summary"]["by_bucket"]["dismissed_sessions"] == 2
            assert body["summary"]["by_bucket"]["failed_videos"] == 0
        finally:
            await c.aclose()
    _run_async(run())


def test_dedup_flag_in_report_summary():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.get("/api/admin/storage-cleanup/report")
            summary = r.json()["summary"]
            assert summary.get("deduplicated_by_path") is True
            assert "size_estimation_method" in summary
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. Chunk-size estimation tiers
# ---------------------------------------------------------------------------

def test_size_estimate_uses_recorded_chunk_sizes_first():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await db.videos.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1",
                "original_filename": "small.mp4",
                "is_chunked": True, "is_deleted": False,
                "total_chunks": 1,
                "chunk_paths": {"0": "soccer-analysis/iter106-sz/0.bin"},
                "chunk_backends": {"0": "storage"},
                "chunk_sizes": {"0": 2 * 1024 * 1024},  # 2 MB recorded
                "processing_status": "failed",
                "storage_path": "chunked:test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["total_estimated_bytes"] == 2 * 1024 * 1024, (
                f"expected 2 MB from chunk_sizes, got {body['summary']['total_estimated_bytes']}"
            )
        finally:
            await c.aclose()
    _run_async(run())


def test_size_estimate_falls_back_to_file_size_over_total_chunks():
    """When chunk_sizes isn't recorded, use file_size_bytes / total_chunks
    instead of the 10 MB default — much closer to truth for legacy uploads."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await db.videos.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1",
                "original_filename": "legacy.mp4",
                "is_chunked": True, "is_deleted": False,
                "total_chunks": 4,
                "file_size_bytes": 8 * 1024 * 1024,  # 4 chunks averaging 2 MB each
                "chunk_paths": {
                    "0": "soccer-analysis/iter106-legacy/0.bin",
                    "1": "soccer-analysis/iter106-legacy/1.bin",
                    "2": "soccer-analysis/iter106-legacy/2.bin",
                    "3": "soccer-analysis/iter106-legacy/3.bin",
                },
                "chunk_backends": {"0": "storage", "1": "storage", "2": "storage", "3": "storage"},
                # No chunk_sizes recorded — pre-iter80 legacy doc
                "processing_status": "failed",
                "storage_path": "chunked:test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            # Each chunk should be estimated at 2 MB (file_size / total_chunks)
            assert body["summary"]["total_orphan_chunks"] == 4
            expected = 4 * (8 * 1024 * 1024 // 4)
            assert body["summary"]["total_estimated_bytes"] == expected, (
                f"expected {expected} bytes via file_size/total_chunks, "
                f"got {body['summary']['total_estimated_bytes']}"
            )
        finally:
            await c.aclose()
    _run_async(run())


def test_size_estimate_falls_back_to_10mb_when_nothing_recorded():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await db.videos.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1",
                "original_filename": "noinfo.mp4",
                "is_chunked": True, "is_deleted": False,
                "chunk_paths": {"0": "soccer-analysis/iter106-noinfo/0.bin"},
                "chunk_backends": {"0": "storage"},
                # No chunk_sizes, no file_size_bytes, no total_chunks
                "processing_status": "failed",
                "storage_path": "chunked:test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["total_estimated_bytes"] == 10 * 1024 * 1024
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 3. Bucket priority — first claim wins
# ---------------------------------------------------------------------------

def test_dismissed_takes_priority_over_failed_for_shared_paths():
    """When the same path appears in a dismissed session AND a failed video,
    the dismissed bucket claims it (it's iterated first). Predictable
    ordering matters because counts/bytes per bucket depend on it."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            path = "soccer-analysis/iter106-priority/0.bin"
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "x.mp4",
                "file_size_bytes": 5 * 1024 * 1024, "total_chunks": 1,
                "status": "in_progress",
                "chunk_paths": {"0": path},
                "chunk_backends": {"0": "storage"},
                "chunk_sizes": {"0": 5 * 1024 * 1024},
                "dismissed_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            await db.videos.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1",
                "original_filename": "x.mp4",
                "is_chunked": True, "is_deleted": False,
                "total_chunks": 1,
                "file_size_bytes": 5 * 1024 * 1024,
                "chunk_paths": {"0": path},
                "chunk_backends": {"0": "storage"},
                "chunk_sizes": {"0": 5 * 1024 * 1024},
                "processing_status": "failed",
                "storage_path": "chunked:test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["by_bucket"]["dismissed_sessions"] == 1
            assert body["summary"]["by_bucket"]["failed_videos"] == 0
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 4. mark-orphans uses the same deduped path set
# ---------------------------------------------------------------------------

def test_mark_orphans_dedupes_paths_across_buckets():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            path = "soccer-analysis/iter106-mark/0.bin"
            # Same path in both dismissed AND failed
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "x.mp4",
                "file_size_bytes": 5 * 1024 * 1024, "total_chunks": 1,
                "status": "in_progress",
                "chunk_paths": {"0": path},
                "chunk_backends": {"0": "storage"},
                "chunk_sizes": {"0": 5 * 1024 * 1024},
                "dismissed_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            await db.videos.insert_one({
                "id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1",
                "original_filename": "x.mp4",
                "is_chunked": True, "is_deleted": False,
                "total_chunks": 1,
                "file_size_bytes": 5 * 1024 * 1024,
                "chunk_paths": {"0": path},
                "chunk_backends": {"0": "storage"},
                "chunk_sizes": {"0": 5 * 1024 * 1024},
                "processing_status": "failed",
                "storage_path": "chunked:test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.post("/api/admin/storage-cleanup/mark-orphans")
            body = r.json()
            # 1 unique path, not 2
            assert body["newly_marked"] == 1, (
                f"expected 1 unique path after dedup, got {body}"
            )
            # And the orphan_chunks ledger has exactly one row
            count = await db.orphan_chunks.count_documents({"user_id": uid, "path": path})
            assert count == 1
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 5. Frontend download-manifest button
# ---------------------------------------------------------------------------

def test_frontend_has_download_manifest_button():
    src = open("/app/frontend/src/pages/AdminStorageCleanup.js").read()
    assert 'data-testid="download-manifest-btn"' in src
    assert "handleDownloadManifest" in src
    # Generates a JSON Blob and triggers download
    assert "application/json" in src
    assert "soccer-scout-orphan-manifest-" in src


# ---------------------------------------------------------------------------
# 6. Deploy endpoint advertises iter106 features
# ---------------------------------------------------------------------------

def test_deploy_endpoint_advertises_iter106_features():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            features = set(r.json()["features"])
            assert "orphan-report-global-path-dedup" in features
            assert "chunk-size-estimate-via-file-size-divided-by-total-chunks" in features
            assert "download-manifest-json-button" in features
    _run_async(run())
