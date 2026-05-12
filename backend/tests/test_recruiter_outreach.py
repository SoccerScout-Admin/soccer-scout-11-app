"""Recruiter Lens — outreach emails + tracked clicks.

End-to-end flow:
  Coach → POST /api/lens-links {team_id, filters, recipient_email, ...}
  Backend stores lens_link, sends Resend email (or queues on quota), returns
  the tracked URL.
  Recipient → GET /api/lens-track/{token} → records click → 302 to
  /shared-team/{share_token}?filters

Tests focus on the auth boundary, click recording, tenant isolation, and the
filter→query-string mapping. We DON'T test the actual email send — that's
already covered by services/email_queue tests and Resend stays sandboxed.
"""
from __future__ import annotations

import uuid
import requests
import pytest

from tests.conftest import BASE_URL, run_async as _run_async


@pytest.fixture(scope="module")
def coach():
    email = f"lens-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "LensPass123", "name": "Lens Coach", "role": "coach"},
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
def team(coach):
    r = requests.post(
        f"{BASE_URL}/api/teams",
        params={"name": f"LensSquad-{uuid.uuid4().hex[:6]}", "season": "2026"},
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    t = r.json()
    yield t

    async def cleanup():
        from db import db
        await db.lens_link_clicks.delete_many({})
        await db.lens_links.delete_many({"user_id": coach["id"]})
        await db.teams.delete_one({"id": t["id"]})
        await db.users.delete_one({"id": coach["id"]})
    _run_async(cleanup())


# ---------- auth ----------

def test_create_lens_link_requires_auth(team):
    r = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {"class_of": "2027"},
            "recipient_email": "scout@example.com",
        },
    )
    assert r.status_code in (401, 403), r.text


def test_list_lens_links_requires_auth():
    r = requests.get(f"{BASE_URL}/api/lens-links")
    assert r.status_code in (401, 403)


# ---------- tenant isolation ----------

def test_cannot_create_lens_link_for_another_users_team(team, coach):
    other_email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": other_email, "password": "OtherPass1", "name": "Other", "role": "coach"},
    )
    assert r.status_code == 200, r.text
    other_token = r.json()["token"]

    # Try to create lens link for OUR team from the other user
    r = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {"class_of": "2027"},
            "recipient_email": "scout@example.com",
        },
        headers={"Authorization": f"Bearer {other_token}", "Content-Type": "application/json"},
    )
    assert r.status_code == 404, r.text  # Team not found (for that user)

    async def go():
        from db import db
        await db.users.delete_one({"email": other_email})
    _run_async(go())


# ---------- happy path ----------

def test_create_lens_link_returns_tracked_url(team, coach):
    r = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {"class_of": "2027", "position": "Forward"},
            "recipient_email": "scout@example.com",
            "recipient_name": "Coach Smith",
            "message": "These are my 2027 forwards.",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lens_link"]["click_count"] == 0
    assert body["lens_link"]["recipient_email"] == "scout@example.com"
    assert body["lens_link"]["recipient_name"] == "Coach Smith"
    # Tracked URL contains the tracking_token
    assert body["lens_link"]["tracking_token"] in body["tracked_url"]
    # Target URL (the eventual destination) preserves the filters
    assert "class_of=2027" in body["target_url"]
    assert "position=Forward" in body["target_url"]


def test_create_lens_link_auto_enables_team_share(team, coach):
    """If the team isn't publicly shared yet, creating a lens link should
    auto-grant a share_token so the recipient lands somewhere real."""
    # Make a brand new team that has NO share_token
    r = requests.post(
        f"{BASE_URL}/api/teams",
        params={"name": f"FreshTeam-{uuid.uuid4().hex[:6]}", "season": "2026"},
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    fresh = r.json()
    assert not fresh.get("share_token"), "Fresh team should not have share_token"

    r = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": fresh["id"],
            "filters": {"birth_year": "2009"},
            "recipient_email": "scout2@example.com",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lens_link"]["team_share_token"], "team_share_token should be auto-generated"

    async def go():
        from db import db
        await db.lens_links.delete_many({"team_id": fresh["id"]})
        await db.teams.delete_one({"id": fresh["id"]})
    _run_async(go())


# ---------- click tracking ----------

def test_clicking_tracked_url_logs_and_redirects(team, coach):
    """The public lens-track endpoint should 302 to /shared-team/{token}
    with the original filters appended, AND record a click."""
    create = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {"class_of": "2028", "position": "Midfielder"},
            "recipient_email": "scout3@example.com",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    assert create.status_code == 200, create.text
    body = create.json()
    tracking_token = body["lens_link"]["tracking_token"]
    lens_link_id = body["lens_link"]["id"]

    # Hit the tracker — disable redirect-following so we can inspect the 302
    track = requests.get(
        f"{BASE_URL}/api/lens-track/{tracking_token}",
        allow_redirects=False,
    )
    assert track.status_code in (302, 307), track.text
    location = track.headers["Location"]
    assert f"/shared-team/{body['lens_link']['team_share_token']}" in location
    assert "class_of=2028" in location
    assert "position=Midfielder" in location

    # Click is reflected on the lens link
    listed = requests.get(
        f"{BASE_URL}/api/lens-links",
        params={"team_id": team["id"]},
        headers=coach["headers"],
    )
    assert listed.status_code == 200
    rows = {r["id"]: r for r in listed.json()}
    assert rows[lens_link_id]["click_count"] == 1
    assert rows[lens_link_id]["last_clicked_at"] is not None


def test_multiple_clicks_increment_counter(team, coach):
    create = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {"class_of": "2029"},
            "recipient_email": "scout4@example.com",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    tracking_token = create.json()["lens_link"]["tracking_token"]
    lens_link_id = create.json()["lens_link"]["id"]

    for _ in range(3):
        requests.get(
            f"{BASE_URL}/api/lens-track/{tracking_token}",
            allow_redirects=False,
        )

    # GET /api/lens-links/{id}/clicks shows all 3
    detail = requests.get(
        f"{BASE_URL}/api/lens-links/{lens_link_id}/clicks",
        headers=coach["headers"],
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["lens_link"]["click_count"] == 3
    assert len(body["clicks"]) == 3


def test_bogus_tracking_token_redirects_to_home():
    """Unknown tokens should silently redirect without leaking existence info."""
    track = requests.get(
        f"{BASE_URL}/api/lens-track/totally-bogus-token-xyz",
        allow_redirects=False,
    )
    assert track.status_code in (302, 307)
    # Redirects to "/" (or absolute home) — NOT to a /shared-team page
    assert "/shared-team/" not in track.headers["Location"]


def test_clicks_endpoint_blocks_other_users(team, coach):
    """A coach can only see clicks for THEIR OWN lens links."""
    create = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {"position": "Defender"},
            "recipient_email": "scout5@example.com",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    lens_link_id = create.json()["lens_link"]["id"]

    # Register a different coach
    other_email = f"snoop-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": other_email, "password": "SnoopPw01", "name": "Snoop", "role": "coach"},
    )
    other_token = r.json()["token"]

    # Snoop tries to read OUR link's clicks
    bad = requests.get(
        f"{BASE_URL}/api/lens-links/{lens_link_id}/clicks",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert bad.status_code == 404

    async def go():
        from db import db
        await db.users.delete_one({"email": other_email})
    _run_async(go())


def test_list_lens_links_filters_by_team(team, coach):
    """The list endpoint should scope to a single team when team_id is passed."""
    r = requests.get(
        f"{BASE_URL}/api/lens-links",
        params={"team_id": team["id"]},
        headers=coach["headers"],
    )
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    # Every row belongs to that team
    for row in rows:
        assert row["team_id"] == team["id"]
        assert row["user_id"] == coach["id"]


# ---------- validation ----------

def test_invalid_email_returns_422(team, coach):
    r = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {},
            "recipient_email": "not-an-email",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    assert r.status_code == 422


def test_team_id_not_found_returns_404(coach):
    r = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": "non-existent-team-id",
            "filters": {},
            "recipient_email": "scout@example.com",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    assert r.status_code == 404


# ---------- iter59d: Hot Lead engagement-milestone notifications ----------

def test_single_click_does_not_trigger_hot_lead(team, coach):
    create = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {},
            "recipient_email": "lukewarm@example.com",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    tracking = create.json()["lens_link"]["tracking_token"]
    requests.get(f"{BASE_URL}/api/lens-track/{tracking}", allow_redirects=False)

    listed = requests.get(
        f"{BASE_URL}/api/lens-links",
        params={"team_id": team["id"]},
        headers=coach["headers"],
    )
    row = next(r for r in listed.json() if r["tracking_token"] == tracking)
    assert row["click_count"] == 1
    assert row["repeated_open_notified_at"] is None, (
        "Should not notify on a single click"
    )


def test_three_clicks_in_window_triggers_hot_lead(team, coach):
    """3 clicks total within 48h should set repeated_open_notified_at."""
    create = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {"class_of": "2027"},
            "recipient_email": "hot@example.com",
            "recipient_name": "Eager Coach",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    body = create.json()
    tracking = body["lens_link"]["tracking_token"]
    link_id = body["lens_link"]["id"]

    for _ in range(3):
        requests.get(f"{BASE_URL}/api/lens-track/{tracking}", allow_redirects=False)

    listed = requests.get(
        f"{BASE_URL}/api/lens-links",
        params={"team_id": team["id"]},
        headers=coach["headers"],
    )
    row = next(r for r in listed.json() if r["id"] == link_id)
    assert row["click_count"] == 3
    assert row["repeated_open_notified_at"] is not None, (
        "Should notify after 3 clicks in 48h"
    )


def test_hot_lead_does_not_re_fire_on_subsequent_clicks(team, coach):
    """Once notified, subsequent clicks must NOT re-fire the email — the
    repeated_open_notified_at timestamp stays pinned to the first trigger."""
    create = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {},
            "recipient_email": "repeated@example.com",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    tracking = create.json()["lens_link"]["tracking_token"]
    link_id = create.json()["lens_link"]["id"]

    # Cross the threshold
    for _ in range(3):
        requests.get(f"{BASE_URL}/api/lens-track/{tracking}", allow_redirects=False)
    first = requests.get(
        f"{BASE_URL}/api/lens-links",
        params={"team_id": team["id"]},
        headers=coach["headers"],
    ).json()
    initial_ts = next(r for r in first if r["id"] == link_id)["repeated_open_notified_at"]
    assert initial_ts is not None

    # Three more clicks — timestamp must not change
    for _ in range(3):
        requests.get(f"{BASE_URL}/api/lens-track/{tracking}", allow_redirects=False)
    second = requests.get(
        f"{BASE_URL}/api/lens-links",
        params={"team_id": team["id"]},
        headers=coach["headers"],
    ).json()
    later_row = next(r for r in second if r["id"] == link_id)
    assert later_row["click_count"] == 6
    assert later_row["repeated_open_notified_at"] == initial_ts


def test_old_clicks_outside_window_dont_count(team, coach):
    """If only 2 clicks fall inside the 48h window (others are stale), don't
    fire the notification — we backfill the click rows with old timestamps
    to simulate."""
    from datetime import datetime, timezone, timedelta

    create = requests.post(
        f"{BASE_URL}/api/lens-links",
        json={
            "team_id": team["id"],
            "filters": {},
            "recipient_email": "stale@example.com",
        },
        headers={**coach["headers"], "Content-Type": "application/json"},
    )
    tracking = create.json()["lens_link"]["tracking_token"]
    link_id = create.json()["lens_link"]["id"]

    # First click — backdate it to 3 days ago so it's outside the window
    requests.get(f"{BASE_URL}/api/lens-track/{tracking}", allow_redirects=False)
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

    async def backdate():
        from db import db
        # Backdate the first click row
        first_click = await db.lens_link_clicks.find_one(
            {"lens_link_id": link_id}, {"_id": 0},
        )
        await db.lens_link_clicks.update_one(
            {"id": first_click["id"]},
            {"$set": {"clicked_at": stale_ts}},
        )
    _run_async(backdate())

    # Now 2 fresh clicks — total click_count=3 but only 2 in window
    requests.get(f"{BASE_URL}/api/lens-track/{tracking}", allow_redirects=False)
    requests.get(f"{BASE_URL}/api/lens-track/{tracking}", allow_redirects=False)

    listed = requests.get(
        f"{BASE_URL}/api/lens-links",
        params={"team_id": team["id"]},
        headers=coach["headers"],
    ).json()
    row = next(r for r in listed if r["id"] == link_id)
    assert row["click_count"] == 3
    assert row["repeated_open_notified_at"] is None, (
        "Should not notify when only 2 of 3 clicks are inside the 48h window"
    )
