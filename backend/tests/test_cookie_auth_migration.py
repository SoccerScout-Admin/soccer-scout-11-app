"""
Tests for the iter52 cookie-based auth migration.

Uses requests.Session against the live preview URL (matches the rest of the
suite — see conftest.py). Avoids the TestClient/motor event-loop pitfall.

Verifies:
  - Login sets an httpOnly access_token cookie with correct attributes
  - Authenticated calls work with cookie only (no Authorization header)
  - Legacy Authorization Bearer header still works (backwards compat)
  - Logout clears the cookie
  - Unauthenticated calls return 401
"""
import os
import requests
import pytest
from conftest import THROWAWAY_PASSWORD, make_throwaway_email

BASE_URL = os.environ.get(
    'REACT_APP_BACKEND_URL',
    'https://video-scout-11.preview.emergentagent.com',
).rstrip('/')

TEST_EMAIL = make_throwaway_email("cookie-auth")
TEST_PASSWORD = THROWAWAY_PASSWORD


@pytest.fixture(scope="module")
def registered_user():
    """Register a unique throwaway user for the suite."""
    resp = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "name": "Cookie Tester",
            "role": "coach",
        },
        timeout=15,
    )
    if resp.status_code != 200:
        pytest.skip(
            f"register failed (cannot run cookie auth tests): "
            f"{resp.status_code} {resp.text}"
        )
    return resp.json()


def test_login_sets_httponly_access_token_cookie(registered_user):
    session = requests.Session()
    resp = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=15,
    )
    assert resp.status_code == 200, resp.text

    # Cookie jar should contain access_token
    assert "access_token" in session.cookies, (
        f"access_token missing from cookie jar — got keys: {list(session.cookies.keys())}"
    )

    # And the Set-Cookie header must declare the protective attributes.
    # raw.headers carries all Set-Cookie values; resp.headers folds them.
    set_cookies = resp.raw.headers.getlist("Set-Cookie") if hasattr(resp.raw, 'headers') else [resp.headers.get("set-cookie", "")]
    relevant = next((c for c in set_cookies if c.startswith("access_token=")), "")
    relevant_lower = relevant.lower()
    assert "httponly" in relevant_lower, f"HttpOnly missing — XSS-readable! Got: {relevant}"
    assert "samesite=lax" in relevant_lower, f"SameSite=Lax missing: {relevant}"

    # Token still returned in body for backwards compat
    assert "token" in resp.json()


def test_me_works_with_cookie_only_no_header(registered_user):
    """Session-based call should authenticate via the cookie alone."""
    session = requests.Session()
    login = session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=15,
    )
    assert login.status_code == 200

    me = session.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert me.status_code == 200, f"cookie-only /me failed: {me.text}"
    assert me.json()["email"] == TEST_EMAIL


def test_me_works_with_legacy_header_only_no_cookie(registered_user):
    """Backwards compat: legacy clients without cookies but with Bearer header still work."""
    login = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=15,
    )
    token = login.json()["token"]
    # Plain requests.get — no Session, no cookies — only header
    me = requests.get(
        f"{BASE_URL}/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    assert me.status_code == 200, f"header-only /me failed: {me.text}"
    assert me.json()["email"] == TEST_EMAIL


def test_me_without_credentials_returns_401():
    """No cookie + no header → 401."""
    me = requests.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert me.status_code == 401


def test_logout_clears_cookie(registered_user):
    session = requests.Session()
    session.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=15,
    )
    # Confirm authenticated
    assert session.get(f"{BASE_URL}/api/auth/me", timeout=15).status_code == 200

    logout = session.post(f"{BASE_URL}/api/auth/logout", timeout=15)
    assert logout.status_code == 200

    # After logout the same session should be unauthenticated. The server's
    # Set-Cookie: access_token="" with Max-Age=0 must invalidate the session.
    me_after = session.get(f"{BASE_URL}/api/auth/me", timeout=15)
    assert me_after.status_code == 401, f"session still valid after logout: {me_after.text}"
