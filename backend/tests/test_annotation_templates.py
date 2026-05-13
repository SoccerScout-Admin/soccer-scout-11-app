"""Tests for /api/annotation-templates endpoints (Coach Annotation Templates feature)."""
import os
import uuid
import pytest
import requests
from conftest import THROWAWAY_PASSWORD, make_throwaway_email

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://scout-lens.preview.emergentagent.com').rstrip('/')


# --- Helpers --------------------------------------------------------------

def _login(email, password):
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        return None
    d = r.json()
    return d.get("token") or d.get("access_token")


def _register(email, password, name="Aux Tester"):
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": password, "name": name, "role": "coach"},
    )
    if r.status_code in (200, 201):
        d = r.json()
        return d.get("token") or d.get("access_token")
    return None


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --- Fixtures -------------------------------------------------------------

@pytest.fixture(scope="module")
def primary_headers(auth_headers, auth_token):
    """Reuse the session-scoped auth_headers fixture from conftest.py."""
    # Cleanup any non-default templates from previous runs
    r = requests.get(f"{BASE_URL}/api/annotation-templates", headers=auth_headers)
    if r.status_code == 200:
        for t in r.json():
            # Only delete TEST_-prefixed user-created (non default) templates we may have created
            if t.get("text", "").startswith("TEST_"):
                requests.delete(
                    f"{BASE_URL}/api/annotation-templates/{t['id']}", headers=auth_headers
                )
    yield auth_headers


@pytest.fixture(scope="module")
def secondary_headers():
    """Second user for cross-user isolation tests."""
    email = make_throwaway_email("aux")
    password = THROWAWAY_PASSWORD
    token = _register(email, password)
    if not token:
        # Try login if register failed
        token = _login(email, password)
    if not token:
        pytest.skip("Could not create secondary user")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# --- Tests: seed + listing ------------------------------------------------

class TestSeedAndList:
    def test_first_call_seeds_10_defaults(self, primary_headers):
        r = requests.get(f"{BASE_URL}/api/annotation-templates", headers=primary_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 10  # 10 default seeds

        # No user_id leakage
        for t in data:
            assert "user_id" not in t
            assert "_id" not in t
            assert "id" in t and "text" in t and "annotation_type" in t
            assert t["annotation_type"] in {"note", "tactical", "key_moment"}

    def test_seed_distribution(self, primary_headers):
        """3 note + 4 tactical + 3 key_moment = 10 defaults."""
        r = requests.get(f"{BASE_URL}/api/annotation-templates", headers=primary_headers)
        assert r.status_code == 200
        data = r.json()
        defaults = [t for t in data if t.get("is_default")]
        notes = [t for t in defaults if t["annotation_type"] == "note"]
        tactical = [t for t in defaults if t["annotation_type"] == "tactical"]
        keys = [t for t in defaults if t["annotation_type"] == "key_moment"]
        assert len(notes) == 3, f"Expected 3 default notes, got {len(notes)}"
        assert len(tactical) == 4, f"Expected 4 default tactical, got {len(tactical)}"
        assert len(keys) == 3, f"Expected 3 default key_moment, got {len(keys)}"

    def test_filter_by_tactical(self, primary_headers):
        r = requests.get(
            f"{BASE_URL}/api/annotation-templates?annotation_type=tactical",
            headers=primary_headers,
        )
        assert r.status_code == 200
        data = r.json()
        assert all(t["annotation_type"] == "tactical" for t in data)
        assert len(data) >= 4

    def test_filter_invalid_type_returns_400(self, primary_headers):
        r = requests.get(
            f"{BASE_URL}/api/annotation-templates?annotation_type=bogus",
            headers=primary_headers,
        )
        assert r.status_code == 400

    def test_sort_usage_desc_then_created_asc(self, primary_headers):
        r = requests.get(f"{BASE_URL}/api/annotation-templates", headers=primary_headers)
        data = r.json()
        usage = [t.get("usage_count", 0) for t in data]
        assert usage == sorted(usage, reverse=True), "Not sorted by usage_count desc"


# --- Tests: auth ----------------------------------------------------------

class TestAuth:
    def test_get_no_token_returns_401(self):
        r = requests.get(f"{BASE_URL}/api/annotation-templates")
        assert r.status_code == 401

    def test_get_invalid_token_returns_401(self):
        r = requests.get(
            f"{BASE_URL}/api/annotation-templates",
            headers={"Authorization": "Bearer invalid.token.here"},
        )
        assert r.status_code == 401

    def test_post_no_token_returns_401(self):
        r = requests.post(
            f"{BASE_URL}/api/annotation-templates",
            json={"text": "x", "annotation_type": "note"},
        )
        assert r.status_code == 401

    def test_delete_no_token_returns_401(self):
        r = requests.delete(f"{BASE_URL}/api/annotation-templates/any-id")
        assert r.status_code == 401

    def test_use_no_token_returns_401(self):
        r = requests.post(f"{BASE_URL}/api/annotation-templates/any-id/use")
        assert r.status_code == 401


# --- Tests: create / duplicate / delete -----------------------------------

class TestCreateUseDelete:
    def test_create_new_template(self, primary_headers):
        text = f"TEST_{uuid.uuid4().hex[:8]} pressing trigger"
        r = requests.post(
            f"{BASE_URL}/api/annotation-templates",
            json={"text": text, "annotation_type": "tactical"},
            headers=primary_headers,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert "id" in d
        assert d.get("text") == text
        assert d.get("annotation_type") == "tactical"
        assert "user_id" not in d
        assert d.get("is_default") is False

        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/annotation-templates/{d['id']}", headers=primary_headers
        )

    def test_create_duplicate_returns_existing(self, primary_headers):
        text = f"TEST_dup_{uuid.uuid4().hex[:6]}"
        r1 = requests.post(
            f"{BASE_URL}/api/annotation-templates",
            json={"text": text, "annotation_type": "note"},
            headers=primary_headers,
        )
        assert r1.status_code == 200
        first_id = r1.json()["id"]

        r2 = requests.post(
            f"{BASE_URL}/api/annotation-templates",
            json={"text": text, "annotation_type": "note"},
            headers=primary_headers,
        )
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2.get("duplicate") is True
        assert d2.get("id") == first_id

        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/annotation-templates/{first_id}", headers=primary_headers
        )

    def test_create_invalid_type_returns_400(self, primary_headers):
        r = requests.post(
            f"{BASE_URL}/api/annotation-templates",
            json={"text": "test", "annotation_type": "invalid"},
            headers=primary_headers,
        )
        assert r.status_code == 400

    def test_use_increments_and_floats_to_top(self, primary_headers):
        text = f"TEST_use_{uuid.uuid4().hex[:6]}"
        r = requests.post(
            f"{BASE_URL}/api/annotation-templates",
            json={"text": text, "annotation_type": "note"},
            headers=primary_headers,
        )
        tid = r.json()["id"]

        # Increment 3 times (should beat 0-usage defaults)
        for _ in range(3):
            r2 = requests.post(
                f"{BASE_URL}/api/annotation-templates/{tid}/use",
                headers=primary_headers,
            )
            assert r2.status_code == 200

        # Re-fetch and confirm it's near the top with usage_count >= 3
        r3 = requests.get(
            f"{BASE_URL}/api/annotation-templates?annotation_type=note",
            headers=primary_headers,
        )
        data = r3.json()
        target = next((t for t in data if t["id"] == tid), None)
        assert target is not None
        assert target["usage_count"] >= 3
        # Should be index 0 since defaults have usage_count=0
        assert data[0]["id"] == tid, f"Expected used template at top; got {data[0].get('text')}"

        # Cleanup
        requests.delete(
            f"{BASE_URL}/api/annotation-templates/{tid}", headers=primary_headers
        )

    def test_delete_removes_template(self, primary_headers):
        text = f"TEST_del_{uuid.uuid4().hex[:6]}"
        r = requests.post(
            f"{BASE_URL}/api/annotation-templates",
            json={"text": text, "annotation_type": "note"},
            headers=primary_headers,
        )
        tid = r.json()["id"]
        rd = requests.delete(
            f"{BASE_URL}/api/annotation-templates/{tid}", headers=primary_headers
        )
        assert rd.status_code == 200

        # Verify gone
        rg = requests.get(f"{BASE_URL}/api/annotation-templates", headers=primary_headers)
        ids = [t["id"] for t in rg.json()]
        assert tid not in ids

    def test_delete_unknown_returns_404(self, primary_headers):
        r = requests.delete(
            f"{BASE_URL}/api/annotation-templates/{uuid.uuid4()}",
            headers=primary_headers,
        )
        assert r.status_code == 404

    def test_use_unknown_returns_404(self, primary_headers):
        r = requests.post(
            f"{BASE_URL}/api/annotation-templates/{uuid.uuid4()}/use",
            headers=primary_headers,
        )
        assert r.status_code == 404


# --- Tests: cross-user isolation ------------------------------------------

class TestIsolation:
    def test_user_b_cannot_see_user_a_template(self, primary_headers, secondary_headers):
        # User A creates
        text = f"TEST_iso_{uuid.uuid4().hex[:6]}"
        ra = requests.post(
            f"{BASE_URL}/api/annotation-templates",
            json={"text": text, "annotation_type": "note"},
            headers=primary_headers,
        )
        assert ra.status_code == 200
        a_id = ra.json()["id"]

        # User B lists -> shouldn't see A's template
        rb = requests.get(f"{BASE_URL}/api/annotation-templates", headers=secondary_headers)
        assert rb.status_code == 200
        b_ids = [t["id"] for t in rb.json()]
        assert a_id not in b_ids

        # User B can't delete A's template (404)
        rd = requests.delete(
            f"{BASE_URL}/api/annotation-templates/{a_id}", headers=secondary_headers
        )
        assert rd.status_code == 404

        # User B can't /use A's template (404)
        ru = requests.post(
            f"{BASE_URL}/api/annotation-templates/{a_id}/use", headers=secondary_headers
        )
        assert ru.status_code == 404

        # Cleanup as user A
        requests.delete(
            f"{BASE_URL}/api/annotation-templates/{a_id}", headers=primary_headers
        )
