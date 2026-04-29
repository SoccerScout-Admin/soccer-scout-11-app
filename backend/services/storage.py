"""Object storage and chunk management"""
import os
import time
import logging
import asyncio
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from starlette.concurrency import run_in_threadpool
from db import db, STORAGE_URL, EMERGENT_KEY, APP_NAME, CHUNK_STORAGE_DIR, CHUNK_SIZE

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

async def put_object_with_retry(path: str, data: bytes, content_type: str, max_retries: int = 2) -> dict:
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
                await asyncio.sleep(2)
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
    def __init__(self, failure_threshold=1, reset_timeout=120):
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
    chunk_path = f"{APP_NAME}/videos/{user_id}/{video_id}_chunk_{chunk_index:06d}.bin"
    if not storage_breaker.is_open:
        try:
            await put_object_with_retry(chunk_path, data, "application/octet-stream", max_retries=2)
            storage_breaker.record_success()
            return {"backend": "storage", "path": chunk_path, "size": len(data)}
        except Exception as e:
            storage_breaker.record_failure()
            logger.warning(f"Object Storage failed, falling back to filesystem: {str(e)[:80]}")
    else:
        logger.info("Circuit breaker OPEN - using filesystem directly")

    video_dir = os.path.join(CHUNK_STORAGE_DIR, video_id)
    os.makedirs(video_dir, exist_ok=True)
    local_path = os.path.join(video_dir, f"chunk_{chunk_index:06d}.bin")
    await run_in_threadpool(_write_file, local_path, data)
    return {"backend": "filesystem", "path": local_path, "size": len(data)}

async def read_chunk_data(video_id: str, chunk_index: int, chunk_info: dict) -> bytes:
    backend = chunk_info.get("backend", "storage")
    path = chunk_info.get("path", "")
    if backend == "filesystem":
        return await run_in_threadpool(_read_file, path)
    elif backend == "mongodb":
        doc = await db.video_chunks.find_one({"video_id": video_id, "chunk_index": chunk_index}, {"data": 1})
        if doc and "data" in doc:
            return bytes(doc["data"])
        raise Exception(f"Chunk {chunk_index} not found in MongoDB")
    else:
        data, _ = await run_in_threadpool(get_object_sync, path)
        return data
