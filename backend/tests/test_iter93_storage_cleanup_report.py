"""
iter93 — Storage Cleanup Report.

After Emergent Support replied "your account hit its object-storage capacity
limit", we discovered:
  1. Emergent's API does NOT expose a DELETE method (Allow: PUT, GET, HEAD).
  2. Every failed/dismissed upload's chunks accumulate forever in storage.
  3. Users have no way to reclaim space themselves — only Emergent staff can
     manually purge.

This endpoint generates a JSON report the user can email to support so the
backend team can run a one-time purge of orphan chunks.
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
    return {"email": f"clean-{s}@example.com", "password": "CleanPass2026!", "name": f"Clean {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


# ---------------------------------------------------------------------------
# 1. Endpoint requires auth, returns proper shape
# ---------------------------------------------------------------------------

def test_cleanup_report_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/admin/storage-cleanup/report")
            assert r.status_code in (401, 403)
    _run_async(run())


def test_cleanup_report_empty_for_fresh_user():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.get("/api/admin/storage-cleanup/report")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["summary"]["total_orphan_chunks"] == 0
            assert body["summary"]["total_estimated_bytes"] == 0
            assert "instructions" in body
            assert "support@emergent.sh" in body["instructions"]
            # All four buckets present and empty
            for bucket in ("dismissed_sessions", "failed_videos", "deleted_videos", "lost_chunks"):
                assert bucket in body["buckets"], f"bucket {bucket} missing"
                assert body["buckets"][bucket] == []
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. Each bucket gets populated correctly
# ---------------------------------------------------------------------------

def test_cleanup_report_collects_dismissed_sessions():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            # Seed a dismissed chunked_upload with 3 storage-backed chunks
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": uid, "match_id": "m1", "filename": "dismissed.mp4",
                "file_size": 30 * 1024 * 1024, "status": "in_progress",
                "chunk_paths": {"0": "soccer-analysis/x/0.bin", "1": "soccer-analysis/x/1.bin", "2": "soccer-analysis/x/2.bin"},
                "chunk_backends": {"0": "storage", "1": "storage", "2": "storage"},
                "dismissed_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert body["summary"]["total_orphan_chunks"] == 3
            assert len(body["buckets"]["dismissed_sessions"]) == 3
            paths = [e["path"] for e in body["buckets"]["dismissed_sessions"]]
            assert "soccer-analysis/x/0.bin" in paths
            assert "soccer-analysis/x/1.bin" in paths
            assert "soccer-analysis/x/2.bin" in paths
        finally:
            await c.aclose()
    _run_async(run())


def test_cleanup_report_collects_failed_videos():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            vid = str(uuid.uuid4())
            await db.videos.insert_one({
                "id": vid, "user_id": uid, "match_id": "m1",
                "original_filename": "fail.mp4", "is_chunked": True, "is_deleted": False,
                "total_chunks": 2, "chunk_size": 10 * 1024 * 1024,
                "chunk_paths": {"0": "soccer-analysis/f/0.bin", "1": "soccer-analysis/f/1.bin"},
                "chunk_backends": {"0": "storage", "1": "storage"},
                "processing_status": "failed",
                "processing_error": "Whatever",
                "storage_path": "chunked:test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert len(body["buckets"]["failed_videos"]) == 2
            assert len(body["buckets"]["deleted_videos"]) == 0
        finally:
            await c.aclose()
    _run_async(run())


def test_cleanup_report_separates_deleted_from_failed_videos():
    """A failed video that has been is_deleted=true belongs to a different
    bucket — different priority for purging."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            uid = me["id"]
            await db.videos.insert_one({
                "id": str(uuid.uuid4()), "user_id": uid, "match_id": "m1",
                "original_filename": "deleted.mp4", "is_chunked": True, "is_deleted": True,
                "total_chunks": 1, "chunk_size": 10 * 1024 * 1024,
                "chunk_paths": {"0": "soccer-analysis/del/0.bin"},
                "chunk_backends": {"0": "storage"},
                "processing_status": "failed",
                "storage_path": "chunked:test",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert len(body["buckets"]["deleted_videos"]) == 1
            assert len(body["buckets"]["failed_videos"]) == 0
        finally:
            await c.aclose()
    _run_async(run())


def test_cleanup_report_cross_user_isolation():
    """User B's cleanup report must NEVER include User A's orphans."""
    async def run():
        from db import db
        c_a = await _client(_payload())
        c_b = await _client(_payload())
        try:
            me_a = (await c_a.get("/api/auth/me")).json()
            await db.chunked_uploads.insert_one({
                "upload_id": str(uuid.uuid4()),
                "user_id": me_a["id"], "match_id": "ma", "filename": "a.mp4",
                "file_size": 10 * 1024 * 1024, "status": "in_progress",
                "chunk_paths": {"0": "soccer-analysis/a-only/0.bin"},
                "chunk_backends": {"0": "storage"},
                "dismissed_at": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r_b = await c_b.get("/api/admin/storage-cleanup/report")
            assert r_b.json()["summary"]["total_orphan_chunks"] == 0, (
                "User B saw User A's orphan chunks — cross-user leak!"
            )
        finally:
            await c_a.aclose()
            await c_b.aclose()
    _run_async(run())


def test_cleanup_report_instructions_mention_no_delete_api():
    """The instructions must explain WHY the user can't self-serve — there's
    no DELETE endpoint on Emergent's Object Storage API."""
    async def run():
        c = await _client(_payload())
        try:
            r = await c.get("/api/admin/storage-cleanup/report")
            body = r.json()
            assert "DELETE" in body["instructions"], (
                "Instructions must explain that the storage API has no DELETE — "
                "that's the key insight the user needs to escalate effectively."
            )
            assert "support@emergent.sh" in body["instructions"]
        finally:
            await c.aclose()
    _run_async(run())
