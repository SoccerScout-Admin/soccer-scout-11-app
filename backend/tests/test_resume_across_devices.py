"""
iter84 — Resume Across Devices.

GET /api/me/pending-uploads must:
  1. Return only the current user's incomplete chunked-upload sessions.
  2. Join with the matches collection to surface a human label per session.
  3. Cap results at 20 so a coach with hundreds of stalled sessions doesn't
     blow up the dashboard.
  4. Skip sessions whose status is `completed` (those are done — no resume).
  5. Refuse unauthenticated callers.

Auth wiring follows the same `get_current_user` cookie-token flow used by
the other /api/me/* endpoints — see tests/test_cookie_auth_migration.py.
"""
import os
import sys
import uuid

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


def _make_user_payload():
    suffix = uuid.uuid4().hex[:10]
    return {
        "email": f"resume-{suffix}@example.com",
        "password": "ResumePass2026!",
        "name": f"Resume User {suffix}",
    }


async def _register_and_get_client(payload):
    """Register a user and return an httpx.AsyncClient with the auth cookie set
    and the X-CSRF-Token header pre-populated so state-changing calls work."""
    # Persistent client so the HttpOnly auth cookie is carried across calls
    client = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await client.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    # CSRF protection requires the double-submit cookie pattern — read the
    # csrf_token cookie set during register and echo it on every POST.
    csrf = client.cookies.get("csrf_token")
    assert csrf, "csrf_token cookie missing after register"
    client.headers.update({"X-CSRF-Token": csrf})
    return client


async def _create_match(client, label):
    r = await client.post("/api/matches", json={
        "team_home": label, "team_away": "Opponent",
        "date": "2026-05-21", "competition": "Test League",
    })
    assert r.status_code in (200, 201), f"create match failed: {r.text}"
    return r.json()["id"]


async def _init_upload(client, match_id, filename, file_size):
    r = await client.post("/api/videos/upload/init", json={
        "match_id": match_id,
        "filename": filename,
        "file_size": file_size,
        "content_type": "video/mp4",
    })
    assert r.status_code == 200, f"init failed: {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# 1. Auth boundary
# ---------------------------------------------------------------------------

def test_me_pending_uploads_requires_auth():
    """Anonymous callers must NOT see anyone's pending uploads."""
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            r = await client.get("/api/me/pending-uploads")
            # 401/403 both acceptable — anything but 200 with sessions
            assert r.status_code in (401, 403), f"Expected auth error, got {r.status_code}: {r.text[:200]}"
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. Empty state
# ---------------------------------------------------------------------------

def test_me_pending_uploads_empty_for_fresh_user():
    async def run():
        payload = _make_user_payload()
        client = await _register_and_get_client(payload)
        try:
            r = await client.get("/api/me/pending-uploads")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body == {"count": 0, "sessions": []}
        finally:
            await client.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 3. Real session shows up after init
# ---------------------------------------------------------------------------

def test_me_pending_uploads_lists_initialized_sessions():
    """After calling /videos/upload/init for two matches, both sessions must
    show in the cross-device list with the correct match label and 0% progress."""
    async def run():
        payload = _make_user_payload()
        client = await _register_and_get_client(payload)
        try:
            mid_a = await _create_match(client, "Team A")
            mid_b = await _create_match(client, "Team B")
            await _init_upload(client, mid_a, "game-a.mp4", 850 * 1024 * 1024)
            await _init_upload(client, mid_b, "game-b.mp4", 1200 * 1024 * 1024)

            r = await client.get("/api/me/pending-uploads")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["count"] == 2, body
            labels = [s["match_label"] for s in body["sessions"]]
            filenames = [s["filename"] for s in body["sessions"]]
            assert "Team A vs Opponent" in labels
            assert "Team B vs Opponent" in labels
            assert "game-a.mp4" in filenames
            assert "game-b.mp4" in filenames
            # Both still at 0% (no chunks uploaded yet)
            for s in body["sessions"]:
                assert s["chunks_received"] == 0
                assert s["progress_pct"] == 0
                assert s["status"] in ("initialized", "in_progress")
                assert s["total_chunks"] >= 1
        finally:
            await client.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 4. Cross-user isolation
# ---------------------------------------------------------------------------

def test_me_pending_uploads_does_not_leak_other_users():
    """User A's pending uploads must NEVER show up in user B's list."""
    async def run():
        payload_a = _make_user_payload()
        payload_b = _make_user_payload()
        client_a = await _register_and_get_client(payload_a)
        client_b = await _register_and_get_client(payload_b)
        try:
            mid_a = await _create_match(client_a, "User A Team")
            await _init_upload(client_a, mid_a, "userA-game.mp4", 500 * 1024 * 1024)

            # User B sees nothing
            r_b = await client_b.get("/api/me/pending-uploads")
            assert r_b.status_code == 200
            assert r_b.json()["count"] == 0, "User B should not see User A's pending upload"

            # User A still sees their own
            r_a = await client_a.get("/api/me/pending-uploads")
            assert r_a.status_code == 200
            assert r_a.json()["count"] == 1
            assert r_a.json()["sessions"][0]["filename"] == "userA-game.mp4"
        finally:
            await client_a.aclose()
            await client_b.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 5. Frontend banner component is importable from the Dashboard
# ---------------------------------------------------------------------------

def test_dashboard_imports_resume_across_devices_banner():
    """Grep-level guard: regression check that the banner stays wired in."""
    dashboard_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "Dashboard.js"
    )
    with open(dashboard_path, "r", encoding="utf-8") as f:
        src = f.read()
    assert "ResumeAcrossDevicesBanner" in src, (
        "Dashboard.js must import and render <ResumeAcrossDevicesBanner /> — "
        "otherwise the new endpoint is unreachable from the UI."
    )
    assert "<ResumeAcrossDevicesBanner" in src, (
        "Banner must be rendered, not just imported."
    )


def test_banner_component_file_exists():
    banner_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "components",
        "ResumeAcrossDevicesBanner.js",
    )
    assert os.path.isfile(banner_path), f"{banner_path} must exist"
    with open(banner_path, "r", encoding="utf-8") as f:
        src = f.read()
    # data-testids the testing agent will look for
    assert 'data-testid="resume-across-devices-banner"' in src
    assert 'data-testid="resume-across-devices-toggle"' in src
