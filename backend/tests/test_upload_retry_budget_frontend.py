"""
iter82: lock down the new client-side retry budget so a future refactor
doesn't quietly drop it back to 6 (which only covers ~2 minutes of object
storage outage — too short for the real production hiccups we've seen).
"""
import os
import re


_FRONTEND_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "frontend", "src", "pages", "MatchDetail.js",
)


def _read_source():
    with open(_FRONTEND_FILE, "r", encoding="utf-8") as f:
        return f.read()


def test_upload_chunk_retry_budget_min_20():
    """uploadChunkWithRetry must default to >=20 retries — covers ~15min outages."""
    src = _read_source()
    match = re.search(r"uploadChunkWithRetry\s*=\s*async[^=]*maxRetries\s*=\s*(\d+)", src)
    assert match, "Could not find uploadChunkWithRetry default in MatchDetail.js"
    assert int(match.group(1)) >= 20, (
        f"uploadChunkWithRetry default is {match.group(1)}; iter82 set this to 20 "
        "so the client absorbs real ~5-15min object-storage outages instead of "
        "alerting the user with 'Upload interrupted' after ~2 minutes."
    )


def test_upload_call_passes_retry_budget_min_20():
    """The actual call site inside handleChunkedUpload must also use >=20."""
    src = _read_source()
    # Look for the explicit retry arg passed to uploadChunkWithRetry in the loop
    match = re.search(r"uploadChunkWithRetry\([^)]*?,\s*(\d+)\s*,", src, flags=re.DOTALL)
    assert match, "Could not find uploadChunkWithRetry call site in MatchDetail.js"
    assert int(match.group(1)) >= 20, (
        f"uploadChunkWithRetry call passes maxRetries={match.group(1)}; should be >=20."
    )


def test_failure_handler_refreshes_pending_uploads_banner():
    """When an upload fails, fetchPendingUploads must be called inside the catch
    so the user immediately sees the orange resume banner without reloading."""
    src = _read_source()
    # The catch block of handleChunkedUpload should call fetchPendingUploads.
    catch_block = re.search(
        r"catch \(err\) \{\s*console\.error\('Chunked upload failed:.*?finally",
        src, flags=re.DOTALL,
    )
    assert catch_block, "Could not locate handleChunkedUpload catch block"
    assert "fetchPendingUploads" in catch_block.group(0), (
        "handleChunkedUpload catch block must call fetchPendingUploads() so the "
        "Incomplete-upload banner refreshes without forcing the user to reload."
    )


def test_503_gets_friendly_status_message():
    """503 responses (storage degraded) should produce a friendlier status
    than the generic 'Chunk failed' wording."""
    src = _read_source()
    assert "Storage temporarily slow" in src, (
        "Expected friendly 'Storage temporarily slow' status for 503s — iter82 "
        "distinguishes transient storage outages from real chunk failures so "
        "the user understands why their upload is waiting."
    )
