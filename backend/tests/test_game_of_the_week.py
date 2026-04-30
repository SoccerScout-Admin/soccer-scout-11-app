"""Tests for iter21: Game of the Week admin picker + public feed."""
import requests
import secrets
import uuid
from datetime import datetime, timezone, timedelta

from tests.conftest import BASE_URL, run_async as _run


def _finish_and_share(auth_headers):
    """Create a match, finish it, share it — return (match_id, share_token)."""
    match_id = requests.post(
        f"{BASE_URL}/api/matches", headers=auth_headers, timeout=15,
        json={"team_home": f"GOTW-{secrets.token_hex(3)}", "team_away": "AwayFC",
              "date": datetime.now(timezone.utc).date().isoformat(), "competition": "GOTW Test"},
    ).json()["id"]
    requests.put(
        f"{BASE_URL}/api/matches/{match_id}/manual-result", headers=auth_headers, timeout=15,
        json={"home_score": 4, "away_score": 2,
              "key_events": [{"type": "goal", "minute": 10, "team": "GOTW"}],
              "notes": "Great game."},
    )
    requests.post(f"{BASE_URL}/api/matches/{match_id}/finish", headers=auth_headers, timeout=45)
    share_token = requests.post(
        f"{BASE_URL}/api/matches/{match_id}/share-recap", headers=auth_headers, timeout=10,
    ).json()["share_token"]
    return match_id, share_token


def _cleanup_gotw():
    """Helper: nuke the singleton doc directly."""
    from db import db
    async def go():
        await db.featured.delete_one({"_kind": "game_of_the_week"})
    _run(go())


def test_gotw_set_admin_only(api_client):
    """Non-admin coach gets 403."""
    email = f"coach-{secrets.token_hex(4)}@test.com"
    api_client.post(f"{BASE_URL}/api/auth/register", json={
        "email": email, "password": "password123", "name": "Non Admin"
    })
    token = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": email, "password": "password123"
    }).json().get("token")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(
        f"{BASE_URL}/api/admin/game-of-the-week/set",
        json={"share_token": "any"}, headers=headers, timeout=10,
    )
    assert r.status_code == 403


def test_gotw_set_400_missing_token(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/game-of-the-week/set",
        json={}, headers=auth_headers, timeout=10,
    )
    assert r.status_code == 400


def test_gotw_set_404_invalid_token(auth_headers):
    r = requests.post(
        f"{BASE_URL}/api/admin/game-of-the-week/set",
        json={"share_token": "does-not-exist"}, headers=auth_headers, timeout=10,
    )
    assert r.status_code == 404


def test_gotw_full_lifecycle(auth_headers):
    _cleanup_gotw()
    match_id, token = _finish_and_share(auth_headers)
    try:
        # 1. Public feed initially inactive
        r = requests.get(f"{BASE_URL}/api/game-of-the-week", timeout=10)
        assert r.status_code == 200
        assert r.json()["active"] is False

        # 2. Admin promotes
        promote = requests.post(
            f"{BASE_URL}/api/admin/game-of-the-week/set",
            json={"share_token": token}, headers=auth_headers, timeout=10,
        )
        assert promote.status_code == 200, promote.text
        assert promote.json()["status"] == "featured"

        # 3. Public feed now active with full payload
        r = requests.get(f"{BASE_URL}/api/game-of-the-week", timeout=10)
        data = r.json()
        assert data["active"] is True
        assert data["match_id"] == match_id
        assert data["team_home"].startswith("GOTW-")
        assert data["home_score"] == 4
        assert data["away_score"] == 2
        assert data["outcome"] == "W"
        assert data["days_remaining"] == 7
        assert data["summary"]
        assert data["share_token"] == token
        # featured_by must NOT leak in public response
        assert "featured_by" not in data

        # 4. Replacing a pick updates in place, keeps singleton
        match_id_2, token_2 = _finish_and_share(auth_headers)
        try:
            requests.post(
                f"{BASE_URL}/api/admin/game-of-the-week/set",
                json={"share_token": token_2}, headers=auth_headers, timeout=10,
            )
            data2 = requests.get(f"{BASE_URL}/api/game-of-the-week", timeout=10).json()
            assert data2["share_token"] == token_2
            assert data2["match_id"] == match_id_2
        finally:
            requests.delete(f"{BASE_URL}/api/matches/{match_id_2}", headers=auth_headers, timeout=10)

        # 5. Admin clear
        clear = requests.delete(
            f"{BASE_URL}/api/admin/game-of-the-week", headers=auth_headers, timeout=10,
        )
        assert clear.status_code == 200
        r = requests.get(f"{BASE_URL}/api/game-of-the-week", timeout=10)
        assert r.json()["active"] is False
    finally:
        _cleanup_gotw()
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_gotw_auto_expires_after_7_days(auth_headers):
    """Simulate an 8-day-old pick → public feed must auto-clear it."""
    from db import db
    _cleanup_gotw()

    async def seed_old():
        past = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        await db.featured.insert_one({
            "_kind": "game_of_the_week",
            "share_token": "expired-token",
            "match_id": "expired-match",
            "team_home": "A", "team_away": "B",
            "home_score": 1, "away_score": 0, "outcome": "W",
            "featured_at": past, "featured_by": "admin-test",
        })
    _run(seed_old())
    try:
        r = requests.get(f"{BASE_URL}/api/game-of-the-week", timeout=10)
        assert r.status_code == 200
        assert r.json()["active"] is False  # auto-expired + deleted
        # Confirm it was lazily deleted
        async def check():
            cnt = await db.featured.count_documents({"_kind": "game_of_the_week"})
            return cnt
        assert _run(check()) == 0
    finally:
        _cleanup_gotw()


def test_gotw_public_feed_requires_no_auth():
    """No auth header → must still return 200."""
    r = requests.get(f"{BASE_URL}/api/game-of-the-week", timeout=10)
    assert r.status_code == 200
