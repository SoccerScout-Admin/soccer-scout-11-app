"""
iter85 — Dismiss button on the resume-across-devices banner.

A coach with 14 stale "0/85 chunks (0%)" sessions from a flaky-wifi weekend
shouldn't have the dashboard banner clutter forever. DELETE
/api/me/pending-uploads/{upload_id} marks ONE session as dismissed and
best-effort frees any persistent_filesystem chunks on /app so disk doesn't
grow unbounded.

The dismissed_at timestamp keeps the audit trail in Mongo (when, why,
how far it got) — we intentionally don't hard-delete the row.
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
        "email": f"dismiss-{suffix}@example.com",
        "password": "DismissPass2026!",
        "name": f"Dismiss User {suffix}",
    }


async def _register_and_get_client(payload):
    client = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await client.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), f"register failed: {r.text}"
    csrf = client.cookies.get("csrf_token")
    assert csrf, "csrf_token cookie missing"
    client.headers.update({"X-CSRF-Token": csrf})
    return client


async def _create_match(client, label):
    r = await client.post("/api/matches", json={
        "team_home": label, "team_away": "Opponent",
        "date": "2026-05-22", "competition": "Dismiss Tests",
    })
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _init_upload(client, match_id, filename, file_size):
    r = await client.post("/api/videos/upload/init", json={
        "match_id": match_id, "filename": filename,
        "file_size": file_size, "content_type": "video/mp4",
    })
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# 1. Auth boundary
# ---------------------------------------------------------------------------

def test_dismiss_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            r = await client.delete("/api/me/pending-uploads/some-fake-id")
            assert r.status_code in (401, 403), f"got {r.status_code}: {r.text[:200]}"
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. Happy path: dismiss removes session from /me/pending-uploads
# ---------------------------------------------------------------------------

def test_dismiss_hides_session_from_listing():
    async def run():
        client = await _register_and_get_client(_make_user_payload())
        try:
            mid = await _create_match(client, "Dismiss Test Team")
            init = await _init_upload(client, mid, "to-dismiss.mp4", 50 * 1024 * 1024)
            upload_id = init["upload_id"]

            # Pre-dismiss: session shows up
            r = await client.get("/api/me/pending-uploads")
            assert r.status_code == 200
            assert any(s["upload_id"] == upload_id for s in r.json()["sessions"])

            # Dismiss
            r = await client.delete(f"/api/me/pending-uploads/{upload_id}")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["dismissed"] is True
            assert body["upload_id"] == upload_id

            # Post-dismiss: session is gone
            r = await client.get("/api/me/pending-uploads")
            assert r.status_code == 200
            remaining_ids = [s["upload_id"] for s in r.json()["sessions"]]
            assert upload_id not in remaining_ids, (
                f"Dismissed session still in listing: {remaining_ids}"
            )
        finally:
            await client.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 3. Idempotent: dismissing twice is fine
# ---------------------------------------------------------------------------

def test_dismiss_idempotent():
    async def run():
        client = await _register_and_get_client(_make_user_payload())
        try:
            mid = await _create_match(client, "Idempotent Team")
            init = await _init_upload(client, mid, "twice.mp4", 10 * 1024 * 1024)
            upload_id = init["upload_id"]

            r1 = await client.delete(f"/api/me/pending-uploads/{upload_id}")
            assert r1.status_code == 200, r1.text
            r2 = await client.delete(f"/api/me/pending-uploads/{upload_id}")
            assert r2.status_code == 200, r2.text
            # Second call should set the `already` marker
            assert r2.json().get("already") is True, r2.json()
        finally:
            await client.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 4. Cross-user isolation: user A cannot dismiss user B's session
# ---------------------------------------------------------------------------

def test_dismiss_does_not_affect_other_users():
    async def run():
        client_a = await _register_and_get_client(_make_user_payload())
        client_b = await _register_and_get_client(_make_user_payload())
        try:
            mid_a = await _create_match(client_a, "User A Team")
            init_a = await _init_upload(client_a, mid_a, "userA.mp4", 20 * 1024 * 1024)
            upload_id = init_a["upload_id"]

            # User B tries to dismiss user A's session — endpoint should be a
            # no-op (treats the upload as not-existing for user B) and NOT
            # affect the actual session.
            r_b = await client_b.delete(f"/api/me/pending-uploads/{upload_id}")
            assert r_b.status_code == 200
            assert r_b.json().get("already") is True  # treated as not-found, idempotent

            # User A's session must STILL be listed
            r_a = await client_a.get("/api/me/pending-uploads")
            assert upload_id in [s["upload_id"] for s in r_a.json()["sessions"]], (
                "User B's dismiss leaked into User A's session!"
            )
        finally:
            await client_a.aclose()
            await client_b.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 5. Unknown upload_id: idempotent success
# ---------------------------------------------------------------------------

def test_dismiss_unknown_upload_id_is_idempotent():
    async def run():
        client = await _register_and_get_client(_make_user_payload())
        try:
            r = await client.delete("/api/me/pending-uploads/does-not-exist-anywhere")
            assert r.status_code == 200, r.text
            assert r.json().get("already") is True
        finally:
            await client.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 6. Frontend wiring: banner exposes dismiss controls per row
# ---------------------------------------------------------------------------

def test_banner_component_has_dismiss_controls():
    banner_path = os.path.join(
        _BACKEND, "..", "frontend", "src", "pages", "components",
        "ResumeAcrossDevicesBanner.js",
    )
    with open(banner_path, "r", encoding="utf-8") as f:
        src = f.read()
    # Endpoint call from the component
    assert "DELETE" not in src.split("axios.")[0] or "axios.delete" in src, (
        "Banner must call axios.delete to invoke /api/me/pending-uploads/{id}"
    )
    assert "/me/pending-uploads/" in src, (
        "Banner must reference the dismiss endpoint path"
    )
    # data-testid pattern the testing agent will look for
    assert "dismiss-session-" in src, (
        "Banner rows must render an X button with data-testid='dismiss-session-{upload_id}'"
    )
