"""
Tests for iter54 CSRF protection (double-submit token pattern).

The middleware enforces CSRF on cookie-authenticated unsafe-method requests:
  - GETs are skipped (safe methods)
  - Legacy `Authorization: Bearer` callers are skipped (CSRF-immune by design)
  - Auth bootstrap endpoints are exempt (login/register/logout)
  - Everything else with a cookie session must echo the csrf_token cookie
    value in the X-CSRF-Token header
"""
import os
import requests
import pytest
from conftest import THROWAWAY_PASSWORD, make_throwaway_email

BASE_URL = os.environ.get(
    'REACT_APP_BACKEND_URL',
    'https://video-scout-11.preview.emergentagent.com',
).rstrip('/')

TEST_EMAIL = make_throwaway_email("csrf-test")
TEST_PASSWORD = THROWAWAY_PASSWORD


@pytest.fixture(scope="module")
def session_and_csrf():
    """Login and return (session, csrf_token). Session carries the access_token
    cookie (httpOnly) + the csrf_token cookie."""
    session = requests.Session()
    reg = session.post(
        f"{BASE_URL}/api/auth/register",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "name": "CSRF Tester",
            "role": "coach",
        },
        timeout=15,
    )
    if reg.status_code != 200:
        pytest.skip(f"register failed: {reg.status_code} {reg.text}")
    csrf = session.cookies.get("csrf_token")
    assert csrf, f"csrf_token cookie missing from jar after register"
    return session, csrf


def test_login_sets_csrf_token_cookie(session_and_csrf):
    session, csrf = session_and_csrf
    # Cookie jar should contain BOTH access_token and csrf_token
    assert "access_token" in session.cookies
    assert "csrf_token" in session.cookies
    # CSRF token should be a 32+ character URL-safe string (secrets.token_urlsafe(32))
    assert len(csrf) >= 32, f"CSRF token too short ({len(csrf)} chars): {csrf}"


def test_safe_method_get_does_not_require_csrf(session_and_csrf):
    session, _ = session_and_csrf
    # GET /auth/me with cookie but no X-CSRF-Token → should succeed
    me = session.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert me.status_code == 200
    assert me.json()["email"] == TEST_EMAIL


def test_post_without_csrf_header_is_blocked(session_and_csrf):
    session, _ = session_and_csrf
    # POST with cookie session but NO X-CSRF-Token → must be 403
    resp = session.post(
        f"{BASE_URL}/api/matches",
        json={"team_home": "A", "team_away": "B", "date": "2026-02-15"},
        timeout=15,
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
    assert "csrf" in resp.text.lower()


def test_post_with_matching_csrf_header_succeeds(session_and_csrf):
    session, csrf = session_and_csrf
    resp = session.post(
        f"{BASE_URL}/api/matches",
        json={"team_home": "CSRF OK", "team_away": "Test", "date": "2026-02-15"},
        headers={"X-CSRF-Token": csrf},
        timeout=15,
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    match_id = resp.json().get("id")
    assert match_id
    # Cleanup
    session.delete(
        f"{BASE_URL}/api/matches/{match_id}",
        headers={"X-CSRF-Token": csrf},
        timeout=15,
    )


def test_post_with_mismatched_csrf_header_is_blocked(session_and_csrf):
    session, _ = session_and_csrf
    resp = session.post(
        f"{BASE_URL}/api/matches",
        json={"team_home": "X", "team_away": "Y", "date": "2026-02-15"},
        headers={"X-CSRF-Token": "wrong-token-value-here"},
        timeout=15,
    )
    assert resp.status_code == 403


def test_legacy_bearer_header_bypasses_csrf(session_and_csrf):
    """Legacy clients using Authorization: Bearer (no cookie) should bypass
    CSRF entirely — explicit header auth is inherently CSRF-immune."""
    # Get a token via a fresh login that returns it in the body
    login = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=15,
    )
    token = login.json()["token"]

    # Plain requests (no Session = no cookies) + Bearer header + NO CSRF header
    resp = requests.post(
        f"{BASE_URL}/api/matches",
        json={"team_home": "Bearer", "team_away": "Legacy", "date": "2026-02-15"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    assert resp.status_code == 200, f"Bearer-only call blocked unexpectedly: {resp.status_code} {resp.text}"
    match_id = resp.json().get("id")
    if match_id:
        requests.delete(
            f"{BASE_URL}/api/matches/{match_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )


def test_auth_login_endpoint_itself_is_csrf_exempt():
    """/auth/login must not require CSRF — it's the bootstrap call."""
    resp = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=15,
    )
    # Either 200 (valid creds) or 401 (invalid). NEVER 403 (CSRF block).
    assert resp.status_code != 403, "login endpoint blocked by CSRF middleware"
