"""AI-powered close-up generator for goal & highlight clips.

Pipeline (per clip):
  1. Extract the wide-shot segment from the source video using ffmpeg.
  2. Send it to Gemini → JSON with bbox(x_pct,y_pct,w_pct,h_pct) +
     zoom_level(1.5/2.0/2.5) describing where the action is and how
     tightly to crop.
  3. Render the close-up segment with ffmpeg (`crop` + `scale` filters)
     using those coordinates — the close-up is the same length as the
     wide shot but visually zoomed to the action.
  4. Concat wide + close-up using ffmpeg's concat demuxer → a single
     stitched mp4 that plays the action twice: first wide, then tight.
  5. Persist the stitched mp4 in `/var/video_chunks/close_ups/` and
     update the clip doc with `close_up_path` + `close_up_status="ready"`.

`extract_clip_video` (in routes/clips.py) prefers the stitched file
when present — no UI changes required for playback.

Auto-trigger: any `clip_type == "goal"` clip is queued automatically as
soon as it's created. Manual trigger: POST /api/clips/{id}/generate-close-up
flips other clip types into the queue too.

Failure handling: if Gemini call fails or returns garbage JSON, we fall
back to a center crop (still a usable close-up) so the user always gets
SOMETHING. Persistent ffmpeg failures mark `close_up_status="failed"`
so the UI can offer a "retry" affordance.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Optional

from starlette.concurrency import run_in_threadpool

from db import CHUNK_STORAGE_DIR, db
from services.processing import _emergent_key

logger = logging.getLogger(__name__)

CLOSE_UP_DIR = os.path.join(CHUNK_STORAGE_DIR, "close_ups")
os.makedirs(CLOSE_UP_DIR, exist_ok=True)

ZOOM_PROMPT = (
    "You are analyzing a soccer video clip. Identify the bounding box of the "
    "MAIN ACTION (the ball + the player(s) most directly involved) and "
    "recommend an appropriate zoom level so a viewer can see the action up "
    "close.\n\n"
    "Respond with ONLY valid JSON (no markdown, no commentary), exactly:\n"
    "{\n"
    '  "x_pct": <number 0-100>,\n'
    '  "y_pct": <number 0-100>,\n'
    '  "w_pct": <number 10-100>,\n'
    '  "h_pct": <number 10-100>,\n'
    '  "zoom_level": <one of 1.5, 2.0, 2.5>,\n'
    '  "reasoning": "<one sentence>"\n'
    "}\n\n"
    "Coordinates are percentages of the full frame (0,0 = top-left). "
    "Use a TIGHTER box (smaller w/h, higher zoom_level=2.5) when the clip "
    "shows a finishing action like a shot or save. Use a WIDER box "
    "(larger w/h, zoom_level=1.5) for build-up play or counter-attacks "
    "with multiple players involved."
)


# ---------- ffmpeg helpers ----------

async def _run(cmd: list, timeout: int = 300) -> tuple[int, str]:
    """Run a subprocess, returning (returncode, stderr)."""
    result = await run_in_threadpool(
        subprocess.run, cmd, capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stderr or ""


async def _probe_dimensions(video_path: str) -> tuple[int, int]:
    """Return (width, height) via ffprobe. Falls back to 1920x1080."""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", video_path,
    ]
    try:
        result = await run_in_threadpool(
            subprocess.run, cmd, capture_output=True, text=True, timeout=20,
        )
        out = (result.stdout or "").strip()
        if "x" in out:
            w_str, h_str = out.split("x", 1)
            return int(w_str), int(h_str)
    except Exception as exc:
        logger.warning("[close-up] ffprobe failed: %s", exc)
    return 1920, 1080


def _compute_crop_box(
    width: int, height: int, bbox: dict, zoom: float,
) -> tuple[int, int, int, int]:
    """Compute the (x, y, w, h) ffmpeg crop box from the AI's bbox + zoom.

    The bbox is the *target focus*; we compute a crop window centered on the
    bbox center, sized by `width / zoom`. Clamps so we never request pixels
    outside the frame. Snaps even (libx264 requires multiples of 2).
    """
    cx_pct = bbox["x_pct"] + bbox["w_pct"] / 2
    cy_pct = bbox["y_pct"] + bbox["h_pct"] / 2
    cx = int(width * cx_pct / 100)
    cy = int(height * cy_pct / 100)

    crop_w = int(width / zoom) & ~1
    crop_h = int(height / zoom) & ~1
    crop_x = max(0, min(width - crop_w, cx - crop_w // 2)) & ~1
    crop_y = max(0, min(height - crop_h, cy - crop_h // 2)) & ~1
    return crop_x, crop_y, crop_w, crop_h


async def _render_close_up(
    wide_path: str, bbox: dict, zoom: float,
) -> Optional[str]:
    """Crop + scale the wide segment into a tight close-up."""
    width, height = await _probe_dimensions(wide_path)
    cx, cy, cw, ch = _compute_crop_box(width, height, bbox, zoom)

    out_path = tempfile.mktemp(suffix="_zoom.mp4", dir=CLOSE_UP_DIR)
    cmd = [
        "ffmpeg", "-y", "-i", wide_path,
        "-vf", f"crop={cw}:{ch}:{cx}:{cy},scale={width}:{height}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        out_path,
    ]
    rc, err = await _run(cmd, timeout=180)
    if rc != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        logger.warning("[close-up] render failed (rc=%s): %s", rc, err[:300])
        if os.path.exists(out_path):
            os.unlink(out_path)
        return None
    return out_path


async def _stitch(wide_path: str, close_path: str, dest_path: str) -> bool:
    """Concat wide + close-up into one mp4 via the concat demuxer.

    We use the concat demuxer (not the filter) because both segments share
    the same codec/params, which keeps the operation copy-fast.
    """
    list_path = tempfile.mktemp(suffix=".txt", dir=CLOSE_UP_DIR)
    try:
        with open(list_path, "w", encoding="utf-8") as fh:
            fh.write(f"file '{wide_path}'\n")
            fh.write(f"file '{close_path}'\n")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            dest_path,
        ]
        rc, err = await _run(cmd, timeout=180)
        if rc != 0 or not os.path.exists(dest_path) or os.path.getsize(dest_path) < 1000:
            logger.warning("[close-up] stitch failed (rc=%s): %s", rc, err[:300])
            return False
        return True
    finally:
        if os.path.exists(list_path):
            os.unlink(list_path)


# ---------- Gemini analysis ----------

def _center_fallback(zoom: float = 2.0) -> dict:
    """Default crop when AI is unavailable — center of frame."""
    return {
        "x_pct": 25.0, "y_pct": 25.0, "w_pct": 50.0, "h_pct": 50.0,
        "zoom_level": zoom, "reasoning": "Fell back to center crop.",
    }


def _parse_zoom_response(raw: str) -> dict:
    """Pull JSON out of Gemini's response. Tolerant of fenced markdown."""
    if not raw:
        return _center_fallback()
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\n", "", cleaned)
        cleaned = re.sub(r"\n```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if not m:
            return _center_fallback()
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return _center_fallback()

    # Validate / clamp
    def _clamp(v: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return (lo + hi) / 2

    zoom = _clamp(data.get("zoom_level", 2.0), 1.5, 2.5)
    # Snap zoom to one of the three documented levels for predictability.
    zoom = min((1.5, 2.0, 2.5), key=lambda z: abs(z - zoom))

    return {
        "x_pct": _clamp(data.get("x_pct", 25.0), 0, 90),
        "y_pct": _clamp(data.get("y_pct", 25.0), 0, 90),
        "w_pct": _clamp(data.get("w_pct", 50.0), 10, 100),
        "h_pct": _clamp(data.get("h_pct", 50.0), 10, 100),
        "zoom_level": zoom,
        "reasoning": str(data.get("reasoning", ""))[:240],
    }


async def _analyze_clip(clip_path: str) -> dict:
    """Send the wide segment to Gemini and parse the bbox+zoom JSON."""
    try:
        # Lazy-import to avoid heavy deps when emergentintegrations isn't installed
        from emergentintegrations.llm.chat import (  # type: ignore
            FileContentWithMimeType, LlmChat, UserMessage,
        )
        chat = LlmChat(
            api_key=_emergent_key(),
            session_id=f"close-up-{uuid.uuid4()}",
            system_message=(
                "You are a soccer video assistant. You will receive a short "
                "clip (typically 5-15 seconds). Locate the main action and "
                "respond with strict JSON only — no markdown, no commentary."
            ),
        ).with_model("gemini", "gemini-3.1-pro-preview")
        video_file = FileContentWithMimeType(file_path=clip_path, mime_type="video/mp4")
        msg = UserMessage(text=ZOOM_PROMPT, file_contents=[video_file])
        response = await chat.send_message(msg)
        return _parse_zoom_response(response)
    except Exception as exc:
        logger.warning("[close-up] Gemini analysis failed, using fallback: %s", exc)
        return _center_fallback()


# ---------- orchestration ----------

async def _extract_wide_segment(clip: dict) -> Optional[str]:
    """Extract the source segment for a clip.

    Inlines the same chunk-assembly + ffmpeg logic that lives in
    server.extract_clip_video so the worker can run completely
    independently from any HTTP endpoint.
    """
    from services.storage import read_chunk_data

    video = await db.videos.find_one(
        {"id": clip["video_id"], "is_deleted": False}, {"_id": 0},
    )
    if not video:
        return None

    chunks_meta = video.get("chunks") or []
    if not chunks_meta:
        return None
    chunks_meta = sorted(chunks_meta, key=lambda c: c.get("index", 0))

    # 1) Reassemble the source mp4 into a temp file
    raw_path = tempfile.mktemp(suffix=".mp4", dir=CLOSE_UP_DIR)
    try:
        with open(raw_path, "wb") as fh:
            for ch in chunks_meta:
                data = await read_chunk_data(video["id"], ch.get("index", 0), ch)
                if data:
                    fh.write(data)

        if not os.path.exists(raw_path) or os.path.getsize(raw_path) < 1000:
            return None

        # 2) Cut the [start_time, end_time] segment with ffmpeg
        out_path = tempfile.mktemp(suffix="_wide.mp4", dir=CLOSE_UP_DIR)
        duration = max(1.0, float(clip["end_time"]) - float(clip["start_time"]))
        cmd = [
            "ffmpeg", "-y", "-ss", f"{clip['start_time']}", "-i", raw_path,
            "-t", f"{duration}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            out_path,
        ]
        rc, err = await _run(cmd, timeout=240)
        if rc != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
            logger.warning("[close-up] wide-segment extract failed (rc=%s): %s", rc, err[:300])
            if os.path.exists(out_path):
                os.unlink(out_path)
            return None
        return out_path
    finally:
        if os.path.exists(raw_path):
            os.unlink(raw_path)


async def process_clip_close_up(clip_id: str) -> dict:
    """Generate the stitched close-up version of a clip. Idempotent.

    Returns `{status: "ready"|"failed", reason?: str, path?: str}`.
    """
    await db.clips.update_one(
        {"id": clip_id},
        {"$set": {
            "close_up_status": "processing",
            "close_up_started_at": datetime.now(timezone.utc).isoformat(),
        }},
    )

    clip = await db.clips.find_one({"id": clip_id}, {"_id": 0})
    if not clip:
        return {"status": "failed", "reason": "clip_not_found"}

    wide_path = await _extract_wide_segment(clip)
    if not wide_path:
        await _mark_failed(clip_id, "extraction_failed")
        return {"status": "failed", "reason": "extraction_failed"}

    try:
        bbox = await _analyze_clip(wide_path)
        close_path = await _render_close_up(wide_path, bbox, bbox["zoom_level"])
        if not close_path:
            await _mark_failed(clip_id, "render_failed")
            return {"status": "failed", "reason": "render_failed"}

        try:
            dest_path = os.path.join(CLOSE_UP_DIR, f"{clip_id}.mp4")
            ok = await _stitch(wide_path, close_path, dest_path)
            if not ok:
                await _mark_failed(clip_id, "stitch_failed")
                return {"status": "failed", "reason": "stitch_failed"}

            await db.clips.update_one(
                {"id": clip_id},
                {"$set": {
                    "close_up_status": "ready",
                    "close_up_path": dest_path,
                    "close_up_bbox": bbox,
                    "close_up_completed_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            return {"status": "ready", "path": dest_path}
        finally:
            if os.path.exists(close_path):
                os.unlink(close_path)
    finally:
        if os.path.exists(wide_path):
            os.unlink(wide_path)


async def _mark_failed(clip_id: str, reason: str) -> None:
    await db.clips.update_one(
        {"id": clip_id},
        {"$set": {
            "close_up_status": "failed",
            "close_up_error": reason,
            "close_up_completed_at": datetime.now(timezone.utc).isoformat(),
        }},
    )


# ---------- background queueing ----------

# A tiny in-process queue. We don't want a heavy job runner for this.
# At most one close-up renders at a time so ffmpeg + Gemini calls don't
# pile up on the small server.
_queue: asyncio.Queue = asyncio.Queue()
_worker_started = False


async def _worker():
    while True:
        clip_id = await _queue.get()
        try:
            await process_clip_close_up(clip_id)
        except Exception as exc:
            logger.exception("[close-up] worker error on %s: %s", clip_id, exc)
            await _mark_failed(clip_id, f"worker_exception: {exc!r}"[:240])
        finally:
            _queue.task_done()


def _ensure_worker_running():
    global _worker_started
    if _worker_started:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_worker())
    _worker_started = True


async def enqueue_close_up(clip_id: str) -> None:
    """Mark the clip pending and add to the queue. Skips if already queued/done."""
    clip = await db.clips.find_one(
        {"id": clip_id}, {"_id": 0, "id": 1, "close_up_status": 1},
    )
    if not clip:
        return
    if clip.get("close_up_status") in ("processing", "ready", "pending"):
        return

    await db.clips.update_one(
        {"id": clip_id},
        {"$set": {
            "close_up_status": "pending",
            "close_up_queued_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    _ensure_worker_running()
    await _queue.put(clip_id)


def is_ffmpeg_available() -> bool:
    """Useful for tests / startup checks."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
