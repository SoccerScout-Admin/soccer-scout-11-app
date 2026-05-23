"""
iter89 — Disable dangerous /app fallback by default + broaden Try Recovery gate.

Real production bug 2026-05-23: a 1.04 GB / 107-chunk upload finalized at
100% client-side, but production's pod cycled mid-upload. Chunks that had
landed on /app/.video_chunks (the iter83 "persistent" PV fallback) DID NOT
survive — production's /app is NOT actually a real PV on Emergent's hosted
deploy. Result: video doc had all 107 chunk_paths populated but 106 of them
pointed at evaporated files. Migration tagged them "lost", integrity
reported 1 of 107, user got "Upload incomplete — re-upload required."

iter89 takes the conservative route: refuse the /app fallback unless the
operator explicitly opts in via env var. Without the env var, store_chunk
returns 503 immediately when object storage fails, letting iter82's
20-retry client-side budget ride out the outage against object storage.
"""
import os
import sys
import asyncio

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
# 1. store_chunk refuses /app fallback when env var is NOT set (default)
# ---------------------------------------------------------------------------

def test_store_chunk_refuses_fallback_by_default(monkeypatch, tmp_path):
    """Without ENABLE_PERSISTENT_CHUNK_FALLBACK, store_chunk must raise
    `storage_unavailable_fallback_disabled` when object storage fails —
    NOT write to /app/.video_chunks."""
    from services import storage as storage_mod

    # Ensure env var is unset (the safe default)
    monkeypatch.delenv("ENABLE_PERSISTENT_CHUNK_FALLBACK", raising=False)
    monkeypatch.setattr(storage_mod, "PERSISTENT_CHUNK_DIR", str(tmp_path / "fallback"))
    monkeypatch.setattr(storage_mod, "PERSISTENT_CHUNK_FREE_MIN_BYTES", 1)

    async def _always_fail(*_a, **_kw):
        raise RuntimeError("simulated storage 500")
    monkeypatch.setattr(storage_mod, "put_object_with_retry", _always_fail)
    storage_mod.storage_breaker.consecutive_failures = 0

    raised = None
    try:
        _run(storage_mod.store_chunk("vid-no-fallback", "user-x", 0, b"a" * 1024))
    except RuntimeError as e:
        raised = e
    assert raised is not None, (
        "store_chunk must REFUSE the fallback when ENABLE_PERSISTENT_CHUNK_FALLBACK "
        "is not set. iter89 made the dangerous /app path opt-in."
    )
    assert "fallback_disabled" in str(raised)
    # And the fallback directory must NOT have been created
    fallback_dir = tmp_path / "fallback" / "vid-no-fallback"
    assert not fallback_dir.exists(), "Fallback dir created despite refusal!"


def test_store_chunk_uses_fallback_when_env_var_enabled(monkeypatch, tmp_path):
    """With ENABLE_PERSISTENT_CHUNK_FALLBACK=true, iter83 behavior is
    restored — chunk lands on /app/.video_chunks."""
    from services import storage as storage_mod

    monkeypatch.setenv("ENABLE_PERSISTENT_CHUNK_FALLBACK", "true")
    monkeypatch.setattr(storage_mod, "PERSISTENT_CHUNK_DIR", str(tmp_path / "fallback"))
    monkeypatch.setattr(storage_mod, "PERSISTENT_CHUNK_FREE_MIN_BYTES", 1)

    async def _always_fail(*_a, **_kw):
        raise RuntimeError("simulated storage 500")
    monkeypatch.setattr(storage_mod, "put_object_with_retry", _always_fail)
    storage_mod.storage_breaker.consecutive_failures = 0

    result = _run(storage_mod.store_chunk("vid-fallback-on", "user-y", 0, b"b" * 1024))
    assert result["backend"] == "persistent_filesystem"
    assert os.path.exists(result["path"]), "Chunk should have been written to /app fallback"


def test_env_var_accepts_truthy_strings(monkeypatch, tmp_path):
    """The opt-in env var should accept "true"/"1"/"yes" case-insensitively."""
    from services import storage as storage_mod

    monkeypatch.setattr(storage_mod, "PERSISTENT_CHUNK_DIR", str(tmp_path / "fb"))
    monkeypatch.setattr(storage_mod, "PERSISTENT_CHUNK_FREE_MIN_BYTES", 1)

    async def _always_fail(*_a, **_kw):
        raise RuntimeError("storage 500")
    monkeypatch.setattr(storage_mod, "put_object_with_retry", _always_fail)
    storage_mod.storage_breaker.consecutive_failures = 0

    for truthy in ("true", "True", "TRUE", "1", "yes", "YES"):
        monkeypatch.setenv("ENABLE_PERSISTENT_CHUNK_FALLBACK", truthy)
        result = _run(storage_mod.store_chunk(f"vid-{truthy}", "user", 0, b"x"))
        assert result["backend"] == "persistent_filesystem", (
            f"ENABLE_PERSISTENT_CHUNK_FALLBACK={truthy!r} should enable fallback"
        )

    for falsy in ("false", "False", "0", "no", "", "anything-else"):
        monkeypatch.setenv("ENABLE_PERSISTENT_CHUNK_FALLBACK", falsy)
        raised = None
        try:
            _run(storage_mod.store_chunk(f"vid-{falsy or 'empty'}", "user", 0, b"x"))
        except RuntimeError as e:
            raised = e
        assert raised is not None and "fallback_disabled" in str(raised), (
            f"ENABLE_PERSISTENT_CHUNK_FALLBACK={falsy!r} must NOT enable fallback"
        )


# ---------------------------------------------------------------------------
# 2. Frontend: Try Recovery button gate is broadened
# ---------------------------------------------------------------------------

def test_recovery_button_shows_for_generic_processing_error():
    """iter89 broadened the gate — any chunked-video failure (except AI
    budget) should now show Try Recovery so users discover the recovery path."""
    header_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "components",
        "VideoAnalysisHeader.js",
    )
    with open(header_path, "r", encoding="utf-8") as f:
        src = f.read()
    # iter89: gate uses an "isAiBudgetError" exclusion rather than positive matching
    assert "isAiBudgetError" in src, (
        "iter89 must gate the Try Recovery button on `!isAiBudgetError` rather "
        "than positive missing-chunk regex — the positive regex was too narrow "
        "and missed the real production error format."
    )
    # The old over-restrictive AND clause must be gone
    assert "errLower.includes('unreadable')" not in src, (
        "iter89 removed the narrow regex; should not be present anymore"
    )


def test_recovery_button_hidden_for_ai_budget_error():
    """The exclusion must still hide the button for AI budget / quota errors
    so users don't get a misleading CTA when the failure has nothing to do
    with chunks."""
    header_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "components",
        "VideoAnalysisHeader.js",
    )
    with open(header_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "'budget'" in src or '"budget"' in src
    assert "'quota'" in src or '"quota"' in src
    assert "'balance'" in src or '"balance"' in src


# ---------------------------------------------------------------------------
# 3. Audit collection captures every fallback write
# ---------------------------------------------------------------------------

def test_fallback_writes_log_warn_for_audit_grep():
    """Every persistent_filesystem fallback write must emit a WARN log so
    production operators can grep `iter89` logs to see how often the
    fallback is being hit (and thus how risky an unverified PV is)."""
    storage_path = os.path.join(_BACKEND, "services", "storage.py")
    with open(storage_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "routed to persistent_filesystem fallback" in src, (
        "store_chunk must emit a distinctive WARN log when it routes to /app "
        "fallback. Operator grep target."
    )
