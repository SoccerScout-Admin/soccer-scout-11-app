"""iter59: public player dossier MUST include birth_year + current_grade.

This was a real regression — `_build_profile_payload(public=True)` was
filtering them out, so recruiters/scouts viewing a shared link could not
see age-group or graduation year.
"""
from __future__ import annotations

import uuid
import requests
import pytest

from tests.conftest import BASE_URL, run_async as _run_async


@pytest.fixture(scope="module")
def coach():
    email = f"demo-pub-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "PubPass123", "name": "Demo Pub Coach", "role": "coach"},
    )
    if r.status_code != 200:
        pytest.skip(f"register failed: {r.status_code} {r.text}")
    body = r.json()
    return {
        "id": body["user"]["id"],
        "email": email,
        "headers": {"Authorization": f"Bearer {body['token']}"},
    }


@pytest.fixture(scope="module")
def player_with_demographics(coach):
    """Create a player with birth_year + current_grade + a public share token."""
    r = requests.post(
        f"{BASE_URL}/api/players",
        json={
            "name": "Demo Public",
            "number": 9,
            "position": "Forward",
            "birth_year": 2009,
            "current_grade": "10th (Sophomore)",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    player = r.json()
    share = requests.post(
        f"{BASE_URL}/api/players/{player['id']}/share",
        headers=coach["headers"],
    )
    assert share.status_code == 200, share.text
    token = share.json()["share_token"]
    yield {"player": player, "share_token": token}

    async def cleanup():
        from db import db
        await db.players.delete_one({"id": player["id"]})
        await db.users.delete_one({"id": coach["id"]})
    _run_async(cleanup())


def test_public_dossier_includes_birth_year(player_with_demographics):
    """The /api/shared/player/{token} response MUST surface birth_year."""
    token = player_with_demographics["share_token"]
    r = requests.get(f"{BASE_URL}/api/shared/player/{token}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["player"]["birth_year"] == 2009


def test_public_dossier_includes_current_grade(player_with_demographics):
    """And current_grade — so recruiters can see graduation year."""
    token = player_with_demographics["share_token"]
    r = requests.get(f"{BASE_URL}/api/shared/player/{token}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["player"]["current_grade"] == "10th (Sophomore)"


def test_public_dossier_omits_internal_fields(player_with_demographics):
    """Internal fields like user_id and profile_pic_path stay private."""
    token = player_with_demographics["share_token"]
    r = requests.get(f"{BASE_URL}/api/shared/player/{token}")
    body = r.json()
    assert "user_id" not in body["player"], "user_id leaked on public dossier"
    assert "profile_pic_path" not in body["player"]
