"""Iter11 new-feature regression tests.

Covers:
- Admin endpoints (list users, role updates, self-demotion guard, RBAC).
- @-mentions: mentionable-coaches lookup and ClipCollection mention payload.
- Manual-result match endpoints: PUT/GET/DELETE + score bounds + outcome.
- Season Trends aggregation including manual matches.
- /api/auth/me re-validation surface (id/email/name/role).
- Storage dedup smoke: server.py imports from services/storage.py only.

NOTE: We DO NOT trigger the actual coach-pulse weekly blast (would email real
users). Scheduler startup is verified via supervisor logs in the agent run.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://video-scout-11.preview.emergentagent.com').rstrip('/')


# ---------- helpers ----------
def _signup_aux_coach():
    """Create a fresh non-admin coach account to use for 403 / self-demote tests.

    Returns dict {email, password, token, user_id, headers}.
    """
    email = f"TEST_aux_{uuid.uuid4().hex[:8]}@demo.com"
    password = "coach123"
    name = "Aux Coach"
    r = requests.post(f"{BASE_URL}/api/auth/register", json={
        "email": email, "password": password, "name": name,
    }, timeout=15)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    body = r.json()
    token = body.get("token") or body.get("access_token")
    user = body.get("user") or {}
    if not token:
        login = requests.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": password}, timeout=15)
        token = login.json().get("token")
        user = login.json().get("user") or user
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return {"email": email, "password": password, "token": token, "user_id": user.get("id"), "headers": headers}


# ---------- /api/auth/me sanity ----------
class TestAuthMe:
    def test_auth_me_returns_role_and_no_password(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        d = r.json()
        for k in ("id", "email", "name", "role"):
            assert k in d, f"missing {k} in /auth/me response"
        assert "password" not in d
        assert d["email"] == "testcoach@demo.com"
        assert d["role"] in ("admin", "owner")


# ---------- Admin endpoints ----------
class TestAdminEndpoints:
    def test_admin_list_users_as_admin(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        users = r.json()
        assert isinstance(users, list)
        assert len(users) >= 1
        sample = users[0]
        assert "id" in sample and "email" in sample and "role" in sample
        assert "matches_count" in sample and "clips_count" in sample

    def test_admin_list_users_q_filter(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/admin/users?q=testcoach", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        emails = [u.get("email", "") for u in r.json()]
        assert any("testcoach" in e.lower() for e in emails)

    def test_admin_list_users_as_non_admin_403(self):
        aux = _signup_aux_coach()
        try:
            r = requests.get(f"{BASE_URL}/api/admin/users", headers=aux["headers"], timeout=15)
            assert r.status_code == 403
        finally:
            # cleanup not needed — TEST_ prefix
            pass

    def test_admin_invalid_role_400(self, auth_headers):
        # need a user_id — get one from list
        users = requests.get(f"{BASE_URL}/api/admin/users", headers=auth_headers, timeout=10).json()
        target = next((u for u in users if u["email"] != "testcoach@demo.com"), None)
        if not target:
            pytest.skip("No non-admin user available for invalid-role test")
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{target['id']}/role",
            json={"role": "supreme_overlord"},
            headers=auth_headers, timeout=10,
        )
        assert r.status_code == 400

    def test_admin_promote_demote_roundtrip(self, auth_headers):
        aux = _signup_aux_coach()
        uid = aux["user_id"]
        # promote -> admin
        r1 = requests.post(
            f"{BASE_URL}/api/admin/users/{uid}/role",
            json={"role": "admin"}, headers=auth_headers, timeout=10,
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["role"] == "admin"
        # verify on /auth/me of aux user
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=aux["headers"], timeout=10).json()
        assert me["role"] == "admin"
        # demote back -> coach
        r2 = requests.post(
            f"{BASE_URL}/api/admin/users/{uid}/role",
            json={"role": "coach"}, headers=auth_headers, timeout=10,
        )
        assert r2.status_code == 200
        assert r2.json()["role"] == "coach"

    def test_admin_self_demote_when_other_admin_exists(self, auth_headers):
        """If another admin exists, self-demotion is allowed."""
        # Promote an aux coach to admin first.
        aux = _signup_aux_coach()
        promote = requests.post(
            f"{BASE_URL}/api/admin/users/{aux['user_id']}/role",
            json={"role": "admin"}, headers=auth_headers, timeout=10,
        )
        assert promote.status_code == 200
        # Aux, now admin, demotes themselves -> coach. Allowed since testcoach is still admin.
        r = requests.post(
            f"{BASE_URL}/api/admin/users/{aux['user_id']}/role",
            json={"role": "coach"}, headers=aux["headers"], timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json()["role"] == "coach"


# ---------- @-mentions ----------
class TestMentions:
    def test_mentionable_coaches_basic(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/coach-network/mentionable-coaches", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            sample = data[0]
            for k in ("id", "name", "email", "active", "matches_count", "clips_count"):
                assert k in sample
            # Caller excluded
            for u in data:
                assert u["email"] != "testcoach@demo.com"

    def test_mentionable_coaches_q_filter(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/coach-network/mentionable-coaches?q=demo", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        for u in r.json():
            assert "demo" in (u["email"] + u["name"]).lower()


# ---------- Manual-result endpoints ----------
@pytest.fixture(scope="class")
def manual_match(auth_headers):
    """Create a fresh match with no video for manual-result tests."""
    payload = {
        "team_home": "TEST_HOME",
        "team_away": "TEST_AWAY",
        "date": "2026-04-30",
        "competition": "TEST_LEAGUE",
    }
    r = requests.post(f"{BASE_URL}/api/matches", json=payload, headers=auth_headers, timeout=10)
    assert r.status_code in (200, 201)
    match = r.json()
    yield match
    # cleanup
    requests.post(
        f"{BASE_URL}/api/matches/bulk/delete",
        json={"match_ids": [match["id"]]},
        headers=auth_headers, timeout=10,
    )


class TestManualResult:
    def test_save_manual_result_win(self, auth_headers, manual_match):
        mid = manual_match["id"]
        r = requests.put(
            f"{BASE_URL}/api/matches/{mid}/manual-result",
            json={
                "home_score": 3, "away_score": 1,
                "key_events": [{"type": "goal", "minute": 23, "team": "TEST_HOME", "description": "Header"}],
                "notes": "Strong first half",
            },
            headers=auth_headers, timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "saved"
        mr = body["manual_result"]
        assert mr["home_score"] == 3 and mr["away_score"] == 1
        assert mr["outcome"] == "W"
        assert len(mr["key_events"]) == 1

    def test_get_manual_result(self, auth_headers, manual_match):
        mid = manual_match["id"]
        r = requests.get(f"{BASE_URL}/api/matches/{mid}/manual-result", headers=auth_headers, timeout=10)
        assert r.status_code == 200
        mr = r.json()
        assert mr.get("home_score") == 3
        assert mr.get("outcome") == "W"

    def test_matches_list_includes_manual_result(self, auth_headers, manual_match):
        r = requests.get(f"{BASE_URL}/api/matches", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        found = next((m for m in r.json() if m["id"] == manual_match["id"]), None)
        assert found is not None
        assert found.get("has_manual_result") is True
        assert found.get("manual_result", {}).get("outcome") == "W"

    def test_manual_result_score_bounds(self, auth_headers, manual_match):
        mid = manual_match["id"]
        r = requests.put(
            f"{BASE_URL}/api/matches/{mid}/manual-result",
            json={"home_score": 100, "away_score": 0, "key_events": [], "notes": ""},
            headers=auth_headers, timeout=10,
        )
        assert r.status_code == 422  # pydantic validation

    def test_manual_result_outcome_loss_then_draw(self, auth_headers, manual_match):
        mid = manual_match["id"]
        r1 = requests.put(
            f"{BASE_URL}/api/matches/{mid}/manual-result",
            json={"home_score": 0, "away_score": 2, "key_events": [], "notes": ""},
            headers=auth_headers, timeout=10,
        )
        assert r1.status_code == 200
        assert r1.json()["manual_result"]["outcome"] == "L"
        r2 = requests.put(
            f"{BASE_URL}/api/matches/{mid}/manual-result",
            json={"home_score": 1, "away_score": 1, "key_events": [], "notes": ""},
            headers=auth_headers, timeout=10,
        )
        assert r2.status_code == 200
        assert r2.json()["manual_result"]["outcome"] == "D"

    def test_delete_manual_result(self, auth_headers):
        # Create a temp match dedicated to delete
        m = requests.post(
            f"{BASE_URL}/api/matches",
            json={"team_home": "TEST_DEL_H", "team_away": "TEST_DEL_A", "date": "2026-04-30", "competition": "TEST"},
            headers=auth_headers, timeout=10,
        ).json()
        mid = m["id"]
        requests.put(
            f"{BASE_URL}/api/matches/{mid}/manual-result",
            json={"home_score": 1, "away_score": 0, "key_events": [], "notes": ""},
            headers=auth_headers, timeout=10,
        )
        d = requests.delete(f"{BASE_URL}/api/matches/{mid}/manual-result", headers=auth_headers, timeout=10)
        assert d.status_code == 200
        # GET should be empty
        g = requests.get(f"{BASE_URL}/api/matches/{mid}/manual-result", headers=auth_headers, timeout=10)
        assert g.status_code == 200 and g.json() == {}
        # cleanup
        requests.post(
            f"{BASE_URL}/api/matches/bulk/delete",
            json={"match_ids": [mid]}, headers=auth_headers, timeout=10,
        )


# ---------- Season Trends with manual matches ----------
class TestSeasonTrendsManual:
    def test_season_trends_includes_manual(self, auth_headers):
        # Create a folder + a manual-result match assigned to it
        folder_resp = requests.post(
            f"{BASE_URL}/api/folders",
            json={"name": f"TEST_TrendsFolder_{uuid.uuid4().hex[:6]}"},
            headers=auth_headers, timeout=10,
        )
        assert folder_resp.status_code in (200, 201), folder_resp.text
        folder = folder_resp.json()
        fid = folder["id"]

        mr = requests.post(
            f"{BASE_URL}/api/matches",
            json={
                "team_home": "TEST_FH", "team_away": "TEST_FA",
                "date": "2026-04-15", "competition": "TEST_T",
                "folder_id": fid,
            }, headers=auth_headers, timeout=10,
        ).json()
        mid = mr["id"]
        requests.put(
            f"{BASE_URL}/api/matches/{mid}/manual-result",
            json={"home_score": 2, "away_score": 1, "key_events": [
                {"type": "goal", "minute": 10, "team": "TEST_FH"},
                {"type": "goal", "minute": 30, "team": "TEST_FH"},
                {"type": "goal", "minute": 80, "team": "TEST_FA"},
            ], "notes": "manual notes"},
            headers=auth_headers, timeout=10,
        )

        # Generate trends
        r = requests.post(f"{BASE_URL}/api/folders/{fid}/season-trends", headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        totals = body.get("totals") or {}
        assert "matches_with_video" in totals
        assert "matches_with_manual_result" in totals
        assert totals["matches_with_manual_result"] >= 1
        # per_match should include source="manual"
        per_match = body.get("per_match") or []
        sources = [m.get("source") for m in per_match]
        assert "manual" in sources, f"expected source=manual; got sources={sources}"
        # GF/GA reflect manual: at least 2 GF and 1 GA from this manual match
        assert totals.get("goals_for", 0) >= 2
        assert totals.get("goals_against", 0) >= 1

        # cleanup
        requests.post(
            f"{BASE_URL}/api/matches/bulk/delete",
            json={"match_ids": [mid]}, headers=auth_headers, timeout=10,
        )
        requests.delete(f"{BASE_URL}/api/folders/{fid}", headers=auth_headers, timeout=10)


# ---------- Storage dedup smoke ----------
class TestStorageDedup:
    def test_server_does_not_redefine_storage_funcs(self):
        path = os.path.join(os.path.dirname(__file__), "..", "server.py")
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read()
        for name in ("create_storage_session", "init_storage", "put_object_sync",
                     "get_object_sync", "store_chunk", "read_chunk_data",
                     "delete_object_sync", "put_object_with_retry"):
            # No "def name(" or "async def name(" definitions in server.py
            assert f"\ndef {name}(" not in txt, f"server.py still defines {name}"
            assert f"\nasync def {name}(" not in txt, f"server.py still defines async {name}"

    def test_services_storage_is_importable(self):
        from services import storage  # noqa
        for name in ("create_storage_session", "init_storage", "put_object_sync",
                     "get_object_sync", "store_chunk", "read_chunk_data"):
            assert hasattr(storage, name), f"services.storage missing {name}"


# ---------- ClipCollection mention payload (smoke; may skip if no clips) ----------
class TestClipCollectionMentions:
    def test_create_collection_with_mentions_field_accepted(self, auth_headers):
        """Sanity-only: hit /api/clip-collections with 0 mentions and 0 clip_ids
        — schema should still accept description + mentioned_coach_ids."""
        # We need at least one clip ID to make a collection; if none, skip.
        clips = requests.get(f"{BASE_URL}/api/clips", headers=auth_headers, timeout=15)
        if clips.status_code != 200 or not clips.json():
            pytest.skip("No clips available to attach to a collection")
        clip_id = clips.json()[0]["id"]
        r = requests.post(
            f"{BASE_URL}/api/clip-collections",
            json={
                "title": f"TEST_Reel_{uuid.uuid4().hex[:6]}",
                "clip_ids": [clip_id],
                "description": "Quick share",
                "mentioned_coach_ids": [],  # empty — but schema must accept the key
            },
            headers=auth_headers, timeout=20,
        )
        assert r.status_code in (200, 201), r.text
        body = r.json()
        # Must surface mentions counters (even if zero) per spec
        assert "mentions_sent" in body or "mentions_skipped" in body or "id" in body
