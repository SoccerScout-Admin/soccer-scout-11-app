"""Video read endpoints — access token, metadata, processing status.

Heavier endpoints (streaming with Range support, upload chunking, soft-delete,
reprocess, AI-generation) deliberately stay in server.py because they're tightly
coupled with the chunked-upload pipeline and the AI auto-processing background task.
"""
import os
import time
import jwt
from fastapi import APIRouter, HTTPException, Depends
from db import db, JWT_SECRET
from routes.auth import get_current_user

router = APIRouter()


def _get_server_boot_id():
    """Lazy-load SERVER_BOOT_ID from server module so we don't create a circular import.
    server.py owns the live boot-id constant; we read it on demand.
    """
    import server  # local import — server already imports this router *after* it's mounted
    return server.SERVER_BOOT_ID


@router.get("/videos/{video_id}/access-token")
async def get_video_access_token(video_id: str, current_user: dict = Depends(get_current_user)):
    """Generate a short-lived access token for video streaming (prevents exposing main JWT in URLs)."""
    video = await db.videos.find_one(
        {"id": video_id, "user_id": current_user["id"], "is_deleted": False},
        {"_id": 0, "id": 1},
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    video_token = jwt.encode(
        {
            "user_id": current_user["id"],
            "video_id": video_id,
            "exp": int(time.time()) + 300,
            "type": "video_access",
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return {"token": video_token}


@router.get("/videos/{video_id}/metadata")
async def get_video_metadata(video_id: str, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one(
        {"id": video_id, "user_id": current_user["id"], "is_deleted": False},
        {"_id": 0},
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    # Don't send chunk_paths in metadata (too large for large uploads)
    result = {k: v for k, v in video.items() if k not in ("chunk_paths", "chunk_sizes", "chunk_backends")}
    # Add data integrity check for chunked videos
    if video.get("is_chunked"):
        chunk_paths = video.get("chunk_paths", {})
        chunk_backends = video.get("chunk_backends", {})
        total = video.get("total_chunks", len(chunk_paths))
        available = 0
        for i in range(total):
            path = chunk_paths.get(str(i))
            if not path:
                continue
            backend = chunk_backends.get(str(i), "storage")
            if backend == "filesystem" and not os.path.exists(path):
                continue
            available += 1
        result["chunks_available"] = available
        result["chunks_total"] = total
        result["data_integrity"] = (
            "full" if available == total else ("partial" if available > 0 else "unavailable")
        )

    return result


@router.get("/videos/{video_id}/processing-status")
async def get_processing_status(video_id: str, current_user: dict = Depends(get_current_user)):
    """Polling endpoint for frontend to check processing progress."""
    video = await db.videos.find_one(
        {"id": video_id, "user_id": current_user["id"]},
        {"_id": 0, "chunk_paths": 0, "chunk_sizes": 0, "chunk_backends": 0},
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    completed_types = []
    failed_types = []
    analyses = await db.analyses.find(
        {"video_id": video_id, "user_id": current_user["id"]},
        {"_id": 0, "analysis_type": 1, "status": 1},
    ).to_list(10)
    for a in analyses:
        if a.get("status") == "completed":
            completed_types.append(a["analysis_type"])
        elif a.get("status") == "failed":
            failed_types.append(a["analysis_type"])

    return {
        "processing_status": video.get("processing_status", "none"),
        "processing_progress": video.get("processing_progress", 0),
        "processing_current": video.get("processing_current"),
        "processing_error": video.get("processing_error"),
        "processing_completed_at": video.get("processing_completed_at"),
        "completed_types": completed_types,
        "failed_types": failed_types,
        "server_boot_id": _get_server_boot_id(),
    }
