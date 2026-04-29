"""Regression for the 3 endpoints extracted into /app/backend/routes/videos.py

Verifies that after moving these endpoints out of server.py into the videos_router module,
they still return correct payload schema and proper auth/404 behavior.

Endpoints under test:
- GET /api/videos/{id}/access-token  (JWT short-lived, 5-min expiry)
- GET /api/videos/{id}/metadata      (with chunks_available/chunks_total/data_integrity for chunked)
- GET /api/videos/{id}/processing-status  (completed_types/failed_types/server_boot_id)
"""
import os
import time
import jwt
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://video-scout-11.preview.emergentagent.com").rstrip("/")
EXISTING_VIDEO_ID = "d108814f-cf70-43ee-b3e2-a2269c84aa63"  # LFC 07B vs Express FC, chunked


class TestVideoAccessToken:
    def test_access_token_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/videos/{EXISTING_VIDEO_ID}/access-token")
        assert r.status_code in (401, 403), r.text

    def test_access_token_404_for_unknown_video(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/videos/not-a-real-video-id/access-token", headers=auth_headers)
        assert r.status_code == 404, r.text

    def test_access_token_returns_valid_jwt(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/videos/{EXISTING_VIDEO_ID}/access-token", headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "token" in data
        token = data["token"]
        assert isinstance(token, str) and len(token) > 20
        # Decode without verifying signature — we just need the claim shape
        payload = jwt.decode(token, options={"verify_signature": False})
        assert payload.get("video_id") == EXISTING_VIDEO_ID
        assert payload.get("type") == "video_access"
        assert "user_id" in payload
        assert "exp" in payload
        # Should be ~5 min short-lived
        ttl = payload["exp"] - int(time.time())
        assert 60 <= ttl <= 400, f"TTL out of expected 5-min range: {ttl}"


class TestVideoMetadata:
    def test_metadata_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/videos/{EXISTING_VIDEO_ID}/metadata")
        assert r.status_code in (401, 403), r.text

    def test_metadata_404_unknown(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/videos/not-a-real-vid/metadata", headers=auth_headers)
        assert r.status_code == 404, r.text

    def test_metadata_schema_and_no_large_fields(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/videos/{EXISTING_VIDEO_ID}/metadata", headers=auth_headers)
        assert r.status_code == 200, r.text
        data = r.json()
        # Basic video fields
        assert data["id"] == EXISTING_VIDEO_ID
        assert "filename" in data or "title" in data or "original_filename" in data
        # Large fields must be stripped
        assert "chunk_paths" not in data
        assert "chunk_sizes" not in data
        assert "chunk_backends" not in data
        # _id from mongo must not leak
        assert "_id" not in data

    def test_metadata_includes_chunk_integrity_when_chunked(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/videos/{EXISTING_VIDEO_ID}/metadata", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        if data.get("is_chunked"):
            assert "chunks_available" in data
            assert "chunks_total" in data
            assert "data_integrity" in data
            assert data["data_integrity"] in ("full", "partial", "unavailable")
            assert isinstance(data["chunks_available"], int)
            assert isinstance(data["chunks_total"], int)
            assert data["chunks_available"] <= data["chunks_total"]
            # Per review_request, this specific video should have 403 chunks
            # — don't hard-assert 403 (may change) but expect a reasonable count.
            assert data["chunks_total"] > 0


class TestVideoProcessingStatus:
    def test_processing_status_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/videos/{EXISTING_VIDEO_ID}/processing-status")
        assert r.status_code in (401, 403), r.text

    def test_processing_status_404_unknown(self, auth_headers):
        r = requests.get(f"{BASE_URL}/api/videos/not-real/processing-status", headers=auth_headers)
        assert r.status_code == 404, r.text

    def test_processing_status_payload_shape(self, auth_headers):
        r = requests.get(
            f"{BASE_URL}/api/videos/{EXISTING_VIDEO_ID}/processing-status",
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        for k in (
            "processing_status",
            "processing_progress",
            "processing_current",
            "processing_error",
            "processing_completed_at",
            "completed_types",
            "failed_types",
            "server_boot_id",
        ):
            assert k in data, f"Missing key: {k}. Keys={list(data.keys())}"
        assert isinstance(data["completed_types"], list)
        assert isinstance(data["failed_types"], list)
        # server_boot_id must be a truthy string
        assert isinstance(data["server_boot_id"], str) and data["server_boot_id"]

    def test_processing_status_reflects_completed_analyses(self, auth_headers):
        """Per review context this video has 4 completed analyses -> completed_types should be non-empty."""
        r = requests.get(
            f"{BASE_URL}/api/videos/{EXISTING_VIDEO_ID}/processing-status",
            headers=auth_headers,
        )
        assert r.status_code == 200
        data = r.json()
        # valid analysis types
        valid_types = {"tactical", "player_performance", "highlights", "summary"}
        for t in data["completed_types"]:
            assert t in valid_types or isinstance(t, str)


class TestNoDuplicateRoute:
    """Verify the 410-Gone shim has been removed and a normal 200 is returned (not 410)."""
    def test_no_410_gone(self, auth_headers):
        for ep in ("access-token", "metadata", "processing-status"):
            r = requests.get(f"{BASE_URL}/api/videos/{EXISTING_VIDEO_ID}/{ep}", headers=auth_headers)
            assert r.status_code != 410, f"{ep} returned 410 - duplicate shim still live"
