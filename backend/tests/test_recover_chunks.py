"""
iter88 — Recovery endpoint for chunked videos stuck on the iter87 missing-
chunk error.

POST /api/videos/{video_id}/recover-chunks should:
  1. Sync chunk_paths/chunk_backends FROM chunked_uploads → videos (the
     background migration loop updates chunked_uploads first, so a stale
     video doc pointer is the common case).
  2. Re-run migration on every chunk still tagged persistent_filesystem in
     the video doc.
  3. Reset processing_status to "pending" + clear error if integrity is
     now "full".
"""
import os
import sys
import asyncio
import uuid
from datetime import datetime, timezone

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


def _payload():
    s = uuid.uuid4().hex[:10]
    return {"email": f"recov-{s}@example.com", "password": "RecovPass2026!", "name": f"Recov {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


# ---------------------------------------------------------------------------
# 1. Auth + 404
# ---------------------------------------------------------------------------

def test_recover_chunks_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.post("/api/videos/some-fake-id/recover-chunks")
            assert r.status_code in (401, 403)
    _run_async(run())


def test_recover_chunks_404_for_unknown_video():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.post("/api/videos/does-not-exist/recover-chunks")
            assert r.status_code == 404, r.text
        finally:
            await c.aclose()
    _run_async(run())


def test_recover_chunks_400_for_non_chunked_video():
    """Recovery only applies to chunked uploads — refuse cleanly for any
    legacy single-shot uploads that wound up here."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            video_id = str(uuid.uuid4())
            match_id = str(uuid.uuid4())
            await db.matches.insert_one({
                "id": match_id, "user_id": me["id"],
                "team_home": "X", "team_away": "Y", "date": "2026-05-22",
                "competition": "T",
            })
            await db.videos.insert_one({
                "id": video_id, "match_id": match_id, "user_id": me["id"],
                "storage_path": "legacy/key.mp4",
                "is_chunked": False, "is_deleted": False,
                "original_filename": "old.mp4",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            r = await c.post(f"/api/videos/{video_id}/recover-chunks")
            assert r.status_code == 400, r.text
            # Cleanup
            await db.videos.delete_one({"id": video_id})
            await db.matches.delete_one({"id": match_id})
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. Happy path: chunked_uploads has fresher pointers than the video doc
# ---------------------------------------------------------------------------

def test_recover_chunks_syncs_from_uploads_when_video_doc_is_stale():
    """Real iter87 production scenario: the background migration swapped
    chunk N from persistent_filesystem → storage in chunked_uploads but the
    video doc still has the stale pointer. Recovery should sync the pointer
    and integrity should jump back to full."""
    async def run():
        from db import db, APP_NAME
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            video_id = str(uuid.uuid4())
            upload_id = str(uuid.uuid4())
            match_id = str(uuid.uuid4())

            # Seed match + chunked_uploads (with newer pointers) + video (with stale ones)
            await db.matches.insert_one({
                "id": match_id, "user_id": me["id"],
                "team_home": "Recovery", "team_away": "Test",
                "date": "2026-05-22", "competition": "T",
            })

            # chunked_uploads: all 3 chunks already migrated to storage
            storage_paths = {
                str(i): f"{APP_NAME}/videos/{me['id']}/{video_id}_chunk_{i:06d}.bin"
                for i in range(3)
            }
            storage_backends = {str(i): "storage" for i in range(3)}
            await db.chunked_uploads.insert_one({
                "upload_id": upload_id, "video_id": video_id, "user_id": me["id"],
                "match_id": match_id, "filename": "f.mp4", "file_size": 30 * 1024 * 1024,
                "status": "completed",
                "chunk_paths": storage_paths,
                "chunk_backends": storage_backends,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            # video doc: chunks 0,1 already on storage, chunk 2 still has STALE
            # persistent_filesystem pointer to a path that doesn't exist anymore
            stale_paths = dict(storage_paths)
            stale_backends = dict(storage_backends)
            stale_paths["2"] = "/app/.video_chunks/abc/chunk_000002.bin"  # ghost
            stale_backends["2"] = "persistent_filesystem"
            await db.videos.insert_one({
                "id": video_id, "match_id": match_id, "user_id": me["id"],
                "storage_path": f"chunked:{upload_id}",
                "chunk_paths": stale_paths, "chunk_backends": stale_backends,
                "total_chunks": 3, "chunk_size": 10 * 1024 * 1024,
                "is_chunked": True, "is_deleted": False,
                "original_filename": "f.mp4",
                "processing_status": "failed",
                "processing_error": "Chunk 2 of 3 (persistent_filesystem) was lost — re-upload required.",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            r = await c.post(f"/api/videos/{video_id}/recover-chunks")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["synced_from_uploads"] >= 1, body
            assert body["ready_to_retry"] is True, body
            assert body["integrity"] == "full"

            # Verify the video doc was updated AND processing_status reset
            v = await db.videos.find_one({"id": video_id}, {"_id": 0})
            assert v["chunk_backends"]["2"] == "storage"
            assert v["chunk_paths"]["2"] == storage_paths["2"]
            assert v["processing_status"] == "pending"
            assert v.get("processing_error") in (None, "")

            # Cleanup
            await db.chunked_uploads.delete_one({"upload_id": upload_id})
            await db.videos.delete_one({"id": video_id})
            await db.matches.delete_one({"id": match_id})
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 3. Unrecoverable case: chunk missing from BOTH storage and local PV
# ---------------------------------------------------------------------------

def test_recover_chunks_reports_unrecoverable_when_no_pointer_can_be_synced(monkeypatch):
    """If the chunked_uploads doc ALSO has persistent_filesystem for the
    missing chunk AND storage refuses to accept the migration AND there's
    no local file, recovery returns ready_to_retry=False and the user is
    told to re-upload."""
    async def run():
        from db import db
        from services import storage as storage_mod

        # Force put_object to fail so migration can't succeed
        async def _fail(*_a, **_kw):
            raise RuntimeError("storage rejecting")
        monkeypatch.setattr(storage_mod, "put_object_with_retry", _fail)

        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            video_id = str(uuid.uuid4())
            upload_id = str(uuid.uuid4())
            match_id = str(uuid.uuid4())
            await db.matches.insert_one({
                "id": match_id, "user_id": me["id"],
                "team_home": "Unrecov", "team_away": "Test",
                "date": "2026-05-22", "competition": "T",
            })
            ghost = "/app/.video_chunks/ghost/chunk_000000.bin"  # never existed
            await db.chunked_uploads.insert_one({
                "upload_id": upload_id, "video_id": video_id, "user_id": me["id"],
                "match_id": match_id, "filename": "g.mp4", "file_size": 10 * 1024 * 1024,
                "status": "completed",
                "chunk_paths": {"0": ghost},
                "chunk_backends": {"0": "persistent_filesystem"},
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            await db.videos.insert_one({
                "id": video_id, "match_id": match_id, "user_id": me["id"],
                "storage_path": f"chunked:{upload_id}",
                "chunk_paths": {"0": ghost},
                "chunk_backends": {"0": "persistent_filesystem"},
                "total_chunks": 1, "chunk_size": 10 * 1024 * 1024,
                "is_chunked": True, "is_deleted": False,
                "original_filename": "g.mp4",
                "processing_status": "failed",
                "processing_error": "Chunk 0 of 1 missing",
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

            r = await c.post(f"/api/videos/{video_id}/recover-chunks")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["ready_to_retry"] is False
            assert body["integrity"] != "full"
            # processing_status should stay "failed" — recovery didn't fix it
            v = await db.videos.find_one({"id": video_id}, {"_id": 0})
            assert v["processing_status"] == "failed"

            # Cleanup
            await db.chunked_uploads.delete_one({"upload_id": upload_id})
            await db.videos.delete_one({"id": video_id})
            await db.matches.delete_one({"id": match_id})
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 4. Frontend wiring
# ---------------------------------------------------------------------------

def test_header_renders_try_recovery_button_only_for_missing_chunk_errors():
    """Grep-level guards: the Try Recovery button must be conditional on the
    error mentioning missing chunks (so it doesn't appear for AI-budget or
    invalid-mp4 failures where recovery can't help)."""
    header_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "components",
        "VideoAnalysisHeader.js",
    )
    with open(header_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert 'data-testid="try-recovery-btn"' in src
    assert "canTryRecovery" in src or "canRecover" in src, (
        "Header must gate the button on a derived flag (e.g. canTryRecovery), "
        "not show it for every failed video."
    )
    # The gate must look at the error text
    assert "chunk" in src.lower() and "missing" in src.lower(), (
        "canTryRecovery must inspect the processing_error for chunk/missing "
        "keywords so it doesn't fire on AI-budget or invalid-mp4 failures."
    )


def test_video_analysis_page_wires_recovery_handler():
    page_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "VideoAnalysis.js",
    )
    with open(page_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "handleTryRecovery" in src
    assert "/recover-chunks" in src
    assert "onTryRecovery={handleTryRecovery}" in src
