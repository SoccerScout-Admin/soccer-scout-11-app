"""Highlight Reel routes — generate, list, stream, share.

Endpoints (all under /api):
  POST   /matches/{match_id}/highlight-reel           Create + enqueue a reel
  GET    /matches/{match_id}/highlight-reels          List reels for a match
  GET    /highlight-reels/browse                      Public browse feed
  GET    /highlight-reels/browse/competitions         Distinct competitions
  GET    /highlight-reels/trending                    Top reels by views (7d)
  GET    /highlight-reels/{reel_id}                   Reel status + meta
  DELETE /highlight-reels/{reel_id}                   Delete a reel
  POST   /highlight-reels/{reel_id}/share             Toggle share token
  POST   /highlight-reels/{reel_id}/retry             Retry failed reel
  GET    /highlight-reels/{reel_id}/video             Stream the mp4 (auth)
  GET    /highlight-reels/public/{share_token}        Public JSON (records view)
  GET    /highlight-reels/public/{share_token}/video  Public video stream

OG share-card endpoints live in `routes/og.py`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from db import db
from routes.auth import get_current_user
from services.highlight_reel import enqueue_reel, is_ffmpeg_available
from services.scout_digest import record_reel_view, trending_reel_ids, reel_view_count

logger = logging.getLogger(__name__)


async def _record_view_safely(reel_id: str, anon_fp: str | None) -> None:
    """Fire-and-forget wrapper around `record_reel_view` — swallows errors so
    a view-tracking failure can never break the share page response."""
    try:
        await record_reel_view(reel_id, viewer_user_id=None, anon_fingerprint=anon_fp)
    except Exception as exc:
        logger.warning("[reel-view] swallowed: %s", exc)


router = APIRouter()


def _strip_internal(reel: dict) -> dict:
    """Public-safe projection of a reel doc (hides absolute filesystem path)."""
    safe = {k: v for k, v in reel.items() if k != "_id"}
    # Coerce the output path to a boolean ready-state hint instead of a fs path
    safe.pop("output_path", None)
    return safe


async def _load_match(match_id: str, user_id: str) -> dict:
    match = await db.matches.find_one(
        {"id": match_id, "user_id": user_id}, {"_id": 0},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


@router.post("/matches/{match_id}/highlight-reel")
async def create_highlight_reel(
    match_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Create a new highlight reel for a match and enqueue processing.

    A match can have multiple reels (re-runs after editing clips, etc.).
    """
    if not is_ffmpeg_available():
        raise HTTPException(status_code=503, detail="ffmpeg is not available on this server.")

    match = await _load_match(match_id, current_user["id"])

    # Per-user concurrent-reel cap — protects the ffmpeg worker queue from
    # spam (intentional or accidental rapid-fire). 3 in-flight per user is
    # generous given each reel takes a few minutes to finish.
    in_flight = await db.highlight_reels.count_documents({
        "user_id": current_user["id"],
        "status": {"$in": ["pending", "processing"]},
    })
    if in_flight >= 3:
        raise HTTPException(
            status_code=429,
            detail="You already have 3 reels in progress. Wait for at least one to finish before generating another.",
        )

    clip_count = await db.clips.count_documents(
        {"match_id": match_id, "user_id": current_user["id"]},
    )
    if clip_count == 0:
        raise HTTPException(
            status_code=400,
            detail="This match has no clips yet. Add some clips first (or run AI analysis on the video) before generating a reel.",
        )

    reel_id = str(uuid.uuid4())
    doc = {
        "id": reel_id,
        "user_id": current_user["id"],
        "match_id": match_id,
        "status": "pending",
        "progress": 0.0,
        "selected_clip_ids": [],
        "total_clips": 0,
        "duration_seconds": 0.0,
        "output_path": None,
        "share_token": None,
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        # snapshot of the match label so the listing card has it without join
        "match_title": f"{match.get('team_home', '')} vs {match.get('team_away', '')}".strip(),
    }
    await db.highlight_reels.insert_one(doc)
    await enqueue_reel(reel_id)
    doc.pop("_id", None)
    return _strip_internal(doc)


@router.get("/matches/{match_id}/highlight-reels")
async def list_highlight_reels(
    match_id: str,
    current_user: dict = Depends(get_current_user),
):
    await _load_match(match_id, current_user["id"])
    reels = await db.highlight_reels.find(
        {"match_id": match_id, "user_id": current_user["id"]},
        {"_id": 0},
    ).sort("created_at", -1).to_list(50)
    return [_strip_internal(r) for r in reels]



@router.get("/highlight-reels/trending")
async def trending_reels(limit: int = 12, days: int = 7):
    """Top reels by unique-view count over the last `days` window.

    Public endpoint — same shape as `/browse` so the frontend can reuse the
    same tile component. Only `ready` reels with a `share_token` are
    returned (so revoked-sharing reels disappear automatically).
    """
    limit = max(1, min(24, int(limit)))
    days = max(1, min(60, int(days)))

    top = await trending_reel_ids(window_days=days, limit=limit * 2)  # over-fetch in case some are now revoked
    if not top:
        return {"reels": [], "window_days": days}

    by_id = {t["reel_id"]: t["view_count"] for t in top}
    reels = await db.highlight_reels.find(
        {
            "id": {"$in": list(by_id.keys())},
            "status": "ready",
            "share_token": {"$ne": None},
        },
        {"_id": 0},
    ).to_list(len(by_id))
    if not reels:
        return {"reels": [], "window_days": days}

    match_ids = list({r["match_id"] for r in reels})
    user_ids = list({r["user_id"] for r in reels})
    matches = {
        m["id"]: m
        for m in await db.matches.find(
            {"id": {"$in": match_ids}},
            {"_id": 0, "id": 1, "team_home": 1, "team_away": 1, "competition": 1, "date": 1, "manual_result": 1},
        ).to_list(len(match_ids) or 1)
    }
    users = {
        u["id"]: u
        for u in await db.users.find(
            {"id": {"$in": user_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(len(user_ids) or 1)
    }

    out = []
    for r in reels:
        m = matches.get(r["match_id"]) or {}
        u = users.get(r["user_id"]) or {}
        mr = m.get("manual_result") or {}
        out.append({
            "id": r["id"],
            "share_token": r["share_token"],
            "team_home": m.get("team_home", ""),
            "team_away": m.get("team_away", ""),
            "competition": m.get("competition", "") or "",
            "date": m.get("date"),
            "coach_name": u.get("name", ""),
            "total_clips": r.get("total_clips", 0),
            "duration_seconds": r.get("duration_seconds", 0.0),
            "created_at": r.get("created_at"),
            "view_count": by_id.get(r["id"], 0),
            "home_score": mr.get("home_score"),
            "away_score": mr.get("away_score"),
        })

    out.sort(key=lambda x: x["view_count"], reverse=True)
    return {"reels": out[:limit], "window_days": days}


def _reel_counters(my_reels: list) -> dict:
    """Compute the simple per-reel-list counters (totals/ready/shared)."""
    return {
        "total_reels": len(my_reels),
        "ready_reels": sum(1 for r in my_reels if r.get("status") == "ready"),
        "shared_reels": sum(1 for r in my_reels if r.get("share_token")),
    }


async def _aggregate_7d_views(reel_ids: list[str]) -> tuple[int, list]:
    """Return (total_7d_views, rows_sorted_desc_by_view_count) for the given
    set of reel IDs. rows shape: [{_id: reel_id, view_count: int}, ...]"""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    pipeline = [
        {"$match": {"reel_id": {"$in": reel_ids}, "viewed_at": {"$gt": cutoff}}},
        {"$group": {"_id": "$reel_id", "view_count": {"$sum": 1}}},
        {"$sort": {"view_count": -1}},
    ]
    rows = await db.highlight_reel_views.aggregate(pipeline).to_list(len(reel_ids) or 1)
    return sum(r["view_count"] for r in rows), rows


async def _resolve_top_reel(rows: list, my_lookup: dict) -> Optional[dict]:
    """Find the highest-view, still-active (ready + shared) reel and shape it
    into the dashboard card. Returns None if no eligible reel found."""
    for row in rows:
        r = my_lookup.get(row["_id"])
        if not r or r.get("status") != "ready" or not r.get("share_token"):
            continue
        match = await db.matches.find_one(
            {"id": r["match_id"]},
            {"_id": 0, "team_home": 1, "team_away": 1},
        )
        return {
            "id": r["id"],
            "share_token": r["share_token"],
            "team_home": (match or {}).get("team_home", ""),
            "team_away": (match or {}).get("team_away", ""),
            "view_count": row["view_count"],
            "total_clips": r.get("total_clips", 0),
            "duration_seconds": r.get("duration_seconds", 0.0),
        }
    return None


@router.get("/highlight-reels/my-stats")
async def my_reel_stats(current_user: dict = Depends(get_current_user)):
    """Dashboard card data — the owner's own reel stats.

    Returns:
      - total_reels, ready_reels, shared_reels (active share tokens)
      - views_7d, views_all_time (across all my reels)
      - top_reel — { id, share_token, team_home, team_away, view_count }
        for the owner's most-viewed reel in the last 7 days, OR None

    Refactored iter66 — extracted _reel_counters, _aggregate_7d_views,
    _resolve_top_reel so this stays under CC=10.
    """
    user_id = current_user["id"]
    my_reels = await db.highlight_reels.find(
        {"user_id": user_id},
        {"_id": 0, "id": 1, "status": 1, "share_token": 1, "match_id": 1, "total_clips": 1, "duration_seconds": 1},
    ).to_list(500)

    counters = _reel_counters(my_reels)
    if not my_reels:
        return {**counters, "views_7d": 0, "views_all_time": 0, "top_reel": None}

    reel_ids = [r["id"] for r in my_reels]
    views_all_time = await db.highlight_reel_views.count_documents(
        {"reel_id": {"$in": reel_ids}},
    )
    views_7d, rows = await _aggregate_7d_views(reel_ids)
    top_reel = await _resolve_top_reel(rows, {r["id"]: r for r in my_reels}) if rows else None

    return {**counters, "views_7d": views_7d, "views_all_time": views_all_time, "top_reel": top_reel}


@router.post("/admin/highlight-reels/send-weekly-recap")
async def admin_send_reel_recap(current_user: dict = Depends(get_current_user)):
    """Admin-only manual trigger for the weekly Reel Recap email."""
    if (current_user.get("role") or "").lower() not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin only")
    from services.reel_recap import send_weekly_reel_recap
    return await send_weekly_reel_recap(triggered_by="manual")


async def _load_reels_with_context(base_query: dict) -> tuple[list, dict, dict]:
    """Pull ready/shared reels + their matches + their coach users in 3
    parallel-ish Mongo calls. Returns (reels, matches_by_id, users_by_id)."""
    reels = await db.highlight_reels.find(
        base_query, {"_id": 0},
    ).sort("created_at", -1).to_list(500)

    match_ids = list({r["match_id"] for r in reels})
    user_ids = list({r["user_id"] for r in reels})
    matches = {
        m["id"]: m
        for m in await db.matches.find(
            {"id": {"$in": match_ids}},
            {"_id": 0, "id": 1, "team_home": 1, "team_away": 1, "competition": 1, "date": 1, "manual_result": 1},
        ).to_list(len(match_ids) or 1)
    }
    users = {
        u["id"]: u
        for u in await db.users.find(
            {"id": {"$in": user_ids}},
            {"_id": 0, "id": 1, "name": 1},
        ).to_list(len(user_ids) or 1)
    }
    return reels, matches, users


def _reel_passes_filter(comp: str, team_h: str, team_a: str, coach: str,
                       comp_filter: str, needle: str) -> bool:
    """Filter predicate for browse — separated so we can unit-test the matching
    logic without touching Mongo."""
    if comp_filter and comp != comp_filter:
        return False
    if needle:
        haystack = f"{team_h} {team_a} {coach}".lower()
        if needle not in haystack:
            return False
    return True


def _build_reel_card(r: dict, match: dict, owner: dict) -> dict:
    """Shape one public-feed reel card. No filesystem path, no user_id."""
    mr = match.get("manual_result") or {}
    return {
        "id": r["id"],
        "share_token": r["share_token"],
        "team_home": match.get("team_home") or "",
        "team_away": match.get("team_away") or "",
        "competition": match.get("competition") or "",
        "date": match.get("date"),
        "coach_name": owner.get("name") or "",
        "total_clips": r.get("total_clips", 0),
        "duration_seconds": r.get("duration_seconds", 0.0),
        "created_at": r.get("created_at"),
        "home_score": mr.get("home_score"),
        "away_score": mr.get("away_score"),
    }


def _reel_context(r: dict, matches: dict, users: dict) -> tuple[dict, dict, str, str, str, str]:
    """Return (match, owner, comp, team_h, team_a, coach) for a reel — pre-
    coercing all the optional fields once instead of doing it inline in the
    loop (every `or ""` was bumping browse_public_reels' CC)."""
    match = matches.get(r["match_id"]) or {}
    owner = users.get(r["user_id"]) or {}
    return (
        match, owner,
        match.get("competition") or "",
        match.get("team_home") or "",
        match.get("team_away") or "",
        owner.get("name") or "",
    )


@router.get("/highlight-reels/browse")
async def browse_public_reels(
    q: str = "",
    competition: str = "",
    limit: int = 24,
    offset: int = 0,
):
    """Public browse feed of shared highlight reels.

    Only `ready` reels with a `share_token` appear. Filters:
      - `q` — case-insensitive substring match against team names or coach name
      - `competition` — exact competition name match (use empty for "All")
    Pagination: `limit` (1-50) + `offset`.
    Returns lightweight cards (no filesystem path, no user_id).

    Refactored iter66 — extracted _load_reels_with_context,
    _reel_passes_filter, _build_reel_card, _reel_context to stay under CC=10.
    """
    limit = max(1, min(50, int(limit)))
    offset = max(0, int(offset))

    reels, matches, users = await _load_reels_with_context(
        {"status": "ready", "share_token": {"$ne": None}}
    )

    needle = (q or "").strip().lower()
    comp_filter = (competition or "").strip()

    out = []
    for r in reels:
        match, owner, comp, team_h, team_a, coach = _reel_context(r, matches, users)
        if not _reel_passes_filter(comp, team_h, team_a, coach, comp_filter, needle):
            continue
        out.append(_build_reel_card(r, match, owner))
        if len(out) >= offset + limit:
            break

    return {
        "reels": out[offset:offset + limit],
        "total": len(out),
        "has_more": len(out) > offset + limit,
    }


@router.get("/highlight-reels/browse/competitions")
async def browse_competitions():
    """List distinct competitions across all publicly-shared reels.

    Powers the filter chips on the browse page.
    """
    reels = await db.highlight_reels.find(
        {"status": "ready", "share_token": {"$ne": None}},
        {"_id": 0, "match_id": 1},
    ).to_list(500)
    if not reels:
        return {"competitions": []}
    match_ids = list({r["match_id"] for r in reels})
    matches = await db.matches.find(
        {"id": {"$in": match_ids}},
        {"_id": 0, "competition": 1},
    ).to_list(len(match_ids))
    comps = sorted({(m.get("competition") or "").strip() for m in matches if (m.get("competition") or "").strip()})
    return {"competitions": comps}


@router.get("/highlight-reels/{reel_id}")
async def get_highlight_reel(
    reel_id: str,
    current_user: dict = Depends(get_current_user),
):
    reel = await db.highlight_reels.find_one(
        {"id": reel_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    return _strip_internal(reel)


@router.delete("/highlight-reels/{reel_id}")
async def delete_highlight_reel(
    reel_id: str,
    current_user: dict = Depends(get_current_user),
):
    reel = await db.highlight_reels.find_one(
        {"id": reel_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    out = reel.get("output_path")
    if out and os.path.exists(out):
        try:
            os.unlink(out)
        except OSError:
            pass
    await db.highlight_reels.delete_one({"id": reel_id})
    return {"status": "deleted"}


@router.post("/highlight-reels/{reel_id}/share")
async def toggle_reel_share(
    reel_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Toggle a public share token for the reel. Idempotent."""
    reel = await db.highlight_reels.find_one(
        {"id": reel_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    if reel.get("status") != "ready":
        raise HTTPException(
            status_code=400,
            detail="Reel is not ready yet. Wait for processing to complete before sharing.",
        )
    if reel.get("share_token"):
        await db.highlight_reels.update_one(
            {"id": reel_id}, {"$set": {"share_token": None}},
        )
        return {"status": "unshared", "share_token": None}
    token = str(uuid.uuid4())[:12]
    await db.highlight_reels.update_one(
        {"id": reel_id}, {"$set": {"share_token": token}},
    )
    return {"status": "shared", "share_token": token}


@router.post("/highlight-reels/{reel_id}/retry")
async def retry_highlight_reel(
    reel_id: str,
    current_user: dict = Depends(get_current_user),
):
    reel = await db.highlight_reels.find_one(
        {"id": reel_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    if reel.get("status") not in ("failed", "pending"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot retry — current status is '{reel.get('status')}'.",
        )
    await db.highlight_reels.update_one(
        {"id": reel_id},
        {"$set": {"status": "pending", "error": None, "progress": 0.0}},
    )
    await enqueue_reel(reel_id)
    return {"status": "queued"}


def _stream_file(path: str, chunk_size: int = 1024 * 1024):
    with open(path, "rb") as fh:
        while True:
            data = fh.read(chunk_size)
            if not data:
                break
            yield data


@router.get("/highlight-reels/{reel_id}/video")
async def stream_reel_video(
    reel_id: str,
    current_user: dict = Depends(get_current_user),
):
    reel = await db.highlight_reels.find_one(
        {"id": reel_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found")
    out = reel.get("output_path")
    if reel.get("status") != "ready" or not out or not os.path.exists(out):
        raise HTTPException(status_code=409, detail="Reel video is not ready yet.")
    return StreamingResponse(
        _stream_file(out),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'attachment; filename="highlight-reel-{reel_id[:8]}.mp4"',
        },
    )


# ----- Public (share-token) endpoints -----

@router.get("/highlight-reels/public/{share_token}")
async def get_public_reel(share_token: str, request: Request):
    """Public JSON for SPA route `/reel/:shareToken`.

    Records a unique view (24h debounce per viewer) used by `/trending` and
    reflected in the response as `view_count`. View tracking is fire-and-forget
    so it doesn't add latency to the share-page load.
    """
    reel = await db.highlight_reels.find_one(
        {"share_token": share_token}, {"_id": 0},
    )
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found or sharing was revoked")

    # Fire-and-forget view recording — never blocks the page render.
    ip = (request.client.host if request.client else "") or ""
    ua = request.headers.get("user-agent", "")
    anon_fp = f"{ip}|{ua}" if ip or ua else None
    asyncio.create_task(_record_view_safely(reel["id"], anon_fp))

    match = await db.matches.find_one(
        {"id": reel["match_id"]},
        {"_id": 0, "team_home": 1, "team_away": 1, "competition": 1, "date": 1, "manual_result": 1},
    )
    owner = await db.users.find_one(
        {"id": reel["user_id"]}, {"_id": 0, "name": 1},
    )

    # Public projection: hide owner_id + filesystem path
    safe = _strip_internal(reel)
    safe.pop("user_id", None)
    safe["coach_name"] = (owner or {}).get("name", "")
    safe["view_count"] = await reel_view_count(reel["id"])
    if match:
        safe["team_home"] = match.get("team_home")
        safe["team_away"] = match.get("team_away")
        safe["competition"] = match.get("competition", "")
        safe["date"] = match.get("date")
        mr = match.get("manual_result") or {}
        if mr.get("home_score") is not None:
            safe["home_score"] = mr.get("home_score")
            safe["away_score"] = mr.get("away_score")
    return safe


@router.get("/highlight-reels/public/{share_token}/video")
async def stream_public_reel_video(share_token: str):
    reel = await db.highlight_reels.find_one(
        {"share_token": share_token}, {"_id": 0},
    )
    if not reel:
        raise HTTPException(status_code=404, detail="Invalid share link")
    out = reel.get("output_path")
    if reel.get("status") != "ready" or not out or not os.path.exists(out):
        raise HTTPException(status_code=409, detail="Reel video is not ready yet.")
    return StreamingResponse(
        _stream_file(out),
        media_type="video/mp4",
    )
