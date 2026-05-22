"""Object storage and chunk management"""
import os
import time
import logging
import asyncio
import shutil
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from starlette.concurrency import run_in_threadpool
from db import (
    db, STORAGE_URL, EMERGENT_KEY, APP_NAME, CHUNK_STORAGE_DIR,
    PERSISTENT_CHUNK_DIR, PERSISTENT_CHUNK_FREE_MIN_BYTES,
)

logger = logging.getLogger(__name__)
storage_key = None

def create_storage_session():
    session = requests.Session()
    retry_strategy = Retry(total=0)
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session

storage_session = create_storage_session()

def init_storage():
    global storage_key
    if storage_key:
        return storage_key
    try:
        resp = storage_session.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
        resp.raise_for_status()
        storage_key = resp.json()["storage_key"]
        logger.info("Storage initialized successfully")
        return storage_key
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
        raise

def reset_storage():
    global storage_key
    storage_key = None

def put_object_sync(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    resp = storage_session.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=(3, 15)
    )
    resp.raise_for_status()
    return resp.json()

async def put_object_with_retry(path: str, data: bytes, content_type: str, max_retries: int = 6) -> dict:
    global storage_session
    last_error = None
    for attempt in range(max_retries):
        try:
            result = await run_in_threadpool(put_object_sync, path, data, content_type)
            return result
        except Exception as e:
            last_error = e
            error_str = str(e)
            is_retryable = "SSL" in error_str or "Connection" in error_str or "EOF" in error_str or "500" in error_str
            if attempt < max_retries - 1 and is_retryable:
                logger.warning(f"Storage upload failed (attempt {attempt+1}/{max_retries}), retrying: {error_str[:100]}")
                storage_session = create_storage_session()
                reset_storage()
                init_storage()
                # Exponential backoff — was hard-coded 2s, now ramps to give the
                # storage backend more recovery time between retries.
                await asyncio.sleep(min(2 ** attempt, 10))
            else:
                raise
    raise last_error

def get_object_sync(path: str) -> tuple:
    key = init_storage()
    resp = storage_session.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=120)
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")

def delete_object_sync(path: str):
    key = init_storage()
    try:
        storage_session.delete(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=30)
    except Exception:
        pass

# Circuit breaker
class StorageCircuitBreaker:
    """Trip after MANY consecutive failures — was 1 (way too aggressive: a single
    transient SSL flake sent every subsequent chunk to ephemeral filesystem
    storage, which then evaporated on the next pod restart, leaving the user
    with "Upload incomplete (50 of 85 chunks)" failures that look like client
    issues but were actually our storage-routing decision)."""
    def __init__(self, failure_threshold=8, reset_timeout=60):
        self.consecutive_failures = 0
        self.failure_threshold = failure_threshold
        self.last_failure_time = 0
        self.reset_timeout = reset_timeout

    @property
    def is_open(self):
        if self.consecutive_failures >= self.failure_threshold:
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.consecutive_failures = 0
                return False
            return True
        return False

    def record_failure(self):
        self.consecutive_failures += 1
        self.last_failure_time = time.time()

    def record_success(self):
        self.consecutive_failures = 0

storage_breaker = StorageCircuitBreaker()

def _write_file(path: str, data: bytes):
    with open(path, 'wb') as f:
        f.write(data)

def _read_file(path: str) -> bytes:
    with open(path, 'rb') as f:
        return f.read()

async def store_chunk(video_id: str, user_id: str, chunk_index: int, data: bytes) -> dict:
    """Store a single video chunk. Strongly prefers persistent object storage;
    falls back to the persistent local PV (`/app/.video_chunks`) when storage
    is degraded — never to ephemeral `/var/video_chunks` which evaporates on
    pod restart.

    Returns one of:
      - {"backend": "storage",                "path": <object-store-key>, ...}  # normal happy path
      - {"backend": "persistent_filesystem",  "path": <local PV abs path>, ...} # fallback during outage; will be migrated later
      - raises RuntimeError(reason)                                            # both tiers unusable — caller turns this into 503

    The caller (`server.py::upload_chunk`) commits both backends to the
    `chunked_uploads` document. A background task (`migrate_persistent_chunks`)
    periodically walks `chunk_backends == "persistent_filesystem"` entries and
    re-uploads them to object storage once it recovers, swapping the backend
    in-place and deleting the local file.
    """
    chunk_path = f"{APP_NAME}/videos/{user_id}/{video_id}_chunk_{chunk_index:06d}.bin"
    if not storage_breaker.is_open:
        try:
            await put_object_with_retry(chunk_path, data, "application/octet-stream", max_retries=6)
            storage_breaker.record_success()
            return {"backend": "storage", "path": chunk_path, "size": len(data)}
        except Exception as e:
            storage_breaker.record_failure()
            logger.warning(f"Object Storage failed, falling back to persistent_filesystem: {str(e)[:80]}")
    else:
        logger.info("Circuit breaker OPEN - using persistent_filesystem directly")

    # iter83: persistent fallback. /app is PV-backed (/dev/nvme0n*) so files
    # survive pod restarts. Refuse the write if /app is critically low — better
    # to 503 the client than to OOM the pod by filling /app to 100%.
    try:
        _, _, free = await run_in_threadpool(shutil.disk_usage, PERSISTENT_CHUNK_DIR if os.path.exists(PERSISTENT_CHUNK_DIR) else "/app")
    except OSError:
        free = 0
    if free < PERSISTENT_CHUNK_FREE_MIN_BYTES:
        logger.error(
            f"Persistent fallback refused — /app has only {free/(1024**2):.0f} MB free "
            f"(need >= {PERSISTENT_CHUNK_FREE_MIN_BYTES/(1024**2):.0f} MB)."
        )
        raise RuntimeError("persistent_storage_full")

    video_dir = os.path.join(PERSISTENT_CHUNK_DIR, video_id)
    await run_in_threadpool(os.makedirs, video_dir, exist_ok=True)
    local_path = os.path.join(video_dir, f"chunk_{chunk_index:06d}.bin")
    await run_in_threadpool(_write_file, local_path, data)
    return {"backend": "persistent_filesystem", "path": local_path, "size": len(data)}


async def read_chunk_data(video_id: str, chunk_index: int, chunk_info: dict) -> bytes:
    backend = chunk_info.get("backend", "storage")
    path = chunk_info.get("path", "")
    # iter83: persistent_filesystem reads identically to the legacy "filesystem"
    # backend — both are local files at an absolute path. Kept distinct in the
    # DB so the migration task can identify chunks still needing upload.
    if backend in ("filesystem", "persistent_filesystem"):
        return await run_in_threadpool(_read_file, path)
    elif backend == "mongodb":
        doc = await db.video_chunks.find_one({"video_id": video_id, "chunk_index": chunk_index}, {"data": 1})
        if doc and "data" in doc:
            return bytes(doc["data"])
        raise Exception(f"Chunk {chunk_index} not found in MongoDB")
    else:
        data, _ = await run_in_threadpool(get_object_sync, path)
        return data


# ----- iter83: background migration of persistent_filesystem chunks -----
#
# When object storage is degraded, store_chunk commits the chunk to
# /app/.video_chunks with backend="persistent_filesystem". This task walks
# those committed chunks and re-uploads them to object storage as soon as
# storage recovers — swapping the backend tag and deleting the local file
# so /app doesn't fill up over time.

# Public knobs (kept module-level so tests can monkeypatch them):
MIGRATE_INTERVAL_SECS = 30          # how often the loop wakes up
MIGRATE_BATCH = 25                  # max chunks to migrate per pass


async def _migrate_one_chunk(video_id: str, chunk_index_str: str, local_path: str, user_id: str) -> bool:
    """Upload a single persistent chunk to object storage. Returns True on
    successful upload (caller is responsible for the DB swap AND for deleting
    the local file ONLY AFTER the DB swap is committed — iter87 fix for the
    race that corrupted videos when the pod restarted between os.remove and
    update_one).

    Does NOT delete the local file — that's the caller's job, post-DB-swap."""
    if not os.path.exists(local_path):
        # File evaporated (manual cleanup or volume detached) — drop the
        # entry so the migration loop doesn't burn cycles on it forever.
        logger.warning(f"Persistent chunk file missing, dropping backend entry: {local_path}")
        return True

    try:
        data = await run_in_threadpool(_read_file, local_path)
    except Exception as e:
        logger.warning(f"Could not read persistent chunk {local_path}: {e}")
        return False

    target_key = f"{APP_NAME}/videos/{user_id}/{video_id}_chunk_{int(chunk_index_str):06d}.bin"
    try:
        await put_object_with_retry(target_key, data, "application/octet-stream", max_retries=3)
    except Exception as e:
        logger.info(f"Migration: storage still rejecting chunk {video_id}/{chunk_index_str}: {str(e)[:80]}")
        return False
    return True


async def _migrate_collection(coll_name: str) -> int:
    """Walk a collection (`chunked_uploads` or `videos`), find any chunk
    that's still on persistent_filesystem, try to migrate it to object
    storage, and persist the backend/path swap in the same document.
    Returns the number of chunks moved this pass.

    iter87 (P0): write-then-update-then-delete ordering. Pre-iter87 the local
    file was deleted INSIDE _migrate_one_chunk before the DB swap — if the
    pod restarted between those two steps, the DB still pointed at a deleted
    file. The video assembler would silently zero-fill the missing chunk,
    corrupting the mp4 (moov atom missing). Now we:
      1. Upload the bytes to object storage
      2. Swap the DB pointer (backend → storage, path → new key)
      3. ONLY THEN delete the local file
    A pod restart between any two of these leaves the system in a safe state.
    """
    coll = db[coll_name]
    query = {"chunk_backends": {"$exists": True, "$ne": {}}}
    moved = 0
    cursor = coll.find(query, {"_id": 0}).limit(50)
    async for doc in cursor:
        backends = doc.get("chunk_backends") or {}
        paths = doc.get("chunk_paths") or {}
        if not any(b == "persistent_filesystem" for b in backends.values()):
            continue

        user_id = doc.get("user_id")
        video_id = doc.get("video_id") or doc.get("id")
        upload_id = doc.get("upload_id")
        if not user_id or not video_id:
            continue

        per_doc_moved = 0
        for idx_str, backend_name in list(backends.items()):
            if backend_name != "persistent_filesystem":
                continue
            local_path = paths.get(idx_str)
            if not local_path:
                continue

            # 1. Upload the chunk to object storage
            ok = await _migrate_one_chunk(video_id, idx_str, local_path, user_id)
            if not ok:
                break

            # 2. Swap the DB pointer FIRST — this is the durable record.
            new_path = f"{APP_NAME}/videos/{user_id}/{video_id}_chunk_{int(idx_str):06d}.bin"
            filter_ = {"upload_id": upload_id} if upload_id and coll_name == "chunked_uploads" else {"id": video_id}
            try:
                await coll.update_one(filter_, {"$set": {
                    f"chunk_backends.{idx_str}": "storage",
                    f"chunk_paths.{idx_str}": new_path,
                }})
            except Exception as db_err:
                logger.error(
                    f"Migration: DB swap failed for {video_id}/{idx_str} after "
                    f"successful upload — local file PRESERVED so next tick can retry. "
                    f"err={db_err!r}"
                )
                continue  # don't delete the local file; next pass will retry

            # 3. ONLY NOW delete the local file. If the pod restarts between
            # steps 2 and 3, we leak one ~10MB file (next tick will skip it
            # since backend is now "storage") but the DB stays consistent.
            try:
                await run_in_threadpool(os.remove, local_path)
            except OSError as rm_err:
                logger.warning(
                    f"Migration: post-swap local file delete failed (orphan file, "
                    f"not a correctness issue) {local_path}: {rm_err}"
                )

            per_doc_moved += 1
            moved += 1
            if moved >= MIGRATE_BATCH:
                break

        if per_doc_moved:
            logger.info(f"Migration: {coll_name} {video_id} — moved {per_doc_moved} chunks to object storage")
        if moved >= MIGRATE_BATCH:
            break
    return moved


async def migrate_persistent_chunks_loop():
    """Forever-loop migration task. Hooked into server.py startup.

    Cheap when there's nothing to do: a single Mongo query with a sparse
    filter. We only do real work when chunks are actually marked
    persistent_filesystem."""
    await run_in_threadpool(os.makedirs, PERSISTENT_CHUNK_DIR, exist_ok=True)
    logger.info(f"[migrate-loop] watching {PERSISTENT_CHUNK_DIR} for persistent_filesystem chunks every {MIGRATE_INTERVAL_SECS}s")
    while True:
        try:
            moved_uploads = await _migrate_collection("chunked_uploads")
            moved_videos = await _migrate_collection("videos")
            if moved_uploads or moved_videos:
                logger.info(f"[migrate-loop] {moved_uploads + moved_videos} chunks migrated this pass")
        except Exception as e:
            logger.error(f"[migrate-loop] unexpected error (will keep looping): {e}")
        await asyncio.sleep(MIGRATE_INTERVAL_SECS)
