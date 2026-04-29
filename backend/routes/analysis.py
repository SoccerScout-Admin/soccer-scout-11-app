"""Read-only analysis endpoints (highlights package, markers, analysis listing).

NOTE: The heavy AI-generation endpoints (`/analysis/generate`, `/process/...`)
remain in server.py because they depend on the auto-processing pipeline,
FFmpeg helpers, and Gemini integration that would introduce circular imports.
"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from db import db
from routes.auth import get_current_user

router = APIRouter()


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
