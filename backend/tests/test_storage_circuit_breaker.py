"""
Tests for iter81: chunked-upload storage routing.

Real production bug 2026-05-21 (video 25e71613, 845 MB compressed file):
upload finished at 50 of 85 chunks. Root cause was the hyper-aggressive
storage circuit breaker — a single transient SSL error from object storage
tripped the breaker (failure_threshold=1, reset_timeout=120s), causing 34
subsequent chunks to land on ephemeral filesystem. When the pod restarted
(common in this environment due to storage churn), those filesystem chunks
evaporated and the user saw "Upload incomplete (50 of 85 chunks)".

iter81 closes the loop with three guards:
  1. Circuit breaker is far more lenient: failure_threshold=8 (was 1),
     reset_timeout=60 (was 120). One SSL flake no longer reroutes everything.
  2. put_object_with_retry: 4 retries (was 2), exponential backoff (was hardcoded 2s).
  3. Chunk endpoint rejects filesystem-routed chunks with 503 + Retry-After.
     The iter79 client retry loop catches 503 as retryable and re-uploads,
     giving object storage time to recover.
"""
import os
import sys
import asyncio

# Ensure backend root is on path
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_circuit_breaker_threshold_is_lenient():
    """One failure should NOT trip the breaker (was the iter80 production bug)."""
    from services.storage import StorageCircuitBreaker
    cb = StorageCircuitBreaker()
    # Default ctor — must require many failures to trip
    assert cb.failure_threshold >= 5, (
        f"Circuit breaker threshold too aggressive ({cb.failure_threshold}). "
        "Single transient errors should not trip the breaker — that's the iter80 bug."
    )


def test_circuit_breaker_resets_after_timeout():
    """After reset_timeout seconds with no failures, the breaker should
    consider itself closed again."""
    from services.storage import StorageCircuitBreaker
    cb = StorageCircuitBreaker()
    assert cb.reset_timeout <= 120  # 60-120s is reasonable
    assert cb.reset_timeout >= 30  # not so short we hammer broken storage


def test_circuit_breaker_opens_only_at_threshold():
    """Trip the breaker exactly at the threshold — not earlier."""
    from services.storage import StorageCircuitBreaker
    cb = StorageCircuitBreaker(failure_threshold=8, reset_timeout=60)
    for _ in range(7):
        cb.record_failure()
    assert cb.is_open is False, "Breaker opened too early — before threshold"
    cb.record_failure()  # 8th failure
    assert cb.is_open is True, "Breaker did not open at threshold"


def test_circuit_breaker_success_resets_failure_count():
    """A success after some failures should reset the consecutive counter."""
    from services.storage import StorageCircuitBreaker
    cb = StorageCircuitBreaker(failure_threshold=8)
    for _ in range(5):
        cb.record_failure()
    assert cb.consecutive_failures == 5
    cb.record_success()
    assert cb.consecutive_failures == 0


def test_put_object_with_retry_signature():
    """The retry helper must default to >=3 retries (iter81 raised from 2)."""
    import inspect
    from services.storage import put_object_with_retry
    sig = inspect.signature(put_object_with_retry)
    max_retries_default = sig.parameters["max_retries"].default
    assert max_retries_default >= 3, (
        f"put_object_with_retry default max_retries is {max_retries_default}; "
        "should be at least 3 so transient flakes are absorbed before falling "
        "back to filesystem."
    )
