"""
iter98 — Async `/analysis/generate*` endpoints to dodge Cloudflare's 100s
edge timeout.

Real production bug 2026-05-27, video f0673397 (1.04 GB, post-iter97 upload):
processing pipeline worked → timeline markers generated → user clicked
"Regenerate" for the overview/tactical analysis → got an "AI Generation
Failed — Request failed with status code 520" toast.

Root cause: `/api/analysis/generate` synchronously runs
`prepare_video_sample()` (5-15 min ffmpeg) + `chat.send_message()` (3-10 min
Gemini File API). Total often >100s, which is Cloudflare's HTTP edge
timeout — surfaces as HTTP 520 to the user. The pod keeps running and
eventually writes the result, but the user sees a misleading failure.

Fix: both endpoints now return 202 Accepted immediately with a
`pending` placeholder analysis row. The actual work runs as
`asyncio.create_task(...)` in the background. The frontend polls
`/api/analysis/video/{id}` and watches the row flip pending → completed/failed.

Tests cover:
  1. /analysis/generate returns 202 + creates pending row
  2. /analysis/generate-trimmed returns 202 + creates pending row
  3. Both endpoints return fast (<5s, well under Cloudflare 100s budget)
  4. Both endpoints replace an existing analysis of the same type
  5. 202 response shape: {analysis_id, status: "pending"}
  6. Auth + not-found boundaries
  7. Frontend hook polls /api/analysis/video/{id}
  8. Frontend handles 202 status
"""
import os
import sys
import uuid
import time
from datetime import datetime, timezone

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


def _payload():
    s = uuid.uuid4().hex[:10]
    return {"email": f"iter98-{s}@example.com", "password": "Iter98Pass!", "name": f"Iter98 {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


async def _seed_match_and_video(c, user_id):
    """Create a match + a minimal video row the analysis endpoints can find.
    The video doesn't need to actually be processable — we expect the
    background task to fail; we just want to verify the 202 contract.
    """
    from db import db
    match_id = str(uuid.uuid4())
    await db.matches.insert_one({
        "id": match_id, "user_id": user_id,
        "team_home": "Test FC", "team_away": "Demo United",
        "date": "2026-05-27", "created_at": datetime.now(timezone.utc).isoformat(),
    })
    video_id = str(uuid.uuid4())
    await db.videos.insert_one({
        "id": video_id, "user_id": user_id, "match_id": match_id,
        "original_filename": "fake.mp4", "is_chunked": False, "is_deleted": False,
        "storage_path": "/nonexistent/fake.mp4",
        "processing_status": "completed",
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return match_id, video_id


# ---------------------------------------------------------------------------
# 1. /analysis/generate returns 202 fast + creates pending placeholder
# ---------------------------------------------------------------------------

def test_generate_returns_202_with_pending_placeholder():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            _, video_id = await _seed_match_and_video(c, me["id"])

            start = time.time()
            r = await c.post(
                "/api/analysis/generate",
                json={"video_id": video_id, "analysis_type": "tactical"},
            )
            elapsed = time.time() - start

            assert r.status_code == 202, f"expected 202, got {r.status_code}: {r.text}"
            assert elapsed < 5.0, (
                f"endpoint took {elapsed:.1f}s — must be <5s to safely beat the "
                "Cloudflare 100s edge timeout"
            )
            body = r.json()
            assert body["status"] == "pending"
            assert "analysis_id" in body

            # Placeholder row in MongoDB has status=pending and the right shape
            row = await db.analyses.find_one(
                {"id": body["analysis_id"]}, {"_id": 0}
            )
            assert row is not None
            assert row["status"] == "pending"
            assert row["analysis_type"] == "tactical"
            assert row["video_id"] == video_id
            assert row["user_id"] == me["id"]
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. /analysis/generate-trimmed returns 202 fast
# ---------------------------------------------------------------------------

def test_generate_trimmed_returns_202_with_pending_placeholder():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            _, video_id = await _seed_match_and_video(c, me["id"])

            start = time.time()
            r = await c.post(
                "/api/analysis/generate-trimmed",
                json={
                    "video_id": video_id, "analysis_type": "highlights",
                    "trim_start": 60, "trim_end": 240,
                },
            )
            elapsed = time.time() - start

            assert r.status_code == 202, r.text
            assert elapsed < 5.0
            body = r.json()
            assert body["status"] == "pending"
            assert "analysis_id" in body

            row = await db.analyses.find_one(
                {"id": body["analysis_id"]}, {"_id": 0}
            )
            assert row["status"] == "pending"
            assert row["analysis_type"] == "highlights"
            assert row["trim_start"] == 60
            assert row["trim_end"] == 240
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 3. Replacing an existing analysis of the same type
# ---------------------------------------------------------------------------

def test_generate_replaces_existing_analysis_of_same_type():
    """Calling generate again for the same analysis_type should clear the
    old row and insert a fresh `pending` one — never leave the user looking
    at a stale `completed` row while the new one is in flight."""
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            _, video_id = await _seed_match_and_video(c, me["id"])

            # Seed a completed analysis
            old_id = str(uuid.uuid4())
            await db.analyses.insert_one({
                "id": old_id, "video_id": video_id, "user_id": me["id"],
                "analysis_type": "tactical", "status": "completed",
                "content": "old result", "created_at": "2026-05-26T00:00:00+00:00",
            })

            r = await c.post(
                "/api/analysis/generate",
                json={"video_id": video_id, "analysis_type": "tactical"},
            )
            new_id = r.json()["analysis_id"]
            assert new_id != old_id

            # Old row gone, only the new pending row remains for this type
            rows = await db.analyses.find(
                {"video_id": video_id, "analysis_type": "tactical"}, {"_id": 0}
            ).to_list(10)
            assert len(rows) == 1, f"expected 1 row, got {len(rows)}: {rows}"
            assert rows[0]["id"] == new_id
            assert rows[0]["status"] == "pending"
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 4. Background task eventually marks the placeholder as failed
#    (we don't have a real video to process — verify the failure path
#     writes back to the same analysis_id rather than leaving it pending
#     forever)
# ---------------------------------------------------------------------------

def test_background_task_marks_placeholder_failed_on_error():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            _, video_id = await _seed_match_and_video(c, me["id"])

            r = await c.post(
                "/api/analysis/generate",
                json={"video_id": video_id, "analysis_type": "tactical"},
            )
            analysis_id = r.json()["analysis_id"]

            # Wait up to 20s for the background task to fail and update the row
            for _ in range(40):
                row = await db.analyses.find_one({"id": analysis_id}, {"_id": 0})
                if row and row["status"] in ("completed", "failed"):
                    break
                await __import__("asyncio").sleep(0.5)
            assert row is not None
            assert row["status"] == "failed", (
                f"expected status=failed (no real video), got {row['status']}"
            )
            assert "error" in row
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 5. Auth + not-found boundaries
# ---------------------------------------------------------------------------

def test_generate_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.post(
                "/api/analysis/generate",
                json={"video_id": "x", "analysis_type": "tactical"},
            )
            assert r.status_code in (401, 403)
    _run_async(run())


def test_generate_returns_404_for_unknown_video():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.post(
                "/api/analysis/generate",
                json={"video_id": "does-not-exist", "analysis_type": "tactical"},
            )
            assert r.status_code == 404
        finally:
            await c.aclose()
    _run_async(run())


def test_generate_trimmed_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.post(
                "/api/analysis/generate-trimmed",
                json={"video_id": "x", "analysis_type": "tactical"},
            )
            assert r.status_code in (401, 403)
    _run_async(run())


# ---------------------------------------------------------------------------
# 6. Frontend wiring: VideoAnalysis polls the analysis/video endpoint
# ---------------------------------------------------------------------------

def test_frontend_video_analysis_polls_for_completion():
    src = open("/app/frontend/src/pages/VideoAnalysis.js").read()
    assert "pollAnalysisStatus" in src, "frontend must define a polling helper"
    # Polling reads /api/analysis/video/{id} (the same endpoint already used elsewhere)
    assert "/analysis/video/" in src
    # Treats 202 the same way as 200 — does not raise
    assert "res.status === 202" in src or "status === 202" in src
    # No more 5-10 min timeout on the POST request — it's now a 30s budget
    # (since the response is immediate)
    assert "timeout: 30000" in src
    # The old 300s/600s synchronous timeouts must be gone
    assert "timeout: 300000" not in src
    assert "timeout: 600000," not in src or src.count("timeout: 600000") <= 1  # download clip still uses 600000


# ---------------------------------------------------------------------------
# 7. Build endpoint advertises iter98 feature flags
# ---------------------------------------------------------------------------

def test_deploy_endpoint_advertises_iter98_features():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            body = r.json()
            assert body["build"] == "iter98"
            features = set(body["features"])
            assert "async-analysis-generate-202" in features
            assert "async-analysis-generate-trimmed-202" in features
            assert "analysis-status-polling-frontend" in features
            assert "pending-analysis-row-placeholder" in features
    _run_async(run())
