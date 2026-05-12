"""Clip management with sharing and download"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from typing import Optional, List
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import uuid
import os
import subprocess
import tempfile
from db import db, CHUNK_STORAGE_DIR, CHUNK_SIZE
from models import Clip, ClipZipRequest
from routes.auth import get_current_user
from services.storage import read_chunk_data, get_object_sync

router = APIRouter()


class ClipCreate(BaseModel):
    video_id: str
    title: str
    start_time: float
    end_time: float
    clip_type: str = "highlight"
    description: Optional[str] = None
    player_ids: List[str] = []
    match_id: Optional[str] = None


@router.post("/clips")
async def create_clip(input: ClipCreate, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one({"id": input.video_id, "user_id": current_user["id"]}, {"_id": 0, "match_id": 1})
    clip = Clip(
        user_id=current_user["id"],
        video_id=input.video_id,
        match_id=input.match_id or (video.get("match_id") if video else None),
        title=input.title,
        start_time=input.start_time,
        end_time=input.end_time,
        clip_type=input.clip_type,
        description=input.description,
        player_ids=input.player_ids
    )
    await db.clips.insert_one(clip.model_dump())
    return clip.model_dump()


@router.get("/clips/video/{video_id}")
async def get_video_clips(video_id: str, current_user: dict = Depends(get_current_user)):
    clips = await db.clips.find({"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(200)
    return clips


@router.delete("/clips/{clip_id}")
async def delete_clip(clip_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.clips.delete_one({"id": clip_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Clip not found")
    return {"status": "deleted"}


# ===== Clip Sharing =====

@router.post("/clips/{clip_id}/share")
async def toggle_clip_share(clip_id: str, current_user: dict = Depends(get_current_user)):
    """Generate or revoke a share token for a clip"""
    clip = await db.clips.find_one({"id": clip_id, "user_id": current_user["id"]}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if clip.get("share_token"):
        await db.clips.update_one({"id": clip_id}, {"$set": {"share_token": None}})
        return {"status": "unshared", "share_token": None}
    else:
        token = str(uuid.uuid4())[:12]
        await db.clips.update_one({"id": clip_id}, {"$set": {"share_token": token}})
        return {"status": "shared", "share_token": token}


@router.get("/shared/clip/{share_token}")
async def get_shared_clip(share_token: str):
    """Public: view a shared clip's metadata"""
    clip = await db.clips.find_one({"share_token": share_token}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Shared clip not found or link expired")

    video = await db.videos.find_one({"id": clip["video_id"]}, {"_id": 0, "id": 1, "original_filename": 1})
    match = await db.matches.find_one({"id": clip.get("match_id")}, {"_id": 0, "team_home": 1, "team_away": 1, "date": 1, "competition": 1})
    owner = await db.users.find_one({"id": clip["user_id"]}, {"_id": 0, "name": 1})

    # Get tagged players
    players = []
    if clip.get("player_ids"):
        players = await db.players.find({"id": {"$in": clip["player_ids"]}}, {"_id": 0, "id": 1, "name": 1, "number": 1, "profile_pic_url": 1}).to_list(20)

    # NOTE: push-on-view hook lives in server.py's get_shared_clip_detail (which is the
    # actively-mounted handler). This routes/clips.py file is currently NOT mounted via
    # include_router; keeping it as the canonical home for future clip-route migration.

    return {
        "clip": clip,
        "match": match,
        "video_id": video["id"] if video else None,
        "owner": owner.get("name") if owner else "Coach",
        "players": players
    }


@router.get("/shared/clip/{share_token}/video")
async def stream_shared_clip_video(share_token: str):
    """Public: stream the actual video segment for a shared clip"""
    clip = await db.clips.find_one({"share_token": share_token}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Invalid share link")

    video = await db.videos.find_one({"id": clip["video_id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Extract the clip segment
    out_path = await _extract_clip_segment(video, clip)
    if not out_path:
        raise HTTPException(status_code=500, detail="Failed to extract clip")

    async def stream_and_cleanup():
        try:
            with open(out_path, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

    return StreamingResponse(stream_and_cleanup(), media_type="video/mp4")


# ===== Clip Download =====

@router.get("/clips/{clip_id}/extract")
async def extract_clip_video(clip_id: str, current_user: dict = Depends(get_current_user)):
    """Extract actual video segment for a clip"""
    clip = await db.clips.find_one({"id": clip_id, "user_id": current_user["id"]}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    video = await db.videos.find_one({"id": clip["video_id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    out_path = await _extract_clip_segment(video, clip)
    if not out_path:
        raise HTTPException(status_code=500, detail="Failed to extract clip")

    safe_title = "".join(c for c in clip["title"] if c.isalnum() or c in " -_").strip()[:50] or "clip"

    async def stream_and_cleanup():
        try:
            with open(out_path, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

    return StreamingResponse(
        stream_and_cleanup(), media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.mp4"'}
    )


def _safe_clip_filename(title: str) -> str:
    """Sanitize a clip title to a safe MP4 filename (40 chars max, alnum/space/dash/underscore only)."""
    cleaned = "".join(c for c in title if c.isalnum() or c in " -_").strip()[:40]
    return f"{cleaned or 'clip'}.mp4"


async def _extract_clips_for_zip(clips: list) -> list:
    """Group clips by source video, assemble each raw video once, then extract
    every clip from it before discarding. Returns [(file_path, filename), ...].

    The grouping is critical for perf — assembling a 5GB raw video takes ~30s,
    so doing it once per video instead of once per clip saves minutes when a
    coach exports a highlight reel of 10 clips from 2 matches."""
    video_clips: dict = {}
    for clip in clips:
        video_clips.setdefault(clip["video_id"], []).append(clip)

    extracted = []
    for video_id, clip_list in video_clips.items():
        video = await db.videos.find_one({"id": video_id, "is_deleted": False}, {"_id": 0})
        if not video:
            continue
        raw_path = await _assemble_video(video)
        try:
            for clip in clip_list:
                out_path = await _ffmpeg_extract(raw_path, clip["start_time"], clip["end_time"])
                if out_path:
                    extracted.append((out_path, _safe_clip_filename(clip["title"])))
        finally:
            if os.path.exists(raw_path):
                os.unlink(raw_path)
    return extracted


def _write_zip(zip_path: str, files: list) -> None:
    """Bundle (path, filename) pairs into a ZIP at zip_path, then delete sources."""
    import zipfile
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
        for file_path, filename in files:
            zf.write(file_path, filename)
    for fp, _ in files:
        if os.path.exists(fp):
            os.unlink(fp)


def _stream_then_delete(path: str):
    """Async generator that streams `path` 1MB at a time, then deletes it.
    Wrapped here to keep the route handler focused on flow, not IO."""
    async def gen():
        try:
            with open(path, 'rb') as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
        finally:
            if os.path.exists(path):
                os.unlink(path)
    return gen()


def _cleanup_paths(paths: list) -> None:
    """Best-effort cleanup — swallow errors so we don't lose the original exception."""
    for fp in paths:
        if os.path.exists(fp):
            try:
                os.unlink(fp)
            except OSError:
                pass


@router.post("/clips/download-zip")
async def download_clips_zip(input: ClipZipRequest, current_user: dict = Depends(get_current_user)):
    """Extract multiple clips and return as ZIP.

    iter56 refactor: was 76 lines, complexity 30, 5 nesting levels. Split into
    4 focused helpers above (`_extract_clips_for_zip`, `_write_zip`,
    `_stream_then_delete`, `_cleanup_paths`). This handler is now a flat
    orchestrator that reads top-to-bottom.
    """
    if not input.clip_ids:
        raise HTTPException(status_code=400, detail="No clip IDs provided")
    if len(input.clip_ids) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 clips per download")

    clips = await db.clips.find(
        {"id": {"$in": input.clip_ids}, "user_id": current_user["id"]},
        {"_id": 0},
    ).to_list(20)
    if not clips:
        raise HTTPException(status_code=404, detail="No clips found")

    zip_path = tempfile.mktemp(suffix=".zip", dir=CHUNK_STORAGE_DIR)
    extracted_files = []
    try:
        extracted_files = await _extract_clips_for_zip(clips)
        if not extracted_files:
            raise HTTPException(status_code=500, detail="Failed to extract any clips")
        _write_zip(zip_path, extracted_files)
        return StreamingResponse(
            _stream_then_delete(zip_path),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="highlights.zip"'},
        )
    except HTTPException:
        _cleanup_paths([fp for fp, _ in extracted_files] + [zip_path])
        raise
    except Exception as e:
        _cleanup_paths([fp for fp, _ in extracted_files] + [zip_path])
        raise HTTPException(status_code=500, detail=f"ZIP creation failed: {str(e)[:200]}")


# ===== Internal helpers =====

async def _assemble_video(video: dict) -> str:
    """Assemble all chunks into a single file on disk"""
    raw_path = tempfile.mktemp(suffix=".mp4", dir=CHUNK_STORAGE_DIR)
    if video.get("is_chunked"):
        chunk_paths = video.get("chunk_paths", {})
        chunk_backends = video.get("chunk_backends", {})
        total_chunks = video.get("total_chunks", len(chunk_paths))
        chunk_size = video.get("chunk_size", CHUNK_SIZE)
        with open(raw_path, 'wb') as f:
            for i in range(total_chunks):
                path = chunk_paths.get(str(i))
                if not path:
                    f.write(b'\x00' * chunk_size)
                    continue
                backend = chunk_backends.get(str(i), "storage")
                if backend == "filesystem" and not os.path.exists(path):
                    f.write(b'\x00' * chunk_size)
                    continue
                try:
                    data = await read_chunk_data(video["id"], i, {"backend": backend, "path": path})
                    f.write(data)
                    del data
                except Exception:
                    f.write(b'\x00' * chunk_size)
    else:
        data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
        with open(raw_path, 'wb') as f:
            f.write(data)
        del data
    return raw_path


async def _ffmpeg_extract(raw_path: str, start_time: float, end_time: float) -> str:
    """Extract a segment from a video file"""
    out_path = tempfile.mktemp(suffix=".mp4", dir=CHUNK_STORAGE_DIR)
    duration = end_time - start_time
    cmd = [
        "ffmpeg", "-y", "-ss", str(start_time), "-i", raw_path,
        "-t", str(duration), "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out_path
    ]
    result = await run_in_threadpool(subprocess.run, cmd, capture_output=True, text=True, timeout=300)
    if result.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        return out_path
    if os.path.exists(out_path):
        os.unlink(out_path)
    return None


async def _extract_clip_segment(video: dict, clip: dict) -> str:
    """Full pipeline: assemble video + extract clip segment"""
    raw_path = await _assemble_video(video)
    try:
        out_path = await _ffmpeg_extract(raw_path, clip["start_time"], clip["end_time"])
        return out_path
    finally:
        if os.path.exists(raw_path):
            os.unlink(raw_path)
