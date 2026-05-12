"""iter59: Recruiter Lens — public team view MUST expose birth_year +
current_grade so URL-driven recruiter filters (Class of YYYY, U17) can
render on the public dossier. Same regression class as the iter58 player
dossier fix.
"""
from __future__ import annotations

import uuid
import requests
import pytest

from tests.conftest import BASE_URL, run_async as _run_async


@pytest.fixture(scope="module")
def coach():
    email = f"recruiter-lens-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "RLPass1234", "name": "Lens Coach", "role": "coach"},
    )
    if r.status_code != 200:
        pytest.skip(f"register failed: {r.status_code} {r.text}")
    data = r.json()
    return {
        "id": data["user"]["id"],
        "email": email,
        "headers": {"Authorization": f"Bearer {data['token']}"},
    }


@pytest.fixture(scope="module")
def shared_team_with_roster(coach):
    # Create team
    r = requests.post(
        f"{BASE_URL}/api/teams",
        params={"name": f"LensTeam-{uuid.uuid4().hex[:6]}", "season": "2026"},
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    team = r.json()
    # Three players with mixed demographics
    roster = [
        {"name": "Senior Striker", "number": 9, "position": "Forward",
         "birth_year": 2007, "current_grade": "12th (Senior)"},
        {"name": "Junior Mid", "number": 8, "position": "Midfielder",
         "birth_year": 2008, "current_grade": "11th (Junior)"},
        {"name": "Soph Defender", "number": 4, "position": "Defender",
         "birth_year": 2009, "current_grade": "10th (Sophomore)"},
    ]
    for p in roster:
        r = requests.post(
            f"{BASE_URL}/api/players",
            json={"team_id": team["id"], **p},
            headers={**coach["headers"], "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text
    # Toggle share
    r = requests.post(
        f"{BASE_URL}/api/teams/{team['id']}/share",
        headers=coach["headers"],
    )
    assert r.status_code == 200, r.text
    token = r.json()["share_token"]
    yield {"team": team, "share_token": token}

    async def cleanup():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
        await db.teams.delete_one({"id": team["id"]})
        await db.users.delete_one({"id": coach["id"]})
    _run_async(cleanup())


def test_public_team_returns_birth_year(shared_team_with_roster):
    """Public team payload MUST include birth_year on each player."""
    token = shared_team_with_roster["share_token"]
    r = requests.get(f"{BASE_URL}/api/shared/team/{token}")
    assert r.status_code == 200, r.text
    body = r.json()
    by_name = {p["name"]: p for p in body["players"]}
    assert by_name["Senior Striker"]["birth_year"] == 2007
    assert by_name["Junior Mid"]["birth_year"] == 2008
    assert by_name["Soph Defender"]["birth_year"] == 2009


def test_public_team_returns_current_grade(shared_team_with_roster):
    """And current_grade — for Class of YYYY recruiter filters."""
    token = shared_team_with_roster["share_token"]
    r = requests.get(f"{BASE_URL}/api/shared/team/{token}")
    body = r.json()
    by_name = {p["name"]: p for p in body["players"]}
    assert by_name["Senior Striker"]["current_grade"] == "12th (Senior)"
    assert by_name["Junior Mid"]["current_grade"] == "11th (Junior)"


def test_public_team_omits_internal_fields(shared_team_with_roster):
    """Internal fields like user_id, team_ids, profile_pic_path stay private."""
    token = shared_team_with_roster["share_token"]
    r = requests.get(f"{BASE_URL}/api/shared/team/{token}")
    body = r.json()
    for p in body["players"]:
        assert "user_id" not in p, "user_id leaked on public team view"
        assert "team_ids" not in p, "team_ids leaked on public team view"
        assert "profile_pic_path" not in p
