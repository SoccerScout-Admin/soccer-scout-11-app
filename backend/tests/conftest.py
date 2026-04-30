import pytest
import requests
import os
import sys
import asyncio

# Allow tests that import backend modules directly (e.g. routes.voice_annotations)
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://video-scout-11.preview.emergentagent.com').rstrip('/')

TEST_EMAIL = os.environ.get('TEST_EMAIL', 'testcoach@demo.com')
TEST_PASSWORD = os.environ.get('TEST_PASSWORD', 'password123')


# ONE module-scoped event loop shared across async tests. Motor caches its IO
# executor against the first loop it sees, so creating per-file loops in
# individual test modules causes "Event loop is closed" intermittent failures.
# Tests should call `run_async(coro)` instead of managing their own loops.
_SHARED_LOOP = asyncio.new_event_loop()


def run_async(coro):
    return _SHARED_LOOP.run_until_complete(coro)


@pytest.fixture(scope="session")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def auth_token(api_client):
    resp = api_client.post(f"{BASE_URL}/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD
    })
    if resp.status_code != 200:
        pytest.skip(f"Auth failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return data.get("token") or data.get("access_token")


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
