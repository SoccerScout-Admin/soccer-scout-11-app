"""
iter92 — Bulk Resume Picker.

After the 2026-05-23 Object Storage outage left a user with 13 paused
uploads, navigating to each match individually to re-pick the same files
was a 13-trip workflow. iter92 lets the user pick ALL files at once via a
single multi-file <input>; the modal matches each by (filename, exact byte
size) to a pending session and uploads them sequentially.
"""
import os
import sys
import asyncio
import uuid

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


def _payload():
    s = uuid.uuid4().hex[:10]
    return {"email": f"bulk-{s}@example.com", "password": "BulkPass2026!", "name": f"Bulk {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


async def _create_match(c, label):
    r = await c.post("/api/matches", json={
        "team_home": label, "team_away": "Opponent",
        "date": "2026-05-24", "competition": "Bulk Resume",
    })
    return r.json()["id"]


async def _init_upload(c, match_id, filename, file_size):
    r = await c.post("/api/videos/upload/init", json={
        "match_id": match_id, "filename": filename,
        "file_size": file_size, "content_type": "video/mp4",
    })
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# 1. The /api/me/pending-uploads response now exposes file_size in bytes
# ---------------------------------------------------------------------------

def test_pending_uploads_exposes_file_size_in_bytes():
    """iter92 needs exact-byte matching client-side. Pre-iter92 the response
    only had file_size_gb (rounded to 0.01 GB) which is way too lossy for
    file-matching (e.g. 850MB rounds to 0.79 GB but so does 870MB)."""
    async def run():
        c = await _client(_payload())
        try:
            mid = await _create_match(c, "Bytes Test Team")
            await _init_upload(c, mid, "bytes-test.mp4", 850 * 1024 * 1024)
            r = await c.get("/api/me/pending-uploads")
            assert r.status_code == 200
            sessions = r.json()["sessions"]
            assert len(sessions) >= 1
            session = next((s for s in sessions if s["filename"] == "bytes-test.mp4"), None)
            assert session is not None, "Test session not found in listing"
            assert "file_size" in session, (
                "iter92 requires file_size (raw bytes) for client-side exact matching"
            )
            assert session["file_size"] == 850 * 1024 * 1024, (
                f"file_size should be exact bytes, got {session['file_size']}"
            )
            # Also still has file_size_gb for the existing UI
            assert "file_size_gb" in session
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. Frontend: BulkResumeModal exists and wires correctly
# ---------------------------------------------------------------------------

def test_bulk_resume_modal_component_exists():
    modal_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "components",
        "BulkResumeModal.js",
    )
    assert os.path.isfile(modal_path)
    with open(modal_path, "r", encoding="utf-8") as f:
        src = f.read()
    # Required testids
    for tid in ("bulk-resume-modal", "bulk-resume-file-picker", "bulk-resume-start", "bulk-resume-modal-close"):
        assert f'data-testid="{tid}"' in src, f"missing testid: {tid}"


def test_bulk_resume_matches_by_exact_byte_size():
    """Filename alone is NOT enough — a coach with two different files named
    'game.mp4' from different matches must NOT cross-route."""
    modal_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "components",
        "BulkResumeModal.js",
    )
    with open(modal_path, "r", encoding="utf-8") as f:
        src = f.read()
    # The matching function must check BOTH filename AND file_size
    assert "filename === f.name" in src or "filename ===" in src
    assert "file_size === f.size" in src or "file_size ===" in src, (
        "Bulk picker must require exact file_size match — filename alone risks "
        "cross-routing files from different matches."
    )


def test_bulk_resume_modal_uses_existing_chunk_upload_flow():
    """The bulk picker must re-use /api/videos/upload/init (matches existing
    session by filename+size) and /api/videos/upload/chunk — not invent a
    new pipeline that could regress the iter80/89 storage safety."""
    modal_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "components",
        "BulkResumeModal.js",
    )
    with open(modal_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "/videos/upload/init" in src
    assert "/videos/upload/chunk" in src


def test_bulk_resume_modal_handles_503_gracefully():
    """The 503/storage-degraded path must surface a 'waiting-storage' status,
    not just spin forever silently."""
    modal_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "components",
        "BulkResumeModal.js",
    )
    with open(modal_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "waiting-storage" in src
    assert "503" in src
    # And uses exponential backoff like iter82
    assert "Math.pow" in src and "60000" in src, (
        "Bulk picker should use the same 60s-max backoff as iter82's "
        "uploadChunkWithRetry — otherwise it gives up too fast on transient outages."
    )


# ---------------------------------------------------------------------------
# 3. Banner wires the "Resume all" button
# ---------------------------------------------------------------------------

def test_resume_banner_renders_resume_all_button_for_multi_session_case():
    banner_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "components",
        "ResumeAcrossDevicesBanner.js",
    )
    with open(banner_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert 'data-testid="resume-all-btn"' in src
    # Imports the modal
    assert "BulkResumeModal" in src
    # The button is gated to total > 1 — no point showing for a single session
    assert "total > 1" in src
