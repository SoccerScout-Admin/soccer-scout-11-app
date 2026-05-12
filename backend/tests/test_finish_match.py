"""Tests for iter19: Finish Match (POST /api/matches/{id}/finish + /unlock).

Covers all 4 paths:
  1. 400 when no manual_result exists yet
  2. happy path with manual_result → returns AI or deterministic recap, locks the match
  3. 409 on second call (already finished)
  4. unlock clears is_final but keeps the recap
"""
import requests
import secrets
import uuid
from datetime import datetime, timezone

from tests.conftest import BASE_URL


def _create_match_no_video(auth_headers):
    payload = {
        "team_home": f"FinishTest-{secrets.token_hex(3)}",
        "team_away": "Opponent FC",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "competition": "Pytest League",
    }
    r = requests.post(f"{BASE_URL}/api/matches", json=payload, headers=auth_headers, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _save_manual_result(match_id, auth_headers, home=2, away=1, events=None):
    if events is None:
        events = [
            {"type": "goal", "minute": 12, "team": "FinishTest", "description": "header from corner"},
            {"type": "goal", "minute": 47, "team": "FinishTest", "description": "counter-attack"},
            {"type": "goal", "minute": 83, "team": "Opponent FC", "description": "set piece"},
        ]
    r = requests.put(
        f"{BASE_URL}/api/matches/{match_id}/manual-result",
        json={"home_score": home, "away_score": away, "key_events": events,
              "notes": "Strong second-half press."},
        headers=auth_headers, timeout=15,
    )
    assert r.status_code == 200, r.text


def test_finish_400_when_no_manual_result(auth_headers):
    match_id = _create_match_no_video(auth_headers)
    try:
        r = requests.post(f"{BASE_URL}/api/matches/{match_id}/finish", headers=auth_headers, timeout=30)
        assert r.status_code == 400
        assert "manual result" in r.json()["detail"].lower()
    finally:
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_finish_happy_path_locks_and_generates_recap(auth_headers):
    match_id = _create_match_no_video(auth_headers)
    try:
        _save_manual_result(match_id, auth_headers)
        # Finish — could take 5-15s if Gemini is up
        r = requests.post(f"{BASE_URL}/api/matches/{match_id}/finish", headers=auth_headers, timeout=45)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["status"] == "finished"
        assert data["is_locked"] is True
        assert data["finished_at"]
        assert data["summary"]
        assert len(data["summary"]) > 30, f"Recap too short: {data['summary']!r}"

        # Verify it's persisted on the match
        m = requests.get(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10).json()
        assert m["manual_result"]["is_final"] is True
        assert m["manual_result"]["finished_at"]
        # Insights summary saved
        assert m.get("insights", {}).get("summary") == data["summary"]
        assert m["insights"]["summary_source"] in ("ai_recap", "deterministic_recap")
    finally:
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_finish_409_on_second_call(auth_headers):
    match_id = _create_match_no_video(auth_headers)
    try:
        _save_manual_result(match_id, auth_headers)
        r1 = requests.post(f"{BASE_URL}/api/matches/{match_id}/finish", headers=auth_headers, timeout=45)
        assert r1.status_code == 200
        # Second call must 409
        r2 = requests.post(f"{BASE_URL}/api/matches/{match_id}/finish", headers=auth_headers, timeout=15)
        assert r2.status_code == 409
        assert "already finished" in r2.json()["detail"].lower()
    finally:
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_unlock_clears_is_final_keeps_recap(auth_headers):
    match_id = _create_match_no_video(auth_headers)
    try:
        _save_manual_result(match_id, auth_headers)
        r1 = requests.post(f"{BASE_URL}/api/matches/{match_id}/finish", headers=auth_headers, timeout=45)
        assert r1.status_code == 200
        original_summary = r1.json()["summary"]

        u = requests.post(f"{BASE_URL}/api/matches/{match_id}/unlock", headers=auth_headers, timeout=10)
        assert u.status_code == 200
        assert u.json()["status"] == "unlocked"

        m = requests.get(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10).json()
        # is_final cleared
        assert "is_final" not in (m.get("manual_result") or {})
        assert "finished_at" not in (m.get("manual_result") or {})
        # Recap preserved
        assert m["insights"]["summary"] == original_summary

        # Now finish again should succeed (not 409)
        r2 = requests.post(f"{BASE_URL}/api/matches/{match_id}/finish", headers=auth_headers, timeout=45)
        assert r2.status_code == 200, r2.text
    finally:
        requests.delete(f"{BASE_URL}/api/matches/{match_id}", headers=auth_headers, timeout=10)


def test_finish_404_unknown_match(auth_headers):
    r = requests.post(f"{BASE_URL}/api/matches/{uuid.uuid4()}/finish", headers=auth_headers, timeout=10)
    assert r.status_code == 404


def test_finish_requires_auth():
    fake = str(uuid.uuid4())
    r = requests.post(f"{BASE_URL}/api/matches/{fake}/finish", timeout=10)
    assert r.status_code in (401, 403)


def test_deterministic_recap_format():
    """Pure-function check for the deterministic fallback narrator."""
    from routes.matches import _deterministic_recap

    sample = {
        "team_home": "Arsenal",
        "team_away": "Chelsea",
        "competition": "Premier League",
        "date": "2026-04-30",
        "manual_result": {
            "home_score": 2,
            "away_score": 1,
            "outcome": "W",
            "events": [
                {"type": "goal", "minute": 12, "team": "Arsenal"},
                {"type": "goal", "minute": 47, "team": "Arsenal"},
                {"type": "goal", "minute": 83, "team": "Chelsea"},
            ],
            "notes": "Solid pressing performance.",
        },
    }
    text = _deterministic_recap(sample)
    assert "Arsenal" in text
    assert "Chelsea" in text
    assert "2-1" in text
    assert "win" in text.lower()
    assert "Premier League" in text


def test_recap_prompt_includes_events_and_notes():
    from routes.matches import _build_match_recap_prompt
    sample = {
        "team_home": "Liverpool",
        "team_away": "Everton",
        "competition": "Friendly",
        "date": "2026-04-30",
        "manual_result": {
            "home_score": 3,
            "away_score": 0,
            "outcome": "W",
            "events": [{"type": "goal", "minute": 5, "team": "Liverpool", "description": "early opener"}],
            "notes": "Set pieces dominant today.",
        },
    }
    prompt = _build_match_recap_prompt(sample)
    assert "Liverpool" in prompt
    assert "3-0" in prompt
    assert "early opener" in prompt
    assert "Set pieces dominant" in prompt
