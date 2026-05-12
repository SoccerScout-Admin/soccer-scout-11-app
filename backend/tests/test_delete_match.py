"""Single-match DELETE endpoint coverage.

Verifies that DELETE /api/matches/{id}:
- Requires auth
- Returns 200 + {status: deleted, id} on success
- Removes the match document
- Returns 404 for unknown ids
- Returns 404 when another user tries to delete someone else's match
  (i.e. enforces owner scoping so cross-user deletes are rejected)
- Cascades: clips / analyses / markers for the match's video are hard-deleted,
  and the video itself is soft-deleted (restorable via the 24h window)
"""
from __future__ import annotations

import uuid
import pytest

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: F401


def _auth_as(email: str, password: str, api_client) -> dict:
    resp = api_client.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
    )
    if resp.status_code != 200:
        pytest.skip(f"Auth failed for {email}: {resp.status_code} {resp.text}")
    token = resp.json().get("token") or resp.json().get("access_token")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _create_match(api_client, headers, home="DELETEME", away="DUMMY") -> str:
    resp = api_client.post(
        f"{BASE_URL}/api/matches",
        headers=headers,
        json={
            "team_home": home,
            "team_away": away,
            "date": "2026-04-30",
            "competition": "Test",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_delete_match_requires_auth(api_client):
    resp = api_client.delete(f"{BASE_URL}/api/matches/{uuid.uuid4()}")
    assert resp.status_code in (401, 403), resp.text


def test_delete_match_unknown_id_returns_404(api_client, auth_headers):
    resp = api_client.delete(
        f"{BASE_URL}/api/matches/does-not-exist-{uuid.uuid4()}",
        headers=auth_headers,
    )
    assert resp.status_code == 404, resp.text


def test_delete_match_happy_path(api_client, auth_headers):
    match_id = _create_match(api_client, auth_headers)

    # Sanity: the match exists
    resp = api_client.get(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text

    # Delete it
    resp = api_client.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"status": "deleted", "id": match_id}

    # GET now 404s
    resp = api_client.get(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers)
    assert resp.status_code == 404


def test_delete_match_cross_user_rejected(api_client, auth_headers):
    """A match owned by testcoach must not be deletable by a different user."""
    owner_match_id = _create_match(api_client, auth_headers, home="OWNER", away="MINE")

    # Register a throwaway user
    throwaway_email = f"throwaway-{uuid.uuid4().hex[:8]}@example.com"
    reg = api_client.post(
        f"{BASE_URL}/api/auth/register",
        json={
            "name": "Throwaway",
            "email": throwaway_email,
            "password": "Throwaway12345!",
            "role": "coach",
        },
    )
    if reg.status_code != 200:
        # Clean up owner's match even if signup fails
        api_client.delete(f"{BASE_URL}/api/matches/{owner_match_id}", headers=auth_headers)
        pytest.skip(f"Could not register throwaway user: {reg.status_code} {reg.text}")

    other_token = reg.json().get("token") or reg.json().get("access_token")
    other_headers = {
        "Authorization": f"Bearer {other_token}",
        "Content-Type": "application/json",
    }

    # Other user's DELETE must NOT succeed
    resp = api_client.delete(
        f"{BASE_URL}/api/matches/{owner_match_id}", headers=other_headers
    )
    assert resp.status_code == 404, resp.text

    # Owner's match still exists
    resp = api_client.get(f"{BASE_URL}/api/matches/{owner_match_id}", headers=auth_headers)
    assert resp.status_code == 200

    # Clean up
    api_client.delete(f"{BASE_URL}/api/matches/{owner_match_id}", headers=auth_headers)


def test_delete_match_cascades_clips_analyses_markers(api_client, auth_headers):
    """When a match has a video_id, cascade-delete clips/analyses/markers and
    soft-delete the video document."""
    from db import db  # async Motor client

    match_id = _create_match(api_client, auth_headers, home="CASCADE", away="TEST")
    fake_video_id = f"vid-{uuid.uuid4()}"

    async def _seed_video_and_derived():
        # Attach a fake video id to the match
        await db.matches.update_one({"id": match_id}, {"$set": {"video_id": fake_video_id}})
        await db.videos.insert_one({
            "id": fake_video_id,
            "user_id": None,  # filled below
            "is_deleted": False,
        })
        # We don't know the owner's user_id from the API — fetch it from the match doc
        m = await db.matches.find_one({"id": match_id}, {"_id": 0, "user_id": 1})
        uid = m["user_id"]
        await db.videos.update_one({"id": fake_video_id}, {"$set": {"user_id": uid}})
        await db.clips.insert_one({"id": f"c-{uuid.uuid4()}", "video_id": fake_video_id, "user_id": uid})
        await db.analyses.insert_one({"id": f"a-{uuid.uuid4()}", "video_id": fake_video_id, "user_id": uid})
        await db.markers.insert_one({"id": f"m-{uuid.uuid4()}", "video_id": fake_video_id, "user_id": uid})

    _run_async(_seed_video_and_derived())

    # Delete via API
    resp = api_client.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers)
    assert resp.status_code == 200, resp.text

    async def _assert_cascade():
        assert await db.clips.count_documents({"video_id": fake_video_id}) == 0
        assert await db.analyses.count_documents({"video_id": fake_video_id}) == 0
        assert await db.markers.count_documents({"video_id": fake_video_id}) == 0
        vid = await db.videos.find_one({"id": fake_video_id}, {"_id": 0})
        assert vid is not None, "video document should still exist (soft-deleted)"
        assert vid.get("is_deleted") is True
        assert vid.get("deleted_at")
        # Clean up the fake video doc so it doesn't linger
        await db.videos.delete_one({"id": fake_video_id})

    _run_async(_assert_cascade())
