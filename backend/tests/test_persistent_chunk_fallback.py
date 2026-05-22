"""
iter83: persistent chunk fallback + background migration.

When object storage is degraded, store_chunk now falls back to
/app/.video_chunks (a real PV mount that survives pod restarts) instead of
/var/video_chunks (overlay = ephemeral). The background migrate_persistent_chunks_loop
re-uploads those chunks to object storage as soon as it recovers, swapping
the backend tag in MongoDB and deleting the local file.
"""
import os
import sys
import asyncio
import shutil
import tempfile
import uuid

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 1. Constants are wired correctly
# ---------------------------------------------------------------------------

def test_persistent_chunk_dir_points_at_pv():
    """PERSISTENT_CHUNK_DIR must live under /app (PV) — NOT /var (overlay)."""
    from db import PERSISTENT_CHUNK_DIR
    assert PERSISTENT_CHUNK_DIR.startswith("/app/"), (
        f"PERSISTENT_CHUNK_DIR is {PERSISTENT_CHUNK_DIR!r}; must live under /app "
        "so chunks survive pod restarts (real iter83 prod bug — 35 of 85 chunks "
        "evaporated from /var when the pod recycled mid-upload)."
    )


def test_persistent_chunk_free_min_is_reasonable():
    from db import PERSISTENT_CHUNK_FREE_MIN_BYTES
    # 100 MB - 2 GB is a sensible range — /app is small, but we still want a
    # margin so the rest of the app doesn't OOM.
    assert 100 * 1024 ** 2 <= PERSISTENT_CHUNK_FREE_MIN_BYTES <= 2 * 1024 ** 3


# ---------------------------------------------------------------------------
# 2. store_chunk fallback writes to /app, not /var
# ---------------------------------------------------------------------------

def test_store_chunk_fallback_writes_to_persistent_dir(monkeypatch, tmp_path):
    """Force object storage to fail. store_chunk must write the chunk under
    PERSISTENT_CHUNK_DIR, not CHUNK_STORAGE_DIR."""
    from services import storage as storage_mod

    fake_persistent = str(tmp_path / "persist")
    monkeypatch.setattr(storage_mod, "PERSISTENT_CHUNK_DIR", fake_persistent)
    # Generous free space so the disk-pressure short-circuit doesn't fire
    monkeypatch.setattr(storage_mod, "PERSISTENT_CHUNK_FREE_MIN_BYTES", 1)

    # Force put_object_with_retry to always fail (simulate storage outage)
    async def _always_fail(*_a, **_kw):
        raise RuntimeError("simulated storage 500")
    monkeypatch.setattr(storage_mod, "put_object_with_retry", _always_fail)
    # Make sure breaker is closed at the start of the test
    storage_mod.storage_breaker.consecutive_failures = 0

    result = _run(storage_mod.store_chunk("vid-abc", "user-x", 0, b"a" * 1024))

    assert result["backend"] == "persistent_filesystem", (
        f"Expected persistent_filesystem backend, got {result['backend']!r}"
    )
    assert result["path"].startswith(fake_persistent), (
        f"Chunk landed at {result['path']!r}; expected under {fake_persistent!r}"
    )
    # File should actually exist on disk
    assert os.path.exists(result["path"])


def test_store_chunk_raises_when_disk_low(monkeypatch, tmp_path):
    """If /app is critically low, store_chunk must raise RuntimeError (not
    silently commit and risk filling /app to 100%)."""
    from services import storage as storage_mod

    fake_persistent = str(tmp_path / "persist")
    os.makedirs(fake_persistent, exist_ok=True)
    monkeypatch.setattr(storage_mod, "PERSISTENT_CHUNK_DIR", fake_persistent)
    # Set the floor higher than any real disk so the check always trips
    monkeypatch.setattr(storage_mod, "PERSISTENT_CHUNK_FREE_MIN_BYTES", 10 ** 18)

    async def _always_fail(*_a, **_kw):
        raise RuntimeError("simulated storage 500")
    monkeypatch.setattr(storage_mod, "put_object_with_retry", _always_fail)
    storage_mod.storage_breaker.consecutive_failures = 0

    raised = None
    try:
        _run(storage_mod.store_chunk("vid-low", "user-y", 0, b"x" * 1024))
    except RuntimeError as e:
        raised = e
    assert raised is not None, "store_chunk should raise when /app is critically low"
    assert "persistent_storage_full" in str(raised)


# ---------------------------------------------------------------------------
# 3. read_chunk_data understands the new backend tag
# ---------------------------------------------------------------------------

def test_read_chunk_data_reads_persistent_filesystem(tmp_path):
    """Backend `persistent_filesystem` must read the same way as the legacy
    `filesystem` tag — both are local files at an absolute path."""
    from services import storage as storage_mod

    chunk_path = tmp_path / "chunk_000000.bin"
    chunk_path.write_bytes(b"hello-iter83")

    result = _run(storage_mod.read_chunk_data(
        video_id="vid-rdtest",
        chunk_index=0,
        chunk_info={"backend": "persistent_filesystem", "path": str(chunk_path)},
    ))
    assert result == b"hello-iter83"


# ---------------------------------------------------------------------------
# 4. Migration loop actually swaps backends + cleans up
# ---------------------------------------------------------------------------

def test_migrate_one_chunk_swaps_backend(monkeypatch, tmp_path):
    """_migrate_one_chunk: when object storage recovers, the chunk gets
    uploaded and the function returns True. iter87 note: the local file is
    NO LONGER deleted here — the caller (_migrate_collection) handles that
    AFTER the DB swap so a pod crash between can't lose the chunk."""
    from services import storage as storage_mod

    local = tmp_path / "chunk_000003.bin"
    local.write_bytes(b"some-data-iter83")

    calls = []
    async def _fake_put(path, data, ctype, max_retries=3):
        calls.append({"path": path, "size": len(data), "max_retries": max_retries})
        return {"ok": True}
    monkeypatch.setattr(storage_mod, "put_object_with_retry", _fake_put)

    ok = _run(storage_mod._migrate_one_chunk("vid-mig", "3", str(local), "user-z"))
    assert ok is True
    # iter87: local file MUST survive — caller is responsible for delete-post-swap.
    assert local.exists(), (
        "iter87 changed the contract: _migrate_one_chunk must leave the local "
        "file in place. Deletion is now sequenced after the DB swap in "
        "_migrate_collection so the moov-atom corruption race can't happen."
    )
    assert len(calls) == 1
    assert "vid-mig_chunk_000003.bin" in calls[0]["path"]


def test_migrate_one_chunk_keeps_file_on_failure(monkeypatch, tmp_path):
    """When put_object still fails, the local chunk MUST be preserved so the
    next migration pass can retry it."""
    from services import storage as storage_mod

    local = tmp_path / "chunk_000005.bin"
    local.write_bytes(b"sticky-data")

    async def _fake_fail(*_a, **_kw):
        raise RuntimeError("storage still 500")
    monkeypatch.setattr(storage_mod, "put_object_with_retry", _fake_fail)

    ok = _run(storage_mod._migrate_one_chunk("vid-keep", "5", str(local), "user-k"))
    assert ok is False
    assert local.exists(), "Local chunk must NOT be deleted when migration fails"


def test_migrate_one_chunk_drops_missing_file(tmp_path):
    """If the local file was wiped externally (manual cleanup / volume detach),
    return True so the loop drops the dead entry instead of looping forever."""
    from services import storage as storage_mod

    nonexistent = str(tmp_path / "doesnotexist.bin")
    ok = _run(storage_mod._migrate_one_chunk("vid-gone", "9", nonexistent, "user-g"))
    assert ok is True


def test_migrate_interval_is_short_enough():
    """The migration interval must wake up frequently enough that a transient
    outage gets cleared without the user noticing."""
    from services import storage as storage_mod
    assert storage_mod.MIGRATE_INTERVAL_SECS <= 60, (
        f"MIGRATE_INTERVAL_SECS is {storage_mod.MIGRATE_INTERVAL_SECS} — too slow. "
        "Should re-check at least once a minute so persistent chunks don't sit "
        "on /app any longer than needed."
    )


# ---------------------------------------------------------------------------
# 5. Server-side upload_chunk no longer auto-503s filesystem chunks
# ---------------------------------------------------------------------------

def test_upload_chunk_does_not_reject_filesystem_anymore():
    """iter80 used to reject filesystem chunks with 503. iter83 commits them
    instead (now safe because they're on a PV). Grep-level guard to prevent
    the old behavior sneaking back in."""
    with open(os.path.join(_BACKEND, "server.py"), "r", encoding="utf-8") as f:
        src = f.read()
    # The old iter80 rejection message must be GONE.
    assert "routed to ephemeral filesystem" not in src, (
        "iter83 deleted the iter80 ephemeral-filesystem 503 rejection — but the "
        "log line is still in server.py. Either the rejection logic snuck back, "
        "or the comment leaked. Either way: clean it up."
    )
