"""Video read endpoints — access token, metadata, processing status.

Heavier endpoints (streaming with Range support, upload chunking, soft-delete,
reprocess, AI-generation) deliberately stay in server.py because they're tightly
coupled with the chunked-upload pipeline and the AI auto-processing background task.
"""
import os
import time
import jwt
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from db import db, JWT_SECRET
from runtime import SERVER_BOOT_ID
from routes.auth import get_current_user

router = APIRouter()


def _parse_iso(value):
    if not value:
        return None
    try:
        # Handle `Z` suffix + timezone-naive values
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


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
        "processing_started_at": video.get("processing_started_at"),
        "processing_completed_at": video.get("processing_completed_at"),
        "completed_types": completed_types,
        "failed_types": failed_types,
        "server_boot_id": SERVER_BOOT_ID,
    }


@router.get("/videos/processing-eta-stats")
async def get_processing_eta_stats(current_user: dict = Depends(get_current_user)):
    """Return the user's avg total processing duration for completed videos.

    Used by the client-side ETA estimator on MatchDetail. When progress < 10%
    the frontend falls back to this average; otherwise it extrapolates from
    the in-flight elapsed time.

    Returns:
      { avg_seconds: float|null, samples: int }
    """
    cursor = db.videos.find(
        {
            "user_id": current_user["id"],
            "processing_status": "completed",
            "processing_started_at": {"$ne": None},
            "processing_completed_at": {"$ne": None},
        },
        {"_id": 0, "processing_started_at": 1, "processing_completed_at": 1},
    ).sort("processing_completed_at", -1).limit(20)  # Last 20 completed — keeps avg responsive to recent infra

    durations = []
    async for v in cursor:
        started = _parse_iso(v.get("processing_started_at"))
        finished = _parse_iso(v.get("processing_completed_at"))
        if not started or not finished:
            continue
        delta = (finished - started).total_seconds()
        # Sanity-bound: discard < 10s (probably instant failure) or > 2h (probably stalled)
        if 10 <= delta <= 7200:
            durations.append(delta)

    if not durations:
        return {"avg_seconds": None, "samples": 0}
    return {
        "avg_seconds": round(sum(durations) / len(durations), 1),
        "samples": len(durations),
    }
