"""Iter12 new-feature regression tests.

Covers:
- GET /api/coach-network/mentions returns enriched array (read/unread).
- POST /api/coach-network/mentions/{id}/read sets read_at; 404 on unknown/foreign.
- POST /api/coach-network/mentions/read-all returns {updated: N}.
- GET /api/coach-pulse/admin-preview/{user_id} HTML 200 for admin, 403 non-admin, 404 unknown.
- E2E mention flow: coach1 creates collection mentioning coach2; coach2 sees it.
"""
import os
import uuid
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or "https://video-scout-11.preview.emergentagent.com").rstrip("/")
TIMEOUT = 20


# ---------- helpers ----------
def _signup_coach(prefix="m12"):
    email = f"TEST_{prefix}_{uuid.uuid4().hex[:8]}@demo.com"
    pwd = "coach123"
    r = requests.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": pwd, "name": f"Aux {prefix}"},
                      timeout=TIMEOUT)
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    body = r.json()
    token = body.get("token") or body.get("access_token")
    user = body.get("user") or {}
    if not token:
        login = requests.post(f"{BASE_URL}/api/auth/login",
                              json={"email": email, "password": pwd}, timeout=TIMEOUT)
        token = login.json().get("token")
        user = login.json().get("user") or user
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    return {"email": email, "token": token, "user_id": user.get("id"), "headers": headers}


# ---------- GET /coach-network/mentions ----------
class TestMentionsList:
    def test_get_mentions_returns_array(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/coach-network/mentions",
                         headers=auth_headers, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        assert isinstance(data, list)
        # If any mention exists, validate shape
        if data:
            sample = data[0]
            for k in ("id", "mentioner_name", "collection_id", "reel_title",
                      "reel_share_token", "reel_clip_count", "reel_description",
                      "created_at", "read_at", "email_sent"):
                assert k in sample, f"missing key '{k}' in mention shape: {sample}"

    def test_get_mentions_unread_only_filter(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/coach-network/mentions?unread_only=true",
                         headers=auth_headers, timeout=TIMEOUT)
        assert r.status_code == 200
        for m in r.json():
            assert m.get("read_at") in (None, ""), f"unread_only returned read mention: {m}"


# ---------- mark-read endpoints ----------
class TestMentionMarkRead:
    def test_mark_read_unknown_id_404(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/coach-network/mentions/does-not-exist/read",
                          headers=auth_headers, timeout=TIMEOUT)
        assert r.status_code == 404, r.text

    def test_read_all_returns_updated_count(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/coach-network/mentions/read-all",
                          headers=auth_headers, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "updated" in body
        assert isinstance(body["updated"], int)
        assert body["updated"] >= 0


# ---------- admin-preview endpoint ----------
class TestAdminPreview:
    def test_admin_preview_200_for_admin(self, auth_headers):
        # use testcoach own user_id
        me = requests.get(f"{BASE_URL}/api/auth/me", headers=auth_headers, timeout=TIMEOUT).json()
        uid = me["id"]
        r = requests.get(f"{BASE_URL}/api/coach-pulse/admin-preview/{uid}",
                         headers=auth_headers, timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        ct = r.headers.get("content-type", "")
        assert "text/html" in ct, f"expected text/html, got {ct}"
        body = r.text
        assert "<!DOCTYPE html" in body or "<!doctype html" in body.lower(), \
            "admin-preview response should be a full HTML document"

    def test_admin_preview_404_unknown_user(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/coach-pulse/admin-preview/nonexistent-user-id-xyz",
                         headers=auth_headers, timeout=TIMEOUT)
        assert r.status_code == 404, r.text

    def test_admin_preview_403_for_non_admin(self):
        aux = _signup_coach("preview403")
        # call admin-preview using non-admin token
        r = requests.get(f"{BASE_URL}/api/coach-pulse/admin-preview/{aux['user_id']}",
                         headers=aux["headers"], timeout=TIMEOUT)
        assert r.status_code == 403, r.text


# ---------- E2E mention flow ----------
class TestMentionE2E:
    def test_create_collection_with_mention_surfaces_to_target(self, auth_headers):
        """As testcoach (coach1), create a collection mentioning a fresh coach2;
        coach2 should see exactly that mention in their inbox.
        """
        # coach1 is testcoach (auth_headers). Find one of their clips.
        clips_resp = requests.get(f"{BASE_URL}/api/clips",
                                  headers=auth_headers, timeout=TIMEOUT)
        if clips_resp.status_code != 200 or not clips_resp.json():
            pytest.skip("testcoach has no clips — can't build a collection for E2E mention test")
        clip_id = clips_resp.json()[0]["id"]

        coach2 = _signup_coach("ment_target")
        title = f"TEST_Reel_{uuid.uuid4().hex[:6]}"
        create = requests.post(
            f"{BASE_URL}/api/clip-collections",
            json={
                "title": title,
                "clip_ids": [clip_id],
                "description": "E2E mention test reel",
                "mentioned_coach_ids": [coach2["user_id"]],
            },
            headers=auth_headers, timeout=30,
        )
        assert create.status_code in (200, 201), create.text

        # coach2 should see the mention
        inbox = requests.get(f"{BASE_URL}/api/coach-network/mentions",
                             headers=coach2["headers"], timeout=TIMEOUT)
        assert inbox.status_code == 200, inbox.text
        items = inbox.json()
        match = next((m for m in items if m.get("reel_title") == title), None)
        assert match is not None, f"target coach didn't receive mention; inbox={items}"
        assert match["reel_clip_count"] >= 1
        assert match["read_at"] in (None, "")

        # mark-read via target coach should succeed
        mid = match["id"]
        r1 = requests.post(f"{BASE_URL}/api/coach-network/mentions/{mid}/read",
                           headers=coach2["headers"], timeout=TIMEOUT)
        assert r1.status_code == 200, r1.text

        # mark-read via testcoach (different user) should be 404 — mention doesn't belong to them
        r2 = requests.post(f"{BASE_URL}/api/coach-network/mentions/{mid}/read",
                           headers=auth_headers, timeout=TIMEOUT)
        assert r2.status_code == 404, f"foreign mark-read should be 404; got {r2.status_code}"

        # cleanup: best-effort delete the collection
        coll_id = create.json().get("id")
        if coll_id:
            requests.delete(f"{BASE_URL}/api/clip-collections/{coll_id}",
                            headers=auth_headers, timeout=TIMEOUT)
