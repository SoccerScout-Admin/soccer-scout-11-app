"""iter59e: filter-aware OG card endpoints for Recruiter Lens unfurls.

When a coach pastes a filtered Lens URL into Slack/iMessage/email,
crawlers should see a rich preview with:
- "RECRUITER LENS" eyebrow (green, not blue)
- Filter chip baked into the image ("Class of 2027 · Forwards")
- Accurate match count in the og:description

Tests cover:
- 404 for invalid share tokens
- Filter summary appears in og:description
- og:image points at /lens-image.png with same query params
- SPA redirect target preserves filter params
- Match count accurately reflects filter intersection (class_of + position)
- PNG endpoint returns valid image bytes
- Generic full-squad lens (no filters) still renders cleanly
"""
from __future__ import annotations

import uuid
import requests
import pytest

from tests.conftest import BASE_URL, run_async as _run_async


@pytest.fixture(scope="module")
def coach():
    email = f"oglens-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "OgLensPw1", "name": "OG Lens Coach", "role": "coach"},
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
def shared_team_with_demographics(coach):
    """A team with a known mix of grades + positions for filter-intersection tests."""
    r = requests.post(
        f"{BASE_URL}/api/teams",
        params={"name": f"OGLensTeam-{uuid.uuid4().hex[:6]}", "season": "2026"},
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    team = r.json()

    roster = [
        # Three 2027-class forwards (matches class_of=2027 + position=Forward)
        {"name": "Senior FW A", "number": 9, "position": "Forward",
         "birth_year": 2008, "current_grade": "11th (Junior)"},
        {"name": "Senior FW B", "number": 10, "position": "Forward",
         "birth_year": 2008, "current_grade": "11th (Junior)"},
        {"name": "Senior FW C", "number": 11, "position": "Forward",
         "birth_year": 2008, "current_grade": "11th (Junior)"},
        # 2027 midfielder (class_of=2027 only, NOT position=Forward)
        {"name": "Junior Mid", "number": 8, "position": "Midfielder",
         "birth_year": 2008, "current_grade": "11th (Junior)"},
        # 2028 forward (position=Forward only, NOT class_of=2027)
        {"name": "Soph FW", "number": 7, "position": "Forward",
         "birth_year": 2009, "current_grade": "10th (Sophomore)"},
    ]
    for p in roster:
        rr = requests.post(
            f"{BASE_URL}/api/players",
            json={"team_id": team["id"], **p},
            headers={**coach["headers"], "Content-Type": "application/json"},
        )
        assert rr.status_code == 200, rr.text

    # Enable team share
    rr = requests.post(
        f"{BASE_URL}/api/teams/{team['id']}/share",
        headers=coach["headers"],
    )
    assert rr.status_code == 200, rr.text
    share_token = rr.json()["share_token"]

    yield {"team": team, "share_token": share_token}

    async def cleanup():
        from db import db
        await db.players.delete_many({"team_ids": team["id"]})
        await db.teams.delete_one({"id": team["id"]})
        await db.users.delete_one({"id": coach["id"]})
    _run_async(cleanup())


# ---------- HTML unfurl page ----------

def test_unknown_share_token_returns_404():
    r = requests.get(f"{BASE_URL}/api/og/team/totallybogus/lens?class_of=2027")
    assert r.status_code == 404


def test_lens_unfurl_html_contains_filter_summary(shared_team_with_demographics):
    token = shared_team_with_demographics["share_token"]
    r = requests.get(
        f"{BASE_URL}/api/og/team/{token}/lens",
        params={"class_of": "2027", "position": "Forward"},
    )
    assert r.status_code == 200, r.text
    html = r.text
    # Title + description include the human filter summary
    assert "Class of 2027" in html
    assert "Forwards" in html
    # og:image points at /lens-image.png with same params
    assert "/lens-image.png" in html
    assert "class_of=2027" in html
    assert "position=Forward" in html


def test_lens_unfurl_redirects_to_filtered_spa_route(shared_team_with_demographics):
    token = shared_team_with_demographics["share_token"]
    r = requests.get(
        f"{BASE_URL}/api/og/team/{token}/lens",
        params={"class_of": "2027"},
    )
    assert r.status_code == 200
    # window.location.replace points at the filtered SPA path
    assert f'/shared-team/{token}?class_of=2027' in r.text


def test_lens_unfurl_no_filters_renders_full_squad(shared_team_with_demographics):
    """Calling /lens without any query params should still render — it just
    labels the card as "Full Squad" instead of a specific filter."""
    token = shared_team_with_demographics["share_token"]
    r = requests.get(f"{BASE_URL}/api/og/team/{token}/lens")
    assert r.status_code == 200
    assert "Full Squad" in r.text


# ---------- match-count accuracy ----------

def test_lens_unfurl_match_count_reflects_intersection(shared_team_with_demographics):
    """class_of=2027 + position=Forward should match exactly 3 of 5 players
    on the fixture roster (3 Junior FWs; the Junior Mid + Soph FW each fail
    one of the two criteria)."""
    token = shared_team_with_demographics["share_token"]
    r = requests.get(
        f"{BASE_URL}/api/og/team/{token}/lens",
        params={"class_of": "2027", "position": "Forward"},
    )
    assert r.status_code == 200
    # Description string format: "3 of 5 players match Class of 2027 · Forwards"
    assert "3 of 5" in r.text


def test_lens_unfurl_birth_year_filter(shared_team_with_demographics):
    """birth_year=2008 should match the 4 Juniors (3 FWs + 1 Mid)."""
    token = shared_team_with_demographics["share_token"]
    r = requests.get(
        f"{BASE_URL}/api/og/team/{token}/lens",
        params={"birth_year": "2008"},
    )
    assert r.status_code == 200
    assert "4 of 5" in r.text


# ---------- PNG image endpoint ----------

def test_lens_image_returns_png_bytes(shared_team_with_demographics):
    token = shared_team_with_demographics["share_token"]
    r = requests.get(
        f"{BASE_URL}/api/og/team/{token}/lens-image.png",
        params={"class_of": "2027", "position": "Forward"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    # PNG magic header
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    # Reasonable size — empty image would be <1KB
    assert len(r.content) > 5000


def test_lens_image_404_for_unknown_token():
    r = requests.get(f"{BASE_URL}/api/og/team/bogus/lens-image.png")
    assert r.status_code == 404
