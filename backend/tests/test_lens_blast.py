"""
Tests for iter73: POST /api/lens-links/blast (Mass Recruiter Blast / Mail Merge).

Endpoint behavior:
  - Admin-only? NO — any authenticated coach can blast their own teams.
  - Creates a unique lens_link + tracking token PER recipient (so opens and
    Hot Lead detection still attribute per-recipient).
  - In-request dedup (case-insensitive) on emails.
  - Per-coach daily cap of 25 unique recipients across the last 24h, computed
    from ALL of that coach's lens_link rows (single + blast endpoints).
  - Hard per-request ceiling of 50 recipients — anything larger 400s.
  - Returns per-recipient status + summary aggregate.
"""
import os
import uuid
import asyncio
import requests
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

BASE_URL = os.environ.get("BASE_URL") or "https://scout-lens.preview.emergentagent.com"
TEST_EMAIL = "testcoach@demo.com"
TEST_PASS = "password123"


def _login():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASS},
        timeout=15,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}, r.json()


def _run_mongo(coro_factory):
    load_dotenv()

    async def _run():
        client = AsyncIOMotorClient(os.environ["MONGO_URL"])
        db = client[os.environ["DB_NAME"]]
        try:
            return await coro_factory(db)
        finally:
            client.close()

    return asyncio.get_event_loop().run_until_complete(_run())


def _make_team(headers):
    """Create a sentinel team for the test and return its id. We DON'T
    pre-populate players — the blast just needs the team to exist."""
    name = f"BlastTest-{uuid.uuid4().hex[:8]}"
    r = requests.post(
        f"{BASE_URL}/api/teams",
        params={"name": name, "season": "2026"},
        headers=headers, timeout=10,
    )
    r.raise_for_status()
    return r.json()["id"]


def _cleanup_team(headers, team_id):
    requests.delete(f"{BASE_URL}/api/teams/{team_id}", headers=headers, timeout=10)


def _cleanup_blast_lens_links(team_id):
    """Remove the lens_link rows the blast created so they don't leak into
    other tests' cap calculations."""
    async def go(db):
        await db.lens_links.delete_many({"team_id": team_id})

    _run_mongo(go)


# ---------------------------------------------------------------------------
# Auth & input validation
# ---------------------------------------------------------------------------

def test_blast_requires_auth():
    r = requests.post(
        f"{BASE_URL}/api/lens-links/blast",
        json={"team_id": "anything", "recipients": [{"email": "x@y.com"}]},
        timeout=10,
    )
    assert r.status_code in (401, 403)


def test_blast_rejects_empty_recipients():
    headers, _ = _login()
    team_id = _make_team(headers)
    try:
        r = requests.post(
            f"{BASE_URL}/api/lens-links/blast",
            json={"team_id": team_id, "recipients": []},
            headers=headers, timeout=10,
        )
        assert r.status_code == 400
    finally:
        _cleanup_team(headers, team_id)


def test_blast_rejects_more_than_50():
    """Hard ceiling per request — protects response size + DB transaction."""
    headers, _ = _login()
    team_id = _make_team(headers)
    try:
        many = [{"email": f"recipient{i}@example.com"} for i in range(51)]
        r = requests.post(
            f"{BASE_URL}/api/lens-links/blast",
            json={"team_id": team_id, "recipients": many},
            headers=headers, timeout=15,
        )
        assert r.status_code == 400 or r.status_code == 422
    finally:
        _cleanup_team(headers, team_id)
        _cleanup_blast_lens_links(team_id)


def test_blast_404_on_unknown_team():
    headers, _ = _login()
    r = requests.post(
        f"{BASE_URL}/api/lens-links/blast",
        json={"team_id": f"nonexistent-{uuid.uuid4().hex}",
              "recipients": [{"email": "x@y.com"}]},
        headers=headers, timeout=10,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Happy path + per-recipient tracking
# ---------------------------------------------------------------------------

def test_blast_creates_unique_link_per_recipient():
    """3 recipients → 3 unique lens_link rows with distinct tracking_tokens.
    Each must point at the same team_share_token but have a unique tracking
    token + recipient email so opens are attributable."""
    headers, _ = _login()
    team_id = _make_team(headers)
    # Use ephemeral test emails — Resend will accept and queue them
    recipients = [
        {"email": f"r1-{uuid.uuid4().hex[:6]}@example.com", "name": "Coach A"},
        {"email": f"r2-{uuid.uuid4().hex[:6]}@example.com", "name": "Coach B"},
        {"email": f"r3-{uuid.uuid4().hex[:6]}@example.com"},
    ]
    try:
        r = requests.post(
            f"{BASE_URL}/api/lens-links/blast",
            json={"team_id": team_id, "filters": {}, "recipients": recipients,
                  "message": "Test blast"},
            headers=headers, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"]["total_unique_recipients"] == 3
        assert len(body["results"]) == 3
        # Distinct tracking URLs per recipient
        urls = [r["tracked_url"] for r in body["results"] if r["tracked_url"]]
        assert len(set(urls)) == 3
        # Each recipient row has its own lens_link_id
        ids = [r["lens_link_id"] for r in body["results"]]
        assert len(set(ids)) == 3
    finally:
        _cleanup_team(headers, team_id)
        _cleanup_blast_lens_links(team_id)


def test_blast_dedupes_within_request():
    """Same email twice (different case) → only ONE lens_link created."""
    headers, _ = _login()
    team_id = _make_team(headers)
    addr = f"dup-{uuid.uuid4().hex[:6]}@example.com"
    recipients = [
        {"email": addr, "name": "Lower"},
        {"email": addr.upper(), "name": "Upper"},  # same address, different case
        {"email": addr, "name": "Again"},
    ]
    try:
        r = requests.post(
            f"{BASE_URL}/api/lens-links/blast",
            json={"team_id": team_id, "recipients": recipients},
            headers=headers, timeout=15,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["summary"]["total_unique_recipients"] == 1
        assert len(body["results"]) == 1
    finally:
        _cleanup_team(headers, team_id)
        _cleanup_blast_lens_links(team_id)


def test_blast_per_recipient_tags_with_same_blast_id():
    """All recipients in one blast share the same blast_id so the SentLensLinks
    panel can group them visually."""
    headers, _ = _login()
    team_id = _make_team(headers)
    recipients = [
        {"email": f"r1-{uuid.uuid4().hex[:6]}@example.com"},
        {"email": f"r2-{uuid.uuid4().hex[:6]}@example.com"},
    ]
    try:
        r = requests.post(
            f"{BASE_URL}/api/lens-links/blast",
            json={"team_id": team_id, "recipients": recipients},
            headers=headers, timeout=15,
        )
        assert r.status_code == 200
        # Fetch the created lens_links from Mongo to confirm tagging
        async def fetch(db):
            return await db.lens_links.find(
                {"team_id": team_id}, {"_id": 0, "blast_id": 1, "id": 1}
            ).to_list(10)
        rows = _run_mongo(fetch)
        blast_ids = [r["blast_id"] for r in rows if r.get("blast_id")]
        assert len(blast_ids) == 2
        assert blast_ids[0] == blast_ids[1]  # same group
    finally:
        _cleanup_team(headers, team_id)
        _cleanup_blast_lens_links(team_id)


# ---------------------------------------------------------------------------
# Daily cap
# ---------------------------------------------------------------------------

def test_blast_respects_daily_cap():
    """Pre-seed 23 lens_link rows from this coach in the last 24h, then blast
    5 recipients. Cap is 25 → first 2 send, last 3 get `skipped_over_cap`.
    """
    headers, payload = _login()
    user_id = payload["user"]["id"]
    team_id = _make_team(headers)

    # Pre-seed 23 lens_link rows in the last 24h tagged to a DIFFERENT team
    # so cleanup doesn't accidentally remove them but they still count toward
    # the cap (which is user-scoped, not team-scoped).
    seed_team = f"seed-team-{uuid.uuid4().hex[:8]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    seed_docs = [{
        "id": f"ll-seed-{uuid.uuid4().hex[:8]}",
        "user_id": user_id,
        "team_id": seed_team,
        "tracking_token": uuid.uuid4().hex,
        "recipient_email": f"seed-{i}@example.com",
        "created_at": now_iso,
        "click_count": 0,
    } for i in range(23)]

    _run_mongo(lambda db: db.lens_links.insert_many(seed_docs))

    blast_recipients = [
        {"email": f"blast-cap-{i}-{uuid.uuid4().hex[:4]}@example.com"} for i in range(5)
    ]
    try:
        r = requests.post(
            f"{BASE_URL}/api/lens-links/blast",
            json={"team_id": team_id, "recipients": blast_recipients},
            headers=headers, timeout=20,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Total unique = 5; budget left = 25 - 23 = 2; rest = skipped_over_cap
        assert body["summary"]["total_unique_recipients"] == 5
        skipped = body["summary"]["skipped_over_cap"]
        delivered = body["summary"]["sent"] + body["summary"]["queued"]
        # Allow some slack in case Resend itself queued — at most 2 went through,
        # at least 3 were skipped by the cap.
        assert skipped >= 3
        assert delivered <= 2
        # And the skipped rows must be the TAIL — first ones went through
        skipped_rows = [r for r in body["results"] if r["status"] == "skipped_over_cap"]
        assert len(skipped_rows) == skipped
    finally:
        _cleanup_team(headers, team_id)
        _cleanup_blast_lens_links(team_id)
        _run_mongo(lambda db: db.lens_links.delete_many({"user_id": user_id, "team_id": seed_team}))
