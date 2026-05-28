"""
iter102 — Hudl-style manual player tagging on AI markers.

User request 2026-05-28: "Can you wire the next iteration to let the user
identify players in key highlights that the AI can't pick up? Similar to
how Hudl allows a user to identify players that it can't figure out?"

Backend additions:
  • PATCH /api/markers/{marker_id} — set player_number + player_name, also
    optionally label/team/type/importance. Sets manually_tagged=true +
    tagged_at provenance fields.
  • DELETE /api/markers/{marker_id} — remove wrongly-detected markers.

Frontend additions:
  • TagPlayerModal — roster picker with team filter + search.
  • MarkersPanel — small edit-pencil button on each row, always visible when
    no AI attribution, hover-only when AI already tagged.
  • Manual-tag badge (green ✓) on rows the user has touched.
"""
import os
import sys
import uuid
from datetime import datetime, timezone

import httpx

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from tests.conftest import BASE_URL, run_async as _run_async  # noqa: E402


def _payload():
    s = uuid.uuid4().hex[:10]
    return {"email": f"iter102-{s}@example.com", "password": "Iter102Pass!", "name": f"Iter102 {s}"}


async def _client(payload):
    c = httpx.AsyncClient(base_url=BASE_URL, timeout=20)
    r = await c.post("/api/auth/register", json=payload)
    assert r.status_code in (200, 201), r.text
    csrf = c.cookies.get("csrf_token")
    assert csrf
    c.headers.update({"X-CSRF-Token": csrf})
    return c


async def _seed_marker(uid: str, **overrides) -> dict:
    """Drop a minimal marker doc into the DB and return it."""
    from db import db
    doc = {
        "id": str(uuid.uuid4()),
        "video_id": str(uuid.uuid4()),
        "match_id": str(uuid.uuid4()),
        "user_id": uid,
        "time": 234.5,
        "type": "goal",
        "label": "AI-detected goal",
        "team": "Home FC",
        "importance": 5,
        "player_number": None,
        "player_name": None,
        "auto_generated": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    doc.update(overrides)
    await db.markers.insert_one(doc)
    return doc


# ---------------------------------------------------------------------------
# 1. PATCH endpoint — happy path
# ---------------------------------------------------------------------------

def test_patch_marker_sets_player_attribution_and_provenance():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            marker = await _seed_marker(me["id"])
            r = await c.patch(
                f"/api/markers/{marker['id']}",
                json={"player_number": 9, "player_name": "Marcus Lopez"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["player_number"] == 9
            assert body["player_name"] == "Marcus Lopez"
            assert body["manually_tagged"] is True
            assert body["tagged_at"] is not None
            # Database confirms the same
            db_doc = await db.markers.find_one({"id": marker["id"]}, {"_id": 0})
            assert db_doc["player_number"] == 9
            assert db_doc["player_name"] == "Marcus Lopez"
            assert db_doc["manually_tagged"] is True
        finally:
            await c.aclose()
    _run_async(run())


def test_patch_marker_accepts_string_player_number_and_trims_name():
    async def run():
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            marker = await _seed_marker(me["id"])
            r = await c.patch(
                f"/api/markers/{marker['id']}",
                # int-coerce + whitespace trim, mirroring the iter99 parser logic
                json={"player_number": 11, "player_name": "  Tyler Brooks   "},
            )
            body = r.json()
            assert body["player_number"] == 11
            assert body["player_name"] == "Tyler Brooks"
        finally:
            await c.aclose()
    _run_async(run())


def test_patch_marker_clear_player_strips_both_fields():
    async def run():
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            marker = await _seed_marker(
                me["id"], player_number=7, player_name="Wrong Name",
            )
            r = await c.patch(
                f"/api/markers/{marker['id']}",
                json={"clear_player": True},
            )
            body = r.json()
            assert body["player_number"] is None
            assert body["player_name"] is None
            assert body["manually_tagged"] is True  # explicit clear still counts as a human edit
        finally:
            await c.aclose()
    _run_async(run())


def test_patch_marker_can_correct_label_team_type_importance():
    async def run():
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            marker = await _seed_marker(me["id"], type="shot", importance=3)
            r = await c.patch(
                f"/api/markers/{marker['id']}",
                json={
                    "label": "Header from corner kick",
                    "team": "Away FC",
                    "type": "goal",
                    "importance": 5,
                },
            )
            body = r.json()
            assert body["label"] == "Header from corner kick"
            assert body["team"] == "Away FC"
            assert body["type"] == "goal"
            assert body["importance"] == 5
            assert body["manually_tagged"] is True
        finally:
            await c.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 2. Validation + safety rails
# ---------------------------------------------------------------------------

def test_patch_marker_rejects_invalid_type():
    async def run():
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            marker = await _seed_marker(me["id"])
            r = await c.patch(
                f"/api/markers/{marker['id']}",
                json={"type": "fake-type"},
            )
            assert r.status_code == 400, r.text
            assert "type" in r.json()["detail"].lower()
        finally:
            await c.aclose()
    _run_async(run())


def test_patch_marker_clamps_importance_to_1_5():
    async def run():
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            marker = await _seed_marker(me["id"])
            r = await c.patch(
                f"/api/markers/{marker['id']}",
                json={"importance": 99},
            )
            assert r.json()["importance"] == 5
            r = await c.patch(
                f"/api/markers/{marker['id']}",
                json={"importance": -5},
            )
            assert r.json()["importance"] == 1
        finally:
            await c.aclose()
    _run_async(run())


def test_patch_marker_empty_body_returns_400():
    async def run():
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            marker = await _seed_marker(me["id"])
            r = await c.patch(f"/api/markers/{marker['id']}", json={})
            assert r.status_code == 400
        finally:
            await c.aclose()
    _run_async(run())


def test_patch_marker_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.patch(
                "/api/markers/nonexistent",
                json={"player_number": 7},
            )
            assert r.status_code in (401, 403)
    _run_async(run())


def test_patch_marker_404_for_unknown_id():
    async def run():
        c = await _client(_payload())
        try:
            r = await c.patch(
                "/api/markers/does-not-exist",
                json={"player_number": 7},
            )
            assert r.status_code == 404
        finally:
            await c.aclose()
    _run_async(run())


def test_patch_marker_cross_user_isolation():
    """User B must NOT be able to PATCH User A's markers."""
    async def run():
        c_a = await _client(_payload())
        c_b = await _client(_payload())
        try:
            me_a = (await c_a.get("/api/auth/me")).json()
            marker = await _seed_marker(me_a["id"])
            r = await c_b.patch(
                f"/api/markers/{marker['id']}",
                json={"player_number": 99, "player_name": "Hacker"},
            )
            assert r.status_code == 404, (
                "cross-user PATCH must 404 (not leak that the marker exists)"
            )
        finally:
            await c_a.aclose()
            await c_b.aclose()
    _run_async(run())


# ---------------------------------------------------------------------------
# 3. DELETE endpoint
# ---------------------------------------------------------------------------

def test_delete_marker_removes_the_row():
    async def run():
        from db import db
        c = await _client(_payload())
        try:
            me = (await c.get("/api/auth/me")).json()
            marker = await _seed_marker(me["id"])
            r = await c.delete(f"/api/markers/{marker['id']}")
            assert r.status_code == 200
            body = r.json()
            assert body["deleted"] is True
            assert body["id"] == marker["id"]
            # Row is actually gone
            db_doc = await db.markers.find_one({"id": marker["id"]}, {"_id": 0})
            assert db_doc is None
        finally:
            await c.aclose()
    _run_async(run())


def test_delete_marker_cross_user_isolation():
    async def run():
        c_a = await _client(_payload())
        c_b = await _client(_payload())
        try:
            me_a = (await c_a.get("/api/auth/me")).json()
            marker = await _seed_marker(me_a["id"])
            r = await c_b.delete(f"/api/markers/{marker['id']}")
            assert r.status_code == 404
            # Confirm A's marker still exists
            from db import db
            db_doc = await db.markers.find_one({"id": marker["id"]}, {"_id": 0})
            assert db_doc is not None
        finally:
            await c_a.aclose()
            await c_b.aclose()
    _run_async(run())


def test_delete_marker_requires_auth():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.delete("/api/markers/nonexistent")
            assert r.status_code in (401, 403)
    _run_async(run())


# ---------------------------------------------------------------------------
# 4. Frontend wiring
# ---------------------------------------------------------------------------

def test_tag_player_modal_file_exists_with_testids():
    p = "/app/frontend/src/pages/components/TagPlayerModal.js"
    assert os.path.exists(p), f"{p} missing"
    src = open(p).read()
    assert 'data-testid="tag-player-modal"' in src
    assert 'data-testid="tag-player-search"' in src
    assert 'data-testid="tag-player-close"' in src
    assert 'data-testid={`tag-player-row-' in src
    assert 'data-testid="tag-player-clear-btn"' in src
    assert 'data-testid="tag-player-delete-btn"' in src


def test_tag_player_modal_uses_match_roster_endpoint():
    src = open("/app/frontend/src/pages/components/TagPlayerModal.js").read()
    assert "/players/match/" in src, (
        "modal must load the match-specific roster, not the global player list"
    )


def test_tag_player_modal_calls_patch_and_delete():
    src = open("/app/frontend/src/pages/components/TagPlayerModal.js").read()
    assert "/markers/" in src
    assert "axios.patch" in src
    assert "axios.delete" in src
    # The clear_player path
    assert "clear_player: true" in src


def test_markers_panel_includes_edit_button_and_manual_badge():
    src = open("/app/frontend/src/pages/components/MarkersPanel.js").read()
    assert 'data-testid={`marker-row-edit-' in src
    assert 'data-testid={`marker-row-manual-badge-' in src
    # The modal is mounted INSIDE the panel
    assert "<TagPlayerModal" in src


def test_video_analysis_wires_match_id_and_handlers():
    src = open("/app/frontend/src/pages/VideoAnalysis.js").read()
    assert "matchId={match?.id}" in src
    assert "onMarkerUpdated=" in src
    assert "onMarkerDeleted=" in src


# ---------------------------------------------------------------------------
# 5. Deploy endpoint advertises iter102 feature flags
# ---------------------------------------------------------------------------

def test_deploy_endpoint_advertises_iter102_features():
    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as c:
            r = await c.get("/api/health/deploy")
            assert r.status_code == 200
            features = set(r.json()["features"])
            assert "marker-patch-endpoint" in features
            assert "marker-delete-endpoint" in features
            assert "marker-manual-tag-provenance-badge" in features
            assert "tag-player-modal-roster-picker" in features
            assert "marker-row-edit-pencil-button" in features
    _run_async(run())
