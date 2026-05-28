"""Read-only analysis endpoints (highlights package, markers, analysis listing).

NOTE: The heavy AI-generation endpoints (`/analysis/generate`, `/process/...`)
remain in server.py because they depend on the auto-processing pipeline,
FFmpeg helpers, and Gemini integration that would introduce circular imports.
"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel
from db import db
from routes.auth import get_current_user

router = APIRouter()


class MarkerTagInput(BaseModel):
    """iter102 — body for the manual marker-tag PATCH.

    All fields optional so the same endpoint can be used to:
      - Tag a player (set player_number + player_name)
      - Clear a wrong AI tag (set both to null)
      - Fix the label/team/type/importance the AI got wrong
    Only the provided fields are updated; others are left untouched.
    """
    player_number: Optional[int] = None
    player_name: Optional[str] = None
    clear_player: Optional[bool] = False  # explicit opt-in to overwrite player_* with null
    label: Optional[str] = None
    team: Optional[str] = None
    type: Optional[str] = None
    importance: Optional[int] = None


_ALLOWED_MARKER_TYPES = {
    "goal", "shot", "save", "foul", "card",
    "substitution", "tactical", "chance",
}


@router.get("/analysis/video/{video_id}")
async def get_analyses(
    video_id: str, current_user: dict = Depends(get_current_user)
):
    return await db.analyses.find(
        {"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(100)


@router.get("/highlights/video/{video_id}")
async def get_highlights_package(
    video_id: str, current_user: dict = Depends(get_current_user)
):
    """Combined match + clips + analyses bundle for a 'highlights export' view."""
    video = await db.videos.find_one(
        {"id": video_id, "user_id": current_user["id"], "is_deleted": False},
        {"_id": 0},
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})
    clips = await db.clips.find(
        {"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(1000)
    analyses = await db.analyses.find(
        {"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(100)
    return {
        "match": match,
        "video": {
            "id": video["id"],
            "filename": video["original_filename"],
            "size": video["size"],
        },
        "clips": clips,
        "analyses": analyses,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/markers/video/{video_id}")
async def get_markers(
    video_id: str, current_user: dict = Depends(get_current_user)
):
    return await db.markers.find(
        {"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(500)


@router.patch("/markers/{marker_id}")
async def update_marker(
    marker_id: str,
    body: MarkerTagInput,
    current_user: dict = Depends(get_current_user),
):
    """iter102 — Manually correct an AI marker (Hudl-style player tagging).

    Most common use case: AI couldn't read a jersey number → user clicks
    "Tag player" → picks from the match roster → marker gets player_number +
    player_name filled in plus a `manually_tagged: true` provenance flag so
    the UI can distinguish auto vs human-curated.
    """
    marker = await db.markers.find_one(
        {"id": marker_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not marker:
        raise HTTPException(status_code=404, detail="Marker not found")

    updates: dict = {}
    # Player attribution
    if body.clear_player:
        updates["player_number"] = None
        updates["player_name"] = None
    else:
        if body.player_number is not None:
            updates["player_number"] = int(body.player_number)
        if body.player_name is not None:
            updates["player_name"] = body.player_name.strip()[:60] or None
    # Optional event-shape corrections — the AI sometimes guesses wrong
    if body.label is not None:
        updates["label"] = body.label.strip()[:100]
    if body.team is not None:
        updates["team"] = body.team.strip()[:50] or "neutral"
    if body.type is not None:
        if body.type not in _ALLOWED_MARKER_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid type. Must be one of: {sorted(_ALLOWED_MARKER_TYPES)}",
            )
        updates["type"] = body.type
    if body.importance is not None:
        updates["importance"] = max(1, min(5, int(body.importance)))

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # iter102 — provenance: mark this row as human-curated so the UI can
    # render a "verified by you" badge instead of the AI badge.
    updates["manually_tagged"] = True
    updates["tagged_at"] = datetime.now(timezone.utc).isoformat()

    await db.markers.update_one({"id": marker_id}, {"$set": updates})
    refreshed = await db.markers.find_one({"id": marker_id}, {"_id": 0})
    return refreshed


@router.delete("/markers/{marker_id}")
async def delete_marker(
    marker_id: str, current_user: dict = Depends(get_current_user)
):
    """iter102 — Allow removing a wrongly-detected marker (e.g., AI logged a
    'goal' for what was actually a near-miss + restart from kickoff)."""
    res = await db.markers.delete_one(
        {"id": marker_id, "user_id": current_user["id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Marker not found")
    return {"deleted": True, "id": marker_id}
