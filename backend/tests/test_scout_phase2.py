"""Scout Board Phase 2 — Express Interest + Messaging + OG cards.

Surfaces under test:
- POST /scout-listings/{id}/express-interest — auth required, blocks self-interest,
  creates thread, appends message, queues email, increments contact-click metric
- POST /messages/threads/open — find-or-create 1:1 thread, dedupes on participant_pair
- POST /messages/threads/{id}/reply + read tracking
- GET /messages/unread-count aggregate
- GET /messages/threads — list with hydrated participants and my_unread
- GET /og/scout-listing/{id} returns proper OG meta tags
- GET /og/scout-listing/{id}/image.png returns a valid PNG
- Cross-user permission enforcement on threads (not a participant -> 404)
"""
from __future__ import annotations

import io
import os
import time
import uuid
import requests
import pytest

from tests.conftest import BASE_URL, run_async as _run_async


@pytest.fixture(scope="module")
def scout_user():
    email = f"phase2scout-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "ScoutPass123", "name": "P2 Scout", "role": "scout"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    return {
        "email": email,
        "id": data["user"]["id"],
        "headers": {"Authorization": f"Bearer {data['token']}", "Content-Type": "application/json"},
    }


@pytest.fixture(scope="module")
def coach_user():
    email = f"phase2coach-{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "CoachPass123", "name": "P2 Coach", "role": "coach"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    return {
        "email": email,
        "id": data["user"]["id"],
        "headers": {"Authorization": f"Bearer {data['token']}", "Content-Type": "application/json"},
    }


@pytest.fixture(scope="module")
def admin_headers():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": "testcoach@demo.com", "password": "password123"})
    if r.status_code != 200 or r.json().get("user", {}).get("role") not in ("admin", "owner"):
        pytest.skip("admin test account not available")
    return {"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"}


@pytest.fixture
def listing(scout_user, admin_headers):
    """A verified listing belonging to scout_user, fresh for each test."""
    r = requests.post(
        f"{BASE_URL}/api/scout-listings",
        headers=scout_user["headers"],
        json={
            "school_name": f"P2-{uuid.uuid4().hex[:6]}",
            "positions": ["CB", "CM"],
            "grad_years": [2027],
            "level": "NCAA D1",
            "region": "P2 Region",
            "contact_email": f"recruit-{uuid.uuid4().hex[:6]}@p2.example.edu",
            "description": "Phase 2 fixture listing for express interest + messaging tests.",
        },
    )
    assert r.status_code == 200, r.text
    listing_data = r.json()
    requests.post(
        f"{BASE_URL}/api/admin/scout-listings/{listing_data['id']}/verify",
        headers=admin_headers,
    )
    yield listing_data
    # Cleanup
    async def go():
        from db import db
        await db.scout_listings.delete_many({"id": listing_data["id"]})
        await db.message_threads.delete_many({})
        await db.messages.delete_many({})
        await db.scout_listing_views.delete_many({})
        await db.email_queue.delete_many({"to_email": scout_user["email"]})
    _run_async(go())


# ---------- express interest ----------

def test_express_interest_requires_auth(listing):
    r = requests.post(
        f"{BASE_URL}/api/scout-listings/{listing['id']}/express-interest",
        json={"message": "hello hello hello"},
    )
    assert r.status_code in (401, 403)


def test_express_interest_blocks_self(listing, scout_user):
    r = requests.post(
        f"{BASE_URL}/api/scout-listings/{listing['id']}/express-interest",
        headers=scout_user["headers"],
        json={"message": "trying to send interest to myself"},
    )
    assert r.status_code == 400


def test_express_interest_404_for_unknown_listing(coach_user):
    r = requests.post(
        f"{BASE_URL}/api/scout-listings/{uuid.uuid4()}/express-interest",
        headers=coach_user["headers"],
        json={"message": "hello hello hello"},
    )
    assert r.status_code == 404


def test_express_interest_short_message_rejected(listing, coach_user):
    r = requests.post(
        f"{BASE_URL}/api/scout-listings/{listing['id']}/express-interest",
        headers=coach_user["headers"],
        json={"message": "hi"},
    )
    assert r.status_code == 422


def test_express_interest_happy_path(listing, scout_user, coach_user):
    r = requests.post(
        f"{BASE_URL}/api/scout-listings/{listing['id']}/express-interest",
        headers=coach_user["headers"],
        json={"message": "Have a great fit player for your CB need."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "sent"
    thread_id = body["thread_id"]

    # Email queued for the scout
    async def assert_email():
        from db import db
        doc = await db.email_queue.find_one(
            {"to_email": scout_user["email"], "kind": "scout_interest"},
            sort=[("created_at", -1)],
        )
        assert doc is not None
        assert "P2 Coach" in doc["subject"]
        assert thread_id in doc["html"]
    _run_async(assert_email())

    # Thread shows up for coach
    r = requests.get(f"{BASE_URL}/api/messages/threads", headers=coach_user["headers"])
    threads = r.json()
    assert any(t["id"] == thread_id for t in threads)

    # Scout has unread count = 1
    r = requests.get(f"{BASE_URL}/api/messages/unread-count", headers=scout_user["headers"])
    assert r.json()["unread"] == 1

    # Listing's contact_clicks_7d incremented
    r = requests.get(
        f"{BASE_URL}/api/scout-listings/{listing['id']}/insights",
        headers=scout_user["headers"],
    )
    assert r.json()["contact_clicks_7d"] >= 1


# ---------- messaging ----------

def test_open_thread_dedupes_pair(scout_user, coach_user):
    r1 = requests.post(
        f"{BASE_URL}/api/messages/threads/open",
        headers=coach_user["headers"],
        json={"other_user_id": scout_user["id"]},
    )
    assert r1.status_code == 200
    t1 = r1.json()
    r2 = requests.post(
        f"{BASE_URL}/api/messages/threads/open",
        headers=scout_user["headers"],  # the OTHER side opens it
        json={"other_user_id": coach_user["id"]},
    )
    assert r2.status_code == 200
    t2 = r2.json()
    assert t1["id"] == t2["id"], "should dedupe to the same thread"

    # Cleanup
    async def go():
        from db import db
        await db.message_threads.delete_one({"id": t1["id"]})
        await db.messages.delete_many({"thread_id": t1["id"]})
    _run_async(go())


def test_thread_404_for_non_participant(scout_user, coach_user, admin_headers):
    r = requests.post(
        f"{BASE_URL}/api/messages/threads/open",
        headers=coach_user["headers"],
        json={"other_user_id": scout_user["id"], "initial_message": "hi"},
    )
    thread_id = r.json()["id"]
    # Admin (not a participant) tries to read
    r2 = requests.get(f"{BASE_URL}/api/messages/threads/{thread_id}", headers=admin_headers)
    assert r2.status_code == 404
    # Admin tries to reply
    r3 = requests.post(
        f"{BASE_URL}/api/messages/threads/{thread_id}/reply",
        headers=admin_headers,
        json={"body": "I shouldn't be here"},
    )
    assert r3.status_code == 404

    async def go():
        from db import db
        await db.message_threads.delete_one({"id": thread_id})
        await db.messages.delete_many({"thread_id": thread_id})
    _run_async(go())


def test_reply_and_read_flow(scout_user, coach_user):
    # Coach opens with initial message
    r = requests.post(
        f"{BASE_URL}/api/messages/threads/open",
        headers=coach_user["headers"],
        json={"other_user_id": scout_user["id"], "initial_message": "First!"},
    )
    thread_id = r.json()["id"]

    # Scout has unread=1
    r = requests.get(f"{BASE_URL}/api/messages/unread-count", headers=scout_user["headers"])
    assert r.json()["unread"] >= 1

    # Scout marks read -> back to 0
    requests.post(
        f"{BASE_URL}/api/messages/threads/{thread_id}/read",
        headers=scout_user["headers"],
    )
    # The aggregate may be >0 if there are other threads, so check this thread specifically
    r = requests.get(f"{BASE_URL}/api/messages/threads", headers=scout_user["headers"])
    me_in_thread = next(t for t in r.json() if t["id"] == thread_id)
    assert me_in_thread["my_unread"] == 0

    # Scout replies -> coach unread now 1
    r = requests.post(
        f"{BASE_URL}/api/messages/threads/{thread_id}/reply",
        headers=scout_user["headers"],
        json={"body": "Reply from scout"},
    )
    assert r.status_code == 200
    r = requests.get(f"{BASE_URL}/api/messages/threads", headers=coach_user["headers"])
    me_in_thread = next(t for t in r.json() if t["id"] == thread_id)
    assert me_in_thread["my_unread"] == 1

    # Both messages visible in the thread fetch
    r = requests.get(f"{BASE_URL}/api/messages/threads/{thread_id}", headers=coach_user["headers"])
    msgs = r.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["body"] == "First!"
    assert msgs[1]["body"] == "Reply from scout"

    async def go():
        from db import db
        await db.message_threads.delete_one({"id": thread_id})
        await db.messages.delete_many({"thread_id": thread_id})
    _run_async(go())


def test_open_thread_with_self_rejected(coach_user):
    r = requests.post(
        f"{BASE_URL}/api/messages/threads/open",
        headers=coach_user["headers"],
        json={"other_user_id": coach_user["id"]},
    )
    assert r.status_code == 400


def test_open_thread_unknown_user_returns_404(coach_user):
    r = requests.post(
        f"{BASE_URL}/api/messages/threads/open",
        headers=coach_user["headers"],
        json={"other_user_id": str(uuid.uuid4())},
    )
    assert r.status_code == 404


# ---------- OG card ----------

def test_og_html_meta_tags(listing):
    r = requests.get(f"{BASE_URL}/api/og/scout-listing/{listing['id']}")
    assert r.status_code == 200
    body = r.text
    assert "og:title" in body
    assert listing["school_name"] in body
    assert f"/api/og/scout-listing/{listing['id']}/image.png" in body
    assert f"/scouts/{listing['id']}" in body


def test_og_image_is_valid_png(listing):
    r = requests.get(f"{BASE_URL}/api/og/scout-listing/{listing['id']}/image.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 5000  # sanity: real card not a tiny placeholder
    # Confirm dimensions
    from PIL import Image
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (1200, 630)


def test_og_404_for_unknown_listing():
    r = requests.get(f"{BASE_URL}/api/og/scout-listing/{uuid.uuid4()}")
    assert r.status_code == 404
    r = requests.get(f"{BASE_URL}/api/og/scout-listing/{uuid.uuid4()}/image.png")
    assert r.status_code == 404
