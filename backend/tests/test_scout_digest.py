"""Scout listing view tracking + weekly digest.

Surfaces under test:
- record_view dedupes within 24h per (listing, viewer_key)
- Owner self-views are NOT counted toward the listing's view metrics
- /scout-listings/{id}/insights gates to owner only (404 for non-owners)
- /scout-listings/{id}/contact-click increments contact_clicks_7d
- /scout-listings/my embeds insights{}
- send_weekly_digest queues an email with the right subject + body for each scout
- Admin trigger endpoint requires admin
- The digest body includes school name, view count headers, and the CTA link
"""
from __future__ import annotations

import uuid
import requests
import pytest

from tests.conftest import BASE_URL, run_async as _run_async


def _register_scout():
    email = f"digest-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "DigestPass123", "name": "Digest Scout", "role": "scout"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    return {
        "email": email,
        "id": data["user"]["id"],
        "headers": {"Authorization": f"Bearer {data['token']}", "Content-Type": "application/json"},
    }


def _admin_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "testcoach@demo.com", "password": "password123"})
    if r.status_code != 200 or r.json().get("user", {}).get("role") not in ("admin", "owner"):
        pytest.skip("admin test account not available")
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


def _create(scout_headers):
    r = requests.post(
        f"{BASE_URL}/api/scout-listings",
        headers=scout_headers,
        json={
            "school_name": f"Insights-{uuid.uuid4().hex[:6]}",
            "website_url": "https://insights.example.edu",
            "positions": ["CB", "CM"],
            "grad_years": [2027],
            "level": "NCAA D1",
            "region": "Insights Region",
            "contact_email": f"recruit-{uuid.uuid4().hex[:6]}@example.edu",
            "description": "Insights pytest fixture listing — covers view tracking + weekly digest.",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def _cleanup_scout(scout):
    async def go():
        from db import db  # noqa: WPS433
        await db.users.delete_one({"email": scout["email"]})
        await db.scout_listings.delete_many({"user_id": scout["id"]})
        await db.scout_listing_views.delete_many({})
        await db.email_queue.delete_many({"to_email": scout["email"]})
    _run_async(go())


# ---------- view tracking ----------

def test_anon_views_count_and_dedupe():
    """Direct service-layer test — bypasses HTTP transport because the K8s
    ingress mutates the X-Forwarded-For chain in ways that break header-based
    fingerprint dedup at the test boundary. Logic is exercised the same way
    the route handler exercises it (record_view + insights)."""
    scout = _register_scout()
    listing = _create(scout["headers"])
    try:
        async def go():
            from services.scout_digest import listing_insights, record_view
            from db import db  # noqa: WPS433

            await record_view(listing["id"], anon_fingerprint="1.2.3.4|ua-A")
            await record_view(listing["id"], anon_fingerprint="1.2.3.4|ua-A")  # dedup
            await record_view(listing["id"], anon_fingerprint="5.6.7.8|ua-B")

            d = await listing_insights(listing["id"])
            assert d["views_7d"] == 2, f"expected 2 unique views, got {d['views_7d']}"
            assert d["unique_coaches_7d"] == 0
            # Belt-and-suspenders: only 2 rows in the views collection
            count = await db.scout_listing_views.count_documents({"listing_id": listing["id"]})
            assert count == 2

        _run_async(go())
    finally:
        _cleanup_scout(scout)


def test_owner_self_views_are_not_counted():
    scout = _register_scout()
    listing = _create(scout["headers"])
    try:
        for _ in range(3):
            requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}", headers=scout["headers"])
        r = requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}/insights", headers=scout["headers"])
        assert r.json()["views_7d"] == 0
    finally:
        _cleanup_scout(scout)


def test_authed_non_owner_view_counts_unique():
    scout = _register_scout()
    listing = _create(scout["headers"])
    other_headers = _admin_headers()
    try:
        # Admin views the listing twice — should dedupe
        requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}", headers=other_headers)
        requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}", headers=other_headers)
        r = requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}/insights", headers=scout["headers"])
        d = r.json()
        assert d["views_7d"] == 1
        assert d["unique_coaches_7d"] == 1
    finally:
        _cleanup_scout(scout)


def test_insights_endpoint_owner_only():
    scout = _register_scout()
    listing = _create(scout["headers"])
    other_headers = _admin_headers()
    try:
        r = requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}/insights", headers=other_headers)
        assert r.status_code == 404
    finally:
        _cleanup_scout(scout)


def test_contact_click_increments_metric():
    scout = _register_scout()
    listing = _create(scout["headers"])
    other_headers = _admin_headers()
    try:
        r = requests.post(f"{BASE_URL}/api/scout-listings/{listing['id']}/contact-click", headers=other_headers)
        assert r.status_code == 200
        # Click again — dedupes
        r = requests.post(f"{BASE_URL}/api/scout-listings/{listing['id']}/contact-click", headers=other_headers)
        assert r.status_code == 200

        r = requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}/insights", headers=scout["headers"])
        assert r.json()["contact_clicks_7d"] == 1
    finally:
        _cleanup_scout(scout)


def test_contact_click_404_for_unknown_listing():
    other = _admin_headers()
    r = requests.post(f"{BASE_URL}/api/scout-listings/{uuid.uuid4()}/contact-click", headers=other)
    assert r.status_code == 404


def test_my_listings_embeds_insights():
    scout = _register_scout()
    listing = _create(scout["headers"])
    try:
        # Trigger one view
        requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}", headers={"X-Forwarded-For": "20.0.0.1"})
        r = requests.get(f"{BASE_URL}/api/scout-listings/my", headers=scout["headers"])
        assert r.status_code == 200
        listings = r.json()
        assert len(listings) == 1
        assert "insights" in listings[0]
        assert listings[0]["insights"]["views_7d"] == 1
    finally:
        _cleanup_scout(scout)


# ---------- weekly digest ----------

def test_digest_endpoint_admin_only():
    scout = _register_scout()
    try:
        r = requests.post(
            f"{BASE_URL}/api/admin/scout-listings/send-weekly-digest",
            headers=scout["headers"],
        )
        assert r.status_code == 403
    finally:
        _cleanup_scout(scout)


def test_digest_emails_listing_owner():
    scout = _register_scout()
    listing = _create(scout["headers"])
    admin_h = _admin_headers()
    try:
        # Trigger one anon view so the digest has data to show
        requests.get(f"{BASE_URL}/api/scout-listings/{listing['id']}", headers={"X-Forwarded-For": "30.0.0.1"})

        r = requests.post(
            f"{BASE_URL}/api/admin/scout-listings/send-weekly-digest",
            headers=admin_h,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["scouts_total"] >= 1

        async def assert_email_queued():
            from db import db  # noqa: WPS433
            doc = await db.email_queue.find_one(
                {"kind": "scout_digest", "to_email": scout["email"]},
                sort=[("created_at", -1)],
            )
            assert doc is not None, "scout digest should be enqueued for the test scout"
            assert "Scout Board weekly digest" in doc["subject"]
            html = doc["html"]
            assert listing["school_name"] in html
            assert "Open Scout Board" in html
            assert "Views" in html
        _run_async(assert_email_queued())
    finally:
        _cleanup_scout(scout)
