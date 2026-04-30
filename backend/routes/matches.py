"""Match CRUD + recently-deleted-videos lookup."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import uuid
from db import db
from routes.auth import get_current_user

router = APIRouter()


class Match(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    team_home: str
    team_away: str
    date: str
    competition: str = ""
    folder_id: Optional[str] = None
    video_id: Optional[str] = None
    has_manual_result: bool = False
    manual_result: Optional[dict] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MatchCreate(BaseModel):
    team_home: str
    team_away: str
    date: str
    competition: str = ""
    folder_id: Optional[str] = None


@router.post("/matches", response_model=Match)
async def create_match(input: MatchCreate, current_user: dict = Depends(get_current_user)):
    match_obj = Match(user_id=current_user["id"], **input.model_dump())
    await db.matches.insert_one(match_obj.model_dump())
    return match_obj


@router.get("/matches", response_model=List[Match])
async def get_matches(current_user: dict = Depends(get_current_user)):
    matches = await db.matches.find(
        {"user_id": current_user["id"]}, {"_id": 0}
    ).to_list(1000)
    for match in matches:
        if match.get("video_id"):
            video = await db.videos.find_one(
                {"id": match["video_id"]},
                {"_id": 0, "processing_status": 1, "processing_progress": 1},
            )
            if video:
                match["processing_status"] = video.get("processing_status", "none")
                match["processing_progress"] = video.get("processing_progress", 0)
    return matches

@router.get("/matches/{match_id}", response_model=Match)
async def get_match(match_id: str, current_user: dict = Depends(get_current_user)):
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


@router.patch("/matches/{match_id}")
async def update_match(
    match_id: str, updates: dict, current_user: dict = Depends(get_current_user)
):
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    allowed = {"folder_id", "team_home", "team_away", "date", "competition"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if filtered:
        await db.matches.update_one({"id": match_id}, {"$set": filtered})
    return {"status": "updated"}


@router.get("/matches/{match_id}/deleted-videos")
async def list_deleted_videos(
    match_id: str, current_user: dict = Depends(get_current_user)
):
    """Recently deleted videos for a match (24h restore window)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return await db.videos.find(
        {
            "match_id": match_id,
            "user_id": current_user["id"],
            "is_deleted": True,
            "deleted_at": {"$gte": cutoff},
        },
        {"_id": 0, "chunk_paths": 0, "chunk_sizes": 0, "chunk_backends": 0},
    ).sort("deleted_at", -1).to_list(20)


class ManualKeyEvent(BaseModel):
    type: str  # 'goal', 'shot', 'save', 'foul', 'card', 'sub', 'note'
    minute: int = 0
    team: str = ""  # must match team_home or team_away
    player_id: Optional[str] = None
    description: str = ""


class ManualResult(BaseModel):
    home_score: int = Field(ge=0, le=99)
    away_score: int = Field(ge=0, le=99)
    key_events: List[ManualKeyEvent] = Field(default_factory=list, max_length=60)
    notes: str = Field(default="", max_length=2000)


@router.put("/matches/{match_id}/manual-result")
async def save_manual_result(
    match_id: str,
    body: ManualResult,
    current_user: dict = Depends(get_current_user),
):
    """Record the outcome of a match that has no video uploaded.

    Counts toward Season Trends (W/D/L, GF/GA) just like video-derived results.
    Safe to call multiple times — replaces previous manual result.
    """
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]}, {"_id": 0, "id": 1, "team_home": 1, "team_away": 1},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    payload = body.model_dump()
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["updated_by"] = current_user["id"]
    # Compute derived outcome from the home team's perspective so downstream
    # aggregations don't have to recompute.
    payload["outcome"] = (
        "W" if body.home_score > body.away_score
        else "L" if body.home_score < body.away_score
        else "D"
    )
    await db.matches.update_one(
        {"id": match_id},
        {"$set": {"manual_result": payload, "has_manual_result": True}},
    )
    return {"status": "saved", "manual_result": payload}


@router.delete("/matches/{match_id}/manual-result")
async def delete_manual_result(
    match_id: str, current_user: dict = Depends(get_current_user)
):
    """Remove a manual result (e.g. once video is uploaded and processed)."""
    res = await db.matches.update_one(
        {"id": match_id, "user_id": current_user["id"]},
        {"$unset": {"manual_result": "", "has_manual_result": ""}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Match not found")
    return {"status": "deleted"}


@router.get("/matches/{match_id}/manual-result")
async def get_manual_result(
    match_id: str, current_user: dict = Depends(get_current_user)
):
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]},
        {"_id": 0, "manual_result": 1},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match.get("manual_result") or {}


# ===== Bulk match operations =====


class BulkMatchAction(BaseModel):
    match_ids: List[str] = Field(min_length=1, max_length=200)
    folder_id: Optional[str] = None  # for "move" action
    competition: Optional[str] = None  # for "set_competition" action


@router.post("/matches/bulk/move")
async def bulk_move_matches(
    body: BulkMatchAction, current_user: dict = Depends(get_current_user)
):
    """Move selected matches into a folder (or to root if folder_id is null)."""
    if body.folder_id:
        folder = await db.folders.find_one(
            {"id": body.folder_id, "user_id": current_user["id"]}, {"_id": 0}
        )
        if not folder:
            raise HTTPException(status_code=404, detail="Target folder not found")
    res = await db.matches.update_many(
        {"id": {"$in": body.match_ids}, "user_id": current_user["id"]},
        {"$set": {"folder_id": body.folder_id}},
    )
    return {"status": "moved", "count": res.modified_count}


@router.post("/matches/bulk/competition")
async def bulk_set_competition(
    body: BulkMatchAction, current_user: dict = Depends(get_current_user)
):
    """Set the same competition value across multiple matches."""
    if body.competition is None:
        raise HTTPException(status_code=400, detail="competition is required")
    res = await db.matches.update_many(
        {"id": {"$in": body.match_ids}, "user_id": current_user["id"]},
        {"$set": {"competition": body.competition}},
    )
    return {"status": "updated", "count": res.modified_count}


@router.post("/matches/bulk/delete")
async def bulk_delete_matches(
    body: BulkMatchAction, current_user: dict = Depends(get_current_user)
):
    """Delete multiple matches and cascade-delete their derived data.

    For each match, also: hard-delete clips/analyses/markers tied to the match's
    video, and unlink any folder references. The video file itself is left
    soft-deleted (not purged) so the same 24h restore window applies.
    """
    matches = await db.matches.find(
        {"id": {"$in": body.match_ids}, "user_id": current_user["id"]},
        {"_id": 0, "id": 1, "video_id": 1},
    ).to_list(500)

    video_ids = [m["video_id"] for m in matches if m.get("video_id")]
    deleted_count = 0
    for m in matches:
        # Cascade derived data
        if m.get("video_id"):
            await db.clips.delete_many(
                {"video_id": m["video_id"], "user_id": current_user["id"]}
            )
            await db.analyses.delete_many(
                {"video_id": m["video_id"], "user_id": current_user["id"]}
            )
            await db.markers.delete_many(
                {"video_id": m["video_id"], "user_id": current_user["id"]}
            )
        await db.matches.delete_one({"id": m["id"]})
        deleted_count += 1

    # Soft-delete associated videos so the 24h restore window still applies if
    # the user changes their mind. Permanent purge happens via the sweeper.
    if video_ids:
        await db.videos.update_many(
            {"id": {"$in": video_ids}, "user_id": current_user["id"]},
            {"$set": {
                "is_deleted": True,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    return {"status": "deleted", "count": deleted_count}
