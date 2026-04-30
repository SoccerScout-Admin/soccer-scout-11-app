"""Iteration 10 refactor regression — verifies:
1. boot_id from /api/heartbeat matches server_boot_id from /videos/.../processing-status
   (consolidated SERVER_BOOT_ID source-of-truth in runtime.py).
2. AI endpoints (reprocess, generate, generate-trimmed) accept input and respond
   without 500 — i.e. the thin server.py wrappers correctly delegate to
   services/processing.py. We deliberately hit non-existent video IDs to AVOID
   triggering real Gemini runs (cost preservation per spec).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://video-scout-11.preview.emergentagent.com').rstrip('/')


@pytest.fixture(scope="module")
def auth_token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "email": "testcoach@demo.com",
        "password": "password123",
    }, timeout=30)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["user"]["role"] == "admin"
    return data["token"]


@pytest.fixture(scope="module")
def headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def real_video_id(headers):
    """Find an existing video the test user owns by querying Mongo directly."""
    import os as _os
    from dotenv import load_dotenv
    from pymongo import MongoClient
    load_dotenv('/app/backend/.env')
    c = MongoClient(_os.environ['MONGO_URL'])
    udb = c[_os.environ['DB_NAME']]
    u = udb.users.find_one({'email': 'testcoach@demo.com'}, {'id': 1, '_id': 0})
    if not u:
        pytest.skip("test user not found")
    v = udb.videos.find_one(
        {'user_id': u['id'], 'is_deleted': False},
        {'_id': 0, 'id': 1},
    )
    if not v:
        pytest.skip("No video available for boot_id consistency test")
    return v['id']


# -- Boot ID consistency (refactor a) --
class TestBootIdConsistency:
    def test_heartbeat_returns_boot_id(self):
        r = requests.get(f"{BASE_URL}/api/heartbeat", timeout=10)
        assert r.status_code == 200
        d = r.json()
        assert "boot_id" in d and "boot_time" in d
        assert isinstance(d["boot_id"], str) and len(d["boot_id"]) > 10

    def test_processing_status_boot_id_matches_heartbeat(self, headers, real_video_id):
        hb = requests.get(f"{BASE_URL}/api/heartbeat", timeout=10).json()
        ps = requests.get(
            f"{BASE_URL}/api/videos/{real_video_id}/processing-status",
            headers=headers, timeout=10,
        )
        assert ps.status_code == 200, ps.text
        ps_data = ps.json()
        assert "server_boot_id" in ps_data
        assert ps_data["server_boot_id"] == hb["boot_id"], (
            f"Boot-ID mismatch: heartbeat={hb['boot_id']} vs "
            f"processing-status={ps_data['server_boot_id']}"
        )


# -- Refactor (b): wrappers correctly proxy to services/processing --
class TestProcessingWrappers:
    """We hit the endpoints with bogus IDs so they 404 cleanly — proves the
    handler imports / delegates work without 500. We never reach the Gemini
    code path."""

    def test_reprocess_404_on_missing_video(self, headers):
        r = requests.post(
            f"{BASE_URL}/api/videos/nonexistent-uuid-xxx/reprocess",
            headers=headers, timeout=30,
        )
        assert r.status_code == 404

    def test_generate_analysis_404_on_missing_video(self, headers):
        r = requests.post(
            f"{BASE_URL}/api/analysis/generate",
            headers=headers,
            json={"video_id": "nonexistent-uuid-xxx", "analysis_type": "tactical"},
            timeout=30,
        )
        assert r.status_code == 404

    def test_generate_trimmed_404_on_missing_video(self, headers):
        r = requests.post(
            f"{BASE_URL}/api/analysis/generate-trimmed",
            headers=headers,
            json={
                "video_id": "nonexistent-uuid-xxx",
                "analysis_type": "tactical",
                "trim_start": 0,
                "trim_end": 60,
            },
            timeout=30,
        )
        assert r.status_code == 404

    def test_reprocess_returns_already_complete_or_started(self, headers, real_video_id):
        """For a real video, reprocess should respond with one of the documented
        states (already_complete | reprocessing_started). Critically, must NOT 500."""
        r = requests.post(
            f"{BASE_URL}/api/videos/{real_video_id}/reprocess",
            headers=headers, timeout=30,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("status") in ("already_complete", "reprocessing_started"), body


# -- CRUD regression sweep (sanity) --
@pytest.mark.parametrize("endpoint", [
    "/api/matches",
    "/api/folders",
    "/api/clubs",
    "/api/teams",
    "/api/coach-network/benchmarks",
    "/api/coach-pulse/subscription",
    "/api/annotation-templates",
])
def test_crud_endpoint_returns_200(headers, endpoint):
    r = requests.get(f"{BASE_URL}{endpoint}", headers=headers, timeout=20)
    assert r.status_code == 200, f"{endpoint} -> {r.status_code} {r.text[:200]}"
