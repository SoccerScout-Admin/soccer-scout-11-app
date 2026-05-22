"""
iter87 — P0 fix for the "moov atom missing" / silent chunk corruption bug.

Real production bug 2026-05-22: a user's 0.83 GB chunked upload finalized
successfully, then processing failed with "moov atom not found". Root cause:
the iter83 migration loop deleted the local file BEFORE swapping the DB
pointer, so a pod restart between those two steps left the DB referencing
a deleted file. The assembly code (prepare_video_sample) then silently
ZERO-FILLED that missing chunk — corrupting the mp4 wherever the moov atom
lived.

Three fixes guarded by these tests:
  1. Migration: upload → swap DB → delete file (in that order, no skips).
  2. Assembly: raise RuntimeError on first missing/unreadable chunk
     instead of zero-filling. User sees the actual root cause.
  3. _check_chunk_integrity honors `persistent_filesystem` backend too,
     not just legacy `filesystem`.
"""
import os
import sys
import asyncio
from unittest.mock import patch

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
# Fix 1: Migration ordering — write-then-update-then-delete
# ---------------------------------------------------------------------------

def test_migration_no_longer_deletes_file_inside_migrate_one_chunk(monkeypatch, tmp_path):
    """_migrate_one_chunk MUST NOT call os.remove anymore. The local file
    deletion has moved to _migrate_collection so it can be sequenced AFTER
    the DB swap (preventing the moov-atom corruption bug)."""
    from services import storage as storage_mod

    local = tmp_path / "chunk_000000.bin"
    local.write_bytes(b"iter87-bytes" * 100)

    # Make put_object succeed instantly
    async def _ok(*_a, **_kw):
        return {"ok": True}
    monkeypatch.setattr(storage_mod, "put_object_with_retry", _ok)

    # Track any os.remove calls — should be ZERO
    remove_calls = []
    orig_remove = os.remove
    def _spy_remove(p):
        remove_calls.append(p)
        return orig_remove(p)
    monkeypatch.setattr(os, "remove", _spy_remove)

    ok = _run(storage_mod._migrate_one_chunk("vid-x", "0", str(local), "user-x"))
    assert ok is True
    assert remove_calls == [], (
        f"_migrate_one_chunk called os.remove({remove_calls}) — iter87 moved this "
        "delete to _migrate_collection so it happens AFTER the DB swap. Calling "
        "it inside _migrate_one_chunk re-opens the race that corrupted videos."
    )
    assert local.exists(), "Local file must survive _migrate_one_chunk (iter87)"


def test_migration_db_swap_happens_before_file_delete(monkeypatch, tmp_path):
    """_migrate_collection must call update_one BEFORE os.remove. Order
    matters: if the pod crashes between, we'd rather leak a 10MB file than
    lose track of where the chunk lives."""
    from services import storage as storage_mod

    # Stub out the DB layer with an in-memory recorder
    call_order = []
    fake_chunk_path = tmp_path / "fake_chunk.bin"
    fake_chunk_path.write_bytes(b"x" * 1024)

    class FakeColl:
        async def update_one(self, _filt, _update):
            call_order.append("update_one")
            class _Res:
                pass
            return _Res()
        def find(self, *_a, **_kw):
            class _Cur:
                def __init__(self):
                    self._yielded = False
                    self._docs = [{
                        "id": "vid-x", "user_id": "user-x",
                        "chunk_backends": {"0": "persistent_filesystem"},
                        "chunk_paths": {"0": str(fake_chunk_path)},
                    }]
                def limit(self, _n):
                    return self
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    if self._docs:
                        return self._docs.pop(0)
                    raise StopAsyncIteration
            return _Cur()

    class FakeDB(dict):
        def __getitem__(self, _key):
            return FakeColl()
    monkeypatch.setattr(storage_mod, "db", FakeDB())

    async def _ok(*_a, **_kw):
        return {"ok": True}
    monkeypatch.setattr(storage_mod, "put_object_with_retry", _ok)

    orig_remove = os.remove
    def _spy_remove(p):
        call_order.append("remove")
        return orig_remove(p)
    monkeypatch.setattr(os, "remove", _spy_remove)

    moved = _run(storage_mod._migrate_collection("videos"))
    assert moved == 1
    assert call_order == ["update_one", "remove"], (
        f"Expected update_one BEFORE remove, got {call_order}. iter87 requires "
        "the DB pointer to be swapped before the local file is deleted — otherwise "
        "a pod restart between those two steps leaves the DB pointing at a deleted "
        "file (which the iter80 assembly then zero-filled, corrupting the mp4)."
    )


def test_migration_preserves_local_file_if_db_swap_fails(monkeypatch, tmp_path):
    """If the DB update_one raises (e.g. transient mongo blip), the local
    file must NOT be deleted — next tick will retry the whole sequence."""
    from services import storage as storage_mod

    local = tmp_path / "chunk_000001.bin"
    local.write_bytes(b"sticky-iter87")

    class FailingColl:
        async def update_one(self, _filt, _update):
            raise RuntimeError("simulated mongo blip")
        def find(self, *_a, **_kw):
            class _Cur:
                def __init__(self):
                    self._docs = [{
                        "id": "vid-y", "user_id": "user-y",
                        "chunk_backends": {"1": "persistent_filesystem"},
                        "chunk_paths": {"1": str(local)},
                    }]
                def limit(self, _n):
                    return self
                def __aiter__(self):
                    return self
                async def __anext__(self):
                    if self._docs:
                        return self._docs.pop(0)
                    raise StopAsyncIteration
            return _Cur()

    class FakeDB(dict):
        def __getitem__(self, _key):
            return FailingColl()
    monkeypatch.setattr(storage_mod, "db", FakeDB())

    async def _ok(*_a, **_kw):
        return {"ok": True}
    monkeypatch.setattr(storage_mod, "put_object_with_retry", _ok)

    _run(storage_mod._migrate_collection("videos"))
    assert local.exists(), (
        "Local file was deleted even though the DB swap failed — this is the "
        "EXACT race that corrupted the user's 2026-05-22 production upload."
    )


# ---------------------------------------------------------------------------
# Fix 2: Assembly fails fast on missing chunks (no more zero-fill)
# ---------------------------------------------------------------------------

def test_assembly_raises_on_missing_chunk_path(monkeypatch, tmp_path):
    """prepare_video_sample must raise on a chunk_paths entry that doesn't
    exist — NOT silently zero-fill 10MB of zeros into the assembled file."""
    from services import processing

    # Build a fake video doc that's "chunked" but chunk index 2 is missing
    video = {
        "id": "vid-missing",
        "original_filename": "test.mp4",
        "is_chunked": True,
        "chunk_paths": {"0": "/tmp/dummy0.bin", "1": "/tmp/dummy1.bin"},  # chunk 2 missing
        "chunk_backends": {"0": "storage", "1": "storage"},
        "total_chunks": 3,
        "chunk_size": 1024,
    }

    async def _fake_read(*_a, **_kw):
        return b"ok"
    monkeypatch.setattr(processing, "read_chunk_data", _fake_read)
    # Redirect raw_path to tmp_path so we don't write into /var/video_chunks
    monkeypatch.setattr(processing.tempfile, "mktemp",
                        lambda **_kw: str(tmp_path / "raw.mp4"))

    raised = None
    try:
        _run(processing.prepare_video_sample(video))
    except Exception as e:
        raised = e
    assert raised is not None, "prepare_video_sample must raise on missing chunk"
    msg = str(raised)
    assert "Chunk 2 of 3" in msg or "missing" in msg.lower(), (
        f"Expected a per-chunk error like 'Chunk 2 of 3 is missing'; got: {msg!r}"
    )
    assert "re-upload" in msg.lower(), (
        f"Expected the error to tell the user to re-upload; got: {msg!r}"
    )


def test_assembly_raises_on_persistent_filesystem_missing_file(monkeypatch, tmp_path):
    """If a chunk is tagged persistent_filesystem but the file is gone, the
    assembler must raise — NOT pass through to read_chunk_data and crash
    deeper with a confusing error. (This is exactly what the iter83 migration
    race produced.)"""
    from services import processing

    missing_local = str(tmp_path / "does_not_exist.bin")
    video = {
        "id": "vid-pf",
        "original_filename": "test.mp4",
        "is_chunked": True,
        "chunk_paths": {"0": missing_local},
        "chunk_backends": {"0": "persistent_filesystem"},
        "total_chunks": 1,
        "chunk_size": 1024,
    }
    monkeypatch.setattr(processing.tempfile, "mktemp",
                        lambda **_kw: str(tmp_path / "raw.mp4"))

    raised = None
    try:
        _run(processing.prepare_video_sample(video))
    except Exception as e:
        raised = e
    assert raised is not None
    msg = str(raised)
    assert "Chunk 0 of 1" in msg
    assert "persistent_filesystem" in msg or "was lost" in msg
    assert "re-upload" in msg.lower()


def test_assembly_zero_fill_pattern_completely_removed_from_processing():
    """Grep-level guard: the old zero-fill behavior must not silently sneak
    back via a future refactor. ALL writes of `b'\\x00' * chunk_size` must
    be gone from processing.py — any chunk we can't read is a re-upload."""
    proc_path = os.path.join(_BACKEND, "services", "processing.py")
    with open(proc_path, "r", encoding="utf-8") as f:
        src = f.read()
    # The exact zero-fill expression
    assert "b'\\x00' * chunk_size" not in src, (
        "processing.py still contains a zero-fill expression — re-introduces "
        "the moov-atom corruption bug. Replace with `raise RuntimeError(...)`."
    )


# ---------------------------------------------------------------------------
# Fix 3: _check_chunk_integrity honors persistent_filesystem
# ---------------------------------------------------------------------------

def test_check_chunk_integrity_treats_missing_persistent_filesystem_as_unavailable(tmp_path):
    """_check_chunk_integrity must mark a persistent_filesystem chunk whose
    file is GONE as unavailable. Pre-iter87 it would count it as available
    because the existence check only ran for backend=='filesystem'."""
    from services import processing

    missing = str(tmp_path / "gone.bin")
    present = tmp_path / "here.bin"
    present.write_bytes(b"x")

    video = {
        "is_chunked": True,
        "chunk_paths": {"0": missing, "1": str(present)},
        "chunk_backends": {"0": "persistent_filesystem", "1": "persistent_filesystem"},
        "total_chunks": 2,
    }
    integrity, available, total = _run(processing._check_chunk_integrity(video))
    assert total == 2
    assert available == 1, (
        f"Expected 1 of 2 chunks available (file 0 is gone), got {available}/{total}. "
        "iter87 added persistent_filesystem to the existence check."
    )
    assert integrity == "partial"


def test_check_chunk_integrity_treats_present_persistent_filesystem_as_available(tmp_path):
    from services import processing

    p0 = tmp_path / "a.bin"; p0.write_bytes(b"a")
    p1 = tmp_path / "b.bin"; p1.write_bytes(b"b")
    video = {
        "is_chunked": True,
        "chunk_paths": {"0": str(p0), "1": str(p1)},
        "chunk_backends": {"0": "persistent_filesystem", "1": "persistent_filesystem"},
        "total_chunks": 2,
    }
    integrity, available, total = _run(processing._check_chunk_integrity(video))
    assert (integrity, available, total) == ("full", 2, 2)
