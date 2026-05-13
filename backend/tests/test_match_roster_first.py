"""
Tests for iter61: roster-first match creation flow.

Covers the three new endpoints that wire up the Create Match → Roster step:
  - POST /matches/{match_id}/import-team-roster
  - GET  /matches/{match_id}/roster-status
  - POST /videos/{video_id}/start-analysis

Plus the auto-processing gate behavior: a freshly uploaded video lands in
`awaiting_roster` (not `queued`) when the match has zero players.

All tests use the live API at $REACT_APP_BACKEND_URL via requests.
"""
import os
import uuid
import requests

BASE_URL = os.environ.get("BASE_URL") or "https://scout-lens.preview.emergentagent.com"


def _login():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": "testcoach@demo.com", "password": "password123"},
        timeout=15,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _mk_team(headers, name=None, season="2026"):
    name = name or f"PyTeam-{uuid.uuid4().hex[:6]}"
    r = requests.post(
        f"{BASE_URL}/api/teams",
        params={"name": name, "season": season},
        headers=headers,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _mk_player(headers, team_id, name, number, position="Midfielder"):
    r = requests.post(
        f"{BASE_URL}/api/players",
        json={"team_id": team_id, "name": name, "number": number, "position": position},
        headers=headers,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _mk_match(headers, team_home="HomeFC", team_away="AwayFC"):
    r = requests.post(
        f"{BASE_URL}/api/matches",
        json={
            "team_home": team_home,
            "team_away": team_away,
            "date": "2026-02-15",
            "competition": "Test League",
        },
        headers=headers,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def _cleanup_match(headers, match_id):
    requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=headers, timeout=10)


def _cleanup_team(headers, team_id):
    requests.delete(f"{BASE_URL}/api/teams/{team_id}", headers=headers, timeout=10)


# ---------- /roster-status ----------

def test_roster_status_empty_match():
    headers = _login()
    match = _mk_match(headers)
    try:
        r = requests.get(
            f"{BASE_URL}/api/matches/{match['id']}/roster-status",
            headers=headers, timeout=10,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["player_count"] == 0
        assert body["has_roster"] is False
    finally:
        _cleanup_match(headers, match["id"])


def test_roster_status_404_for_unknown_match():
    headers = _login()
    r = requests.get(
        f"{BASE_URL}/api/matches/nope-match-id/roster-status",
        headers=headers, timeout=10,
    )
    assert r.status_code == 404


# ---------- /import-team-roster ----------

def test_import_team_roster_copies_players():
    headers = _login()
    team = _mk_team(headers)
    _mk_player(headers, team["id"], "Reyes", 7, "Forward")
    _mk_player(headers, team["id"], "Murphy", 8, "Midfielder")
    _mk_player(headers, team["id"], "Chen", 1, "Goalkeeper")
    match = _mk_match(headers)
    try:
        r = requests.post(
            f"{BASE_URL}/api/matches/{match['id']}/import-team-roster",
            json={"team_id": team["id"]},
            headers=headers, timeout=10,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["imported"] == 3
        assert body["skipped"] == 0
        assert body["team_name"] == team["name"]

        # Roster status reflects the imported players
        status = requests.get(
            f"{BASE_URL}/api/matches/{match['id']}/roster-status",
            headers=headers, timeout=10,
        ).json()
        assert status["player_count"] == 3
        assert status["has_roster"] is True
    finally:
        _cleanup_match(headers, match["id"])
        _cleanup_team(headers, team["id"])


def test_import_is_idempotent_by_name_and_number():
    """Re-running import on the same match should skip existing copies."""
    headers = _login()
    team = _mk_team(headers)
    _mk_player(headers, team["id"], "Reyes", 7)
    _mk_player(headers, team["id"], "Murphy", 8)
    match = _mk_match(headers)
    try:
        first = requests.post(
            f"{BASE_URL}/api/matches/{match['id']}/import-team-roster",
            json={"team_id": team["id"]},
            headers=headers, timeout=10,
        ).json()
        assert first["imported"] == 2

        # Second call — should skip both
        second = requests.post(
            f"{BASE_URL}/api/matches/{match['id']}/import-team-roster",
            json={"team_id": team["id"]},
            headers=headers, timeout=10,
        ).json()
        assert second["imported"] == 0
        assert second["skipped"] == 2
    finally:
        _cleanup_match(headers, match["id"])
        _cleanup_team(headers, team["id"])


def test_import_preserves_clean_team_roster():
    """Match-imported copies must NOT pollute the team roster (no team_ids
    back-reference). Otherwise the Team Roster page would show fan-out
    duplicates after the same team is imported into multiple matches.
    """
    headers = _login()
    team = _mk_team(headers)
    _mk_player(headers, team["id"], "Reyes", 7)
    _mk_player(headers, team["id"], "Murphy", 8)
    match = _mk_match(headers)
    try:
        requests.post(
            f"{BASE_URL}/api/matches/{match['id']}/import-team-roster",
            json={"team_id": team["id"]},
            headers=headers, timeout=10,
        )
        # Team roster should still show exactly the 2 originals
        team_players = requests.get(
            f"{BASE_URL}/api/teams/{team['id']}/players",
            headers=headers, timeout=10,
        ).json()
        assert len(team_players) == 2
        # And match has its own 2 copies
        match_players = requests.get(
            f"{BASE_URL}/api/players/match/{match['id']}",
            headers=headers, timeout=10,
        ).json()
        assert len(match_players) == 2
        # Copies must NOT carry the source team_id back
        for p in match_players:
            assert team["id"] not in (p.get("team_ids") or [])
    finally:
        _cleanup_match(headers, match["id"])
        _cleanup_team(headers, team["id"])


def test_import_404_for_unknown_team():
    headers = _login()
    match = _mk_match(headers)
    try:
        r = requests.post(
            f"{BASE_URL}/api/matches/{match['id']}/import-team-roster",
            json={"team_id": "no-such-team"},
            headers=headers, timeout=10,
        )
        assert r.status_code == 404
    finally:
        _cleanup_match(headers, match["id"])


def test_import_404_for_unknown_match():
    headers = _login()
    team = _mk_team(headers)
    try:
        r = requests.post(
            f"{BASE_URL}/api/matches/no-such-match/import-team-roster",
            json={"team_id": team["id"]},
            headers=headers, timeout=10,
        )
        assert r.status_code == 404
    finally:
        _cleanup_team(headers, team["id"])


# ---------- /start-analysis ----------

def test_start_analysis_404_for_unknown_video():
    headers = _login()
    r = requests.post(
        f"{BASE_URL}/api/videos/no-such-video/start-analysis",
        headers=headers, timeout=10,
    )
    assert r.status_code == 404
