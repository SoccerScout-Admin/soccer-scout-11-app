"""Tests for iter20: Share Recap — POST /api/matches/{id}/share-recap + OG endpoints."""
import requests
import secrets
import uuid
from datetime import datetime, timezone

from tests.conftest import BASE_URL


def _create_and_finish_match(auth_headers):
    """Set up a fixture: match with manual_result + finished AI recap."""
    match_id = requests.post(
        f"{BASE_URL}/api/matches", headers=auth_headers, timeout=15,
        json={"team_home": f"ShareTest-{secrets.token_hex(3)}", "team_away": "RivalFC",
              "date": datetime.now(timezone.utc).date().isoformat(), "competition": "Test League"},
    ).json()["id"]
    requests.put(
        f"{BASE_URL}/api/matches/{match_id}/manual-result", headers=auth_headers, timeout=15,
        json={"home_score": 3, "away_score": 1,
              "key_events": [{"type": "goal", "minute": 10, "team": "ShareTest", "description": "Header"}],
              "notes": "Strong attacking."},
    )
    requests.post(f"{BASE_URL}/api/matches/{match_id}/finish", headers=auth_headers, timeout=45)
    return match_id


def test_share_recap_400_when_no_summary(auth_headers):
    """Shouldn't allow sharing before finish."""
    match_id = requests.post(
        f"{BASE_URL}/api/matches", headers=auth_headers, timeout=15,
        json={"team_home": "NoSummary FC", "team_away": "NoSummary United",
              "date": datetime.now(timezone.utc).date().isoformat()},
    ).json()["id"]
    try:
        r = requests.post(f"{BASE_URL}/api/matches/{match_id}/share-recap", headers=auth_headers, timeout=10)
        assert r.status_code == 400
        assert "no ai recap" in r.json()["detail"].lower()
    finally:
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_share_recap_toggles(auth_headers):
    """First call shares, second call revokes."""
    match_id = _create_and_finish_match(auth_headers)
    try:
        r1 = requests.post(f"{BASE_URL}/api/matches/{match_id}/share-recap", headers=auth_headers, timeout=10)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["status"] == "shared"
        token = d1["share_token"]
        assert len(token) > 10

        # Second call revokes
        r2 = requests.post(f"{BASE_URL}/api/matches/{match_id}/share-recap", headers=auth_headers, timeout=10)
        assert r2.status_code == 200
        assert r2.json()["status"] == "revoked"

        # Third call re-shares with a new token
        r3 = requests.post(f"{BASE_URL}/api/matches/{match_id}/share-recap", headers=auth_headers, timeout=10)
        assert r3.status_code == 200
        new_token = r3.json()["share_token"]
        assert new_token != token
    finally:
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_share_recap_404_unknown_match(auth_headers):
    r = requests.post(f"{BASE_URL}/api/matches/{uuid.uuid4()}/share-recap", headers=auth_headers, timeout=10)
    assert r.status_code == 404


def test_og_match_recap_html_unfurls_with_proper_meta_tags(auth_headers):
    """WhatsApp/Slack/Twitter must see og:title + og:image + og:description."""
    match_id = _create_and_finish_match(auth_headers)
    try:
        token = requests.post(
            f"{BASE_URL}/api/matches/{match_id}/share-recap", headers=auth_headers, timeout=10,
        ).json()["share_token"]

        # Public unfurl (no auth)
        r = requests.get(f"{BASE_URL}/api/og/match-recap/{token}", timeout=15)
        assert r.status_code == 200, r.text
        html = r.text
        # Must have OG meta tags
        assert 'property="og:title"' in html
        assert 'property="og:image"' in html
        assert 'property="og:description"' in html
        # Title must embed the scoreline
        assert "3-1" in html
        # Description must be the AI recap excerpt
        assert len(html) > 400
    finally:
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_og_match_recap_image_returns_png(auth_headers):
    match_id = _create_and_finish_match(auth_headers)
    try:
        token = requests.post(
            f"{BASE_URL}/api/matches/{match_id}/share-recap", headers=auth_headers, timeout=10,
        ).json()["share_token"]
        r = requests.get(f"{BASE_URL}/api/og/match-recap/{token}/image.png", timeout=30)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/png")
        # PNG magic
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
        # Reasonable size — OG cards are ~15-60 KB
        assert len(r.content) > 5000
    finally:
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_public_recap_endpoint_returns_full_payload(auth_headers):
    match_id = _create_and_finish_match(auth_headers)
    try:
        token = requests.post(
            f"{BASE_URL}/api/matches/{match_id}/share-recap", headers=auth_headers, timeout=10,
        ).json()["share_token"]
        # Public JSON — no auth
        r = requests.get(f"{BASE_URL}/api/match-recap/public/{token}", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        for k in ("team_home", "team_away", "home_score", "away_score", "summary", "key_events", "outcome"):
            assert k in data, f"missing key {k}"
        assert data["home_score"] == 3
        assert data["away_score"] == 1
        assert data["outcome"] == "W"
        assert len(data["summary"]) > 30
        # user_id MUST NOT leak in public response
        assert "user_id" not in data
    finally:
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_public_recap_404_after_revoke(auth_headers):
    """Revoking the share link must invalidate the public URL immediately."""
    match_id = _create_and_finish_match(auth_headers)
    try:
        token = requests.post(
            f"{BASE_URL}/api/matches/{match_id}/share-recap", headers=auth_headers, timeout=10,
        ).json()["share_token"]
        # Works before revoke
        r1 = requests.get(f"{BASE_URL}/api/match-recap/public/{token}", timeout=10)
        assert r1.status_code == 200
        # Revoke
        requests.post(f"{BASE_URL}/api/matches/{match_id}/share-recap", headers=auth_headers, timeout=10)
        # 404 after revoke
        r2 = requests.get(f"{BASE_URL}/api/match-recap/public/{token}", timeout=10)
        assert r2.status_code == 404
    finally:
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_render_match_recap_card_handles_long_summary():
    """The render function must clamp recaps that wrap to > 3 lines without crashing."""
    from services.og_card import render_match_recap_card
    long_recap = (
        "This is a really long recap that should definitely wrap across multiple lines "
        "and then get truncated by the renderer because we only have room for three lines "
        "inside the open graph card layout that we are generating here today. The fourth "
        "line should never render — if it does the test fails."
    )
    png = render_match_recap_card(
        team_home="TestFC", team_away="RivalUnited",
        home_score=3, away_score=2, competition="Premier League",
        coach_name="Test Coach", recap_text=long_recap, outcome="W",
    )
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(png) > 5000
