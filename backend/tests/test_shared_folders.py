"""Tests for shared/public folder endpoints."""
import os
import requests
import pytest

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://scout-lens.preview.emergentagent.com').rstrip('/')
EXISTING_SHARE_TOKEN = os.environ.get('TEST_SHARE_TOKEN', '0c1c5e1a-b80')


# ---------- Public (no auth) shared folder endpoints ----------
class TestSharedPublic:
    def test_get_shared_folder_with_existing_token(self):
        r = requests.get(f"{BASE_URL}/api/shared/{EXISTING_SHARE_TOKEN}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "folder" in data and "owner" in data and "matches" in data
        assert data["folder"]["name"]
        assert isinstance(data["matches"], list)
        assert data["owner"].get("name")
        # Should contain at least 1 match (Team A vs Team B)
        assert len(data["matches"]) >= 1
        match = data["matches"][0]
        assert "id" in match and "team_home" in match and "team_away" in match

    def test_get_shared_folder_invalid_token(self):
        r = requests.get(f"{BASE_URL}/api/shared/invalid-token-xyz-9999")
        assert r.status_code == 404
        assert "detail" in r.json()

    def test_get_shared_match_detail(self):
        # First fetch the folder to get a match id
        f = requests.get(f"{BASE_URL}/api/shared/{EXISTING_SHARE_TOKEN}").json()
        match_id = f["matches"][0]["id"]
        r = requests.get(f"{BASE_URL}/api/shared/{EXISTING_SHARE_TOKEN}/match/{match_id}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert "match" in d and d["match"]["id"] == match_id
        assert "folder_name" in d
        assert "players" in d and isinstance(d["players"], list)
        # Per problem statement: 3 players, 0 completed analyses, 0 clips, 0 annotations
        assert len(d["players"]) >= 3
        if d["match"].get("video_id"):
            assert "video" in d
            assert "analyses" in d and isinstance(d["analyses"], list)
            assert "clips" in d and isinstance(d["clips"], list)
            assert "annotations" in d and isinstance(d["annotations"], list)

    def test_get_shared_match_detail_invalid_match(self):
        r = requests.get(f"{BASE_URL}/api/shared/{EXISTING_SHARE_TOKEN}/match/nonexistent-id")
        assert r.status_code == 404

    def test_get_shared_match_detail_invalid_token(self):
        r = requests.get(f"{BASE_URL}/api/shared/bad-token/match/anything")
        assert r.status_code == 404

    def test_shared_video_stream(self):
        f = requests.get(f"{BASE_URL}/api/shared/{EXISTING_SHARE_TOKEN}").json()
        match_id = f["matches"][0]["id"]
        d = requests.get(f"{BASE_URL}/api/shared/{EXISTING_SHARE_TOKEN}/match/{match_id}").json()
        if not d.get("video"):
            pytest.skip("No video in shared match")
        video_id = d["video"]["id"]
        # Just request first 1KB
        r = requests.get(
            f"{BASE_URL}/api/shared/{EXISTING_SHARE_TOKEN}/video/{video_id}",
            headers={"Range": "bytes=0-1023"},
            stream=True,
            timeout=30,
        )
        assert r.status_code in (200, 206), f"Got {r.status_code}: {r.text[:200]}"
        assert r.headers.get("Content-Type", "").startswith("video/") or r.headers.get("content-type", "").startswith("video/")

    def test_shared_video_invalid_token(self):
        r = requests.get(f"{BASE_URL}/api/shared/bad/video/anything")
        assert r.status_code == 404


# ---------- Auth-protected share toggle endpoint ----------
class TestShareToggle:
    def _create_folder(self, headers, name, is_private=False):
        r = requests.post(f"{BASE_URL}/api/folders", json={"name": name, "is_private": is_private}, headers=headers)
        assert r.status_code in (200, 201), r.text
        return r.json()

    def test_share_private_folder_returns_400(self, auth_headers):
        folder = self._create_folder(auth_headers, "TEST_PrivateShare", is_private=True)
        try:
            r = requests.post(f"{BASE_URL}/api/folders/{folder['id']}/share", headers=auth_headers)
            assert r.status_code == 400
            assert "private" in r.json().get("detail", "").lower()
        finally:
            requests.delete(f"{BASE_URL}/api/folders/{folder['id']}", headers=auth_headers)

    def test_share_public_folder_generate_then_revoke(self, auth_headers):
        folder = self._create_folder(auth_headers, "TEST_ShareToggle", is_private=False)
        token = None
        try:
            # First call: generate token
            r1 = requests.post(f"{BASE_URL}/api/folders/{folder['id']}/share", headers=auth_headers)
            assert r1.status_code == 200, r1.text
            d1 = r1.json()
            assert d1["status"] == "shared"
            assert d1["share_token"] is not None
            token = d1["share_token"]

            # Verify public access works
            pub = requests.get(f"{BASE_URL}/api/shared/{token}")
            assert pub.status_code == 200

            # Second call: revoke
            r2 = requests.post(f"{BASE_URL}/api/folders/{folder['id']}/share", headers=auth_headers)
            assert r2.status_code == 200
            d2 = r2.json()
            assert d2["status"] == "unshared"
            assert d2["share_token"] is None

            # Verify public access now denied
            pub2 = requests.get(f"{BASE_URL}/api/shared/{token}")
            assert pub2.status_code == 404
        finally:
            requests.delete(f"{BASE_URL}/api/folders/{folder['id']}", headers=auth_headers)

    def test_share_nonexistent_folder(self, auth_headers):
        r = requests.post(f"{BASE_URL}/api/folders/nonexistent-folder-id/share", headers=auth_headers)
        assert r.status_code == 404

    def test_share_requires_auth(self):
        r = requests.post(f"{BASE_URL}/api/folders/anything/share")
        assert r.status_code in (401, 403)
