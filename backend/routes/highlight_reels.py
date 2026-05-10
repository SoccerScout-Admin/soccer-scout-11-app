"""Highlight Reel routes — generate, list, stream, share.

Endpoints (all under /api):
  POST   /matches/{match_id}/highlight-reel           Create + enqueue a reel
  GET    /matches/{match_id}/highlight-reels          List reels for a match
  GET    /highlight-reels/{reel_id}                   Reel status + meta
  DELETE /highlight-reels/{reel_id}                   Delete a reel
  POST   /highlight-reels/{reel_id}/share             Toggle share token
  POST   /highlight-reels/{reel_id}/retry             Retry failed reel
  GET    /highlight-reels/{reel_id}/video             Stream the mp4 (auth)
  GET    /highlight-reels/public/{share_token}        Public JSON for SPA
  GET    /highlight-reels/public/{share_token}/video  Public video stream

OG share-card endpoints live in `routes/og.py`.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from db import db
from routes.auth import get_current_user
from services.highlight_reel import enqueue_reel, is_ffmpeg_available

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
async def get_public_reel(share_token: str):
    """Public JSON for SPA route `/reel/:shareToken`."""
    reel = await db.highlight_reels.find_one(
        {"share_token": share_token}, {"_id": 0},
    )
    if not reel:
        raise HTTPException(status_code=404, detail="Reel not found or sharing was revoked")

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
