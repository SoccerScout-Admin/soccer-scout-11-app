"""Scout listings board — create / list / verify / contact redaction.

Verifies:
- Anonymous GET /scout-listings returns sorted verified listings with contact fields redacted
- Unverified listings hidden from public feed by default
- POST /scout-listings rejected for users without scout/admin role (403)
- Create happy path with all fields
- PATCH resets verified=False (re-moderation on edit)
- DELETE hard-deletes
- Filters: positions, grad_years, level, region, q, verified_only
- Admin verify / unverify endpoints
- Detail endpoint: contact hidden for anon, visible for authed
- Controlled-list validation: bad position, bad level, out-of-range year -> 400
"""
from __future__ import annotations

import os
import uuid
import pytest
import requests

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: F401


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def scout_user():
    email = f"scout-{uuid.uuid4().hex[:8]}@example.com"
    pw = "ScoutPass123"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": pw, "name": "Test Scout", "role": "scout"},
    )
    if r.status_code != 200:
        pytest.skip(f"Could not register scout: {r.status_code} {r.text}")
    data = r.json()
    return {
        "email": email,
        "token": data["token"],
        "id": data["user"]["id"],
        "headers": {"Authorization": f"Bearer {data['token']}", "Content-Type": "application/json"},
    }


@pytest.fixture(scope="module")
def coach_user():
    """A user with role=coach — should NOT be able to create listings."""
    email = f"coach-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "CoachPass123", "name": "Test Coach", "role": "coach"},
    )
    if r.status_code != 200:
        pytest.skip(f"Could not register coach: {r.status_code} {r.text}")
    tok = r.json()["token"]
    return {"headers": {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}}


@pytest.fixture(scope="module")
def admin_user():
    # Use the pre-seeded admin test account
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "testcoach@demo.com", "password": "password123"},
    )
    if r.status_code != 200 or r.json().get("user", {}).get("role") not in ("admin", "owner"):
        pytest.skip("admin test account not available")
    tok = r.json()["token"]
    return {"headers": {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}}


VALID_PAYLOAD = {
    "school_name": "Pytest University",
    "website_url": "https://pytest.example.com",
    "positions": ["CB", "CM"],
    "grad_years": [2027, 2028],
    "level": "NCAA D2",
    "region": "Midwest, Test Region",
    "gpa_requirement": "3.2 min",
    "recruiting_timeline": "Evaluating through 2026",
    "contact_email": "recruiting@pytest.example.com",
    "description": "Looking for two-way midfielders and ball-playing center backs with high soccer IQ.",
}


def _create_listing(headers, overrides=None):
    payload = dict(VALID_PAYLOAD)
    if overrides:
        payload.update(overrides)
    r = requests.post(f"{BASE_URL}/api/scout-listings", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _delete_listing(headers, listing_id):
    requests.delete(f"{BASE_URL}/api/scout-listings/{listing_id}", headers=headers)


# ---------- auth + role gate ----------

def test_create_requires_scout_role(coach_user):
    r = requests.post(f"{BASE_URL}/api/scout-listings", headers=coach_user["headers"], json=VALID_PAYLOAD)
    assert r.status_code == 403, r.text
    assert "scout" in r.json()["detail"].lower() or "role" in r.json()["detail"].lower()


def test_create_requires_auth():
    r = requests.post(f"{BASE_URL}/api/scout-listings", json=VALID_PAYLOAD)
    assert r.status_code in (401, 403)


# ---------- CRUD ----------

def test_create_and_delete_listing(scout_user):
    listing = _create_listing(scout_user["headers"])
    try:
        assert listing["school_name"] == VALID_PAYLOAD["school_name"]
        assert listing["verified"] is False
        assert listing["author_name"] == "Test Scout"
        assert sorted(listing["positions"]) == sorted(VALID_PAYLOAD["positions"])
        assert sorted(listing["grad_years"]) == sorted(VALID_PAYLOAD["grad_years"])
    finally:
        _delete_listing(scout_user["headers"], listing["id"])

    # GET after delete -> 404
    r = requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}")
    assert r.status_code == 404


def test_patch_resets_verification(scout_user, admin_user):
    listing = _create_listing(scout_user["headers"])
    try:
        # Verify it
        r = requests.post(
            f"{BASE_URL}/api/admin/scout-listings/{listing['id']}/verify",
            headers=admin_user["headers"],
        )
        assert r.status_code == 200

        # Edit (any field) -> re-moderation
        r = requests.patch(
            f"{BASE_URL}/api/scout-listings/{listing['id']}",
            headers=scout_user["headers"],
            json={"description": "Updated description to trigger re-moderation for pytest."},
        )
        assert r.status_code == 200
        assert r.json()["verified"] is False
    finally:
        _delete_listing(scout_user["headers"], listing["id"])


# ---------- public feed + contact redaction ----------

def test_public_feed_hides_unverified_by_default(scout_user):
    listing = _create_listing(scout_user["headers"], {"school_name": f"HiddenByDefault-{uuid.uuid4().hex[:6]}"})
    try:
        r = requests.get(f"{BASE_URL}/api/scout-listings")
        assert r.status_code == 200
        ids = [l["id"] for l in r.json()]
        assert listing["id"] not in ids

        r = requests.get(f"{BASE_URL}/api/scout-listings?verified_only=false")
        ids = [l["id"] for l in r.json()]
        assert listing["id"] in ids
    finally:
        _delete_listing(scout_user["headers"], listing["id"])


def test_public_feed_redacts_contact_fields(scout_user, admin_user):
    listing = _create_listing(scout_user["headers"])
    try:
        requests.post(
            f"{BASE_URL}/api/admin/scout-listings/{listing['id']}/verify",
            headers=admin_user["headers"],
        )
        r = requests.get(f"{BASE_URL}/api/scout-listings")
        assert r.status_code == 200
        mine = [l for l in r.json() if l["id"] == listing["id"]]
        assert len(mine) == 1
        card = mine[0]
        assert "contact_email" not in card
        assert "website_url" not in card
        assert card.get("_contact_gated") is True
    finally:
        _delete_listing(scout_user["headers"], listing["id"])


def test_detail_redacts_contact_for_anon_shows_for_authed(scout_user):
    listing = _create_listing(scout_user["headers"])
    try:
        # Anon
        r = requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}")
        assert r.status_code == 200
        anon = r.json()
        assert "contact_email" not in anon
        assert "website_url" not in anon
        assert anon.get("_contact_gated") is True

        # Authed
        r = requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}", headers=scout_user["headers"])
        assert r.status_code == 200
        authed = r.json()
        assert authed["contact_email"] == VALID_PAYLOAD["contact_email"]
        # Pydantic HttpUrl normalizes by adding a trailing slash for bare hosts
        assert authed["website_url"].rstrip("/") == VALID_PAYLOAD["website_url"].rstrip("/")
        assert authed.get("_contact_gated") in (None, False)
    finally:
        _delete_listing(scout_user["headers"], listing["id"])


# ---------- filters ----------

def test_filters_apply_correctly(scout_user, admin_user):
    listing = _create_listing(scout_user["headers"], {
        "school_name": f"FilterSchool-{uuid.uuid4().hex[:6]}",
        "positions": ["ST", "LW"],
        "grad_years": [2029],
        "level": "NAIA",
        "region": "Southeast Valley",
    })
    try:
        requests.post(
            f"{BASE_URL}/api/admin/scout-listings/{listing['id']}/verify",
            headers=admin_user["headers"],
        )
        # Positive matches
        for params in (
            "positions=ST",
            "positions=LW",
            "positions=ST,LW",
            "grad_years=2029",
            "level=NAIA",
            "region=southeast",
            f"q={listing['school_name']}",
        ):
            r = requests.get(f"{BASE_URL}/api/scout-listings?{params}")
            assert r.status_code == 200
            ids = [l["id"] for l in r.json()]
            assert listing["id"] in ids, f"expected match for {params}"
        # Negative matches
        for params in (
            "positions=GK",
            "grad_years=2026",
            "level=NCAA D1",
            "region=Pacific Northwest Nowhere",
        ):
            r = requests.get(f"{BASE_URL}/api/scout-listings?{params}")
            ids = [l["id"] for l in r.json()]
            assert listing["id"] not in ids, f"should not match {params}"
    finally:
        _delete_listing(scout_user["headers"], listing["id"])


# ---------- controlled-list validation ----------

def test_reject_bad_position(scout_user):
    r = requests.post(
        f"{BASE_URL}/api/scout-listings",
        headers=scout_user["headers"],
        json={**VALID_PAYLOAD, "positions": ["STRIKER"]},
    )
    assert r.status_code == 400, r.text


def test_reject_bad_level(scout_user):
    r = requests.post(
        f"{BASE_URL}/api/scout-listings",
        headers=scout_user["headers"],
        json={**VALID_PAYLOAD, "level": "Fantasy Pro League"},
    )
    assert r.status_code == 400, r.text


def test_reject_out_of_range_year(scout_user):
    r = requests.post(
        f"{BASE_URL}/api/scout-listings",
        headers=scout_user["headers"],
        json={**VALID_PAYLOAD, "grad_years": [1999]},
    )
    assert r.status_code == 400, r.text


# ---------- admin verify flow ----------

def test_admin_verify_and_unverify(scout_user, admin_user):
    listing = _create_listing(scout_user["headers"])
    try:
        r = requests.post(
            f"{BASE_URL}/api/admin/scout-listings/{listing['id']}/verify",
            headers=admin_user["headers"],
        )
        assert r.status_code == 200
        r = requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}", headers=scout_user["headers"])
        assert r.json()["verified"] is True
        assert r.json()["verified_by"]

        r = requests.post(
            f"{BASE_URL}/api/admin/scout-listings/{listing['id']}/unverify",
            headers=admin_user["headers"],
        )
        assert r.status_code == 200
        r = requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}", headers=scout_user["headers"])
        assert r.json()["verified"] is False
    finally:
        _delete_listing(scout_user["headers"], listing["id"])


def test_admin_list_pending_queue(scout_user, admin_user):
    listing = _create_listing(scout_user["headers"], {"school_name": f"PendingQueue-{uuid.uuid4().hex[:6]}"})
    try:
        r = requests.get(
            f"{BASE_URL}/api/admin/scout-listings?status=pending",
            headers=admin_user["headers"],
        )
        assert r.status_code == 200
        ids = [l["id"] for l in r.json()]
        assert listing["id"] in ids
    finally:
        _delete_listing(scout_user["headers"], listing["id"])


def test_admin_endpoints_require_admin(scout_user):
    # Scout user (not admin) cannot hit admin endpoints
    r = requests.get(f"{BASE_URL}/api/admin/scout-listings", headers=scout_user["headers"])
    assert r.status_code == 403
