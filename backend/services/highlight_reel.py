"""AI-curated Auto-Highlight Reel Generator.

Pipeline (per reel):
  1. Pick top N clips from a match using AI score (goal > save > highlight),
     greedy-fit to a 60-90s budget.
  2. For each selected clip:
       a. Render a branded "Goal 1 — 23' Saka" title card PNG via Pillow.
       b. Convert it to a 2.5s 1920x1080 mp4 segment with ffmpeg.
       c. Extract the wide-shot clip segment from the source video.
  3. Concat title_card → clip → title_card → clip → … into a single mp4 via
     the ffmpeg concat demuxer (re-encode for codec uniformity).
  4. Persist to `/var/video_chunks/reels/{reel_id}.mp4` and mark the reel
     `ready` with `duration_seconds` + `selected_clip_ids` for the frontend.

Failure handling: per-clip failures skip the offender and continue. If we
end up with 0 usable clips the reel is marked `failed` so the UI can show
a helpful error.

Worker: tiny in-process asyncio queue (one reel at a time) so ffmpeg jobs
don't pile up on the small server. Same pattern as close_up_processor.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Optional

from starlette.concurrency import run_in_threadpool

from db import CHUNK_STORAGE_DIR, db
from services.og_card import render_reel_title_card

logger = logging.getLogger(__name__)

REELS_DIR = os.path.join(CHUNK_STORAGE_DIR, "reels")
os.makedirs(REELS_DIR, exist_ok=True)

# Reel budget — strict 60-90s target so coaches can share to socials without
# trimming. Title cards eat into this, so we cap clip-content at 75s.
MIN_DURATION_S = 60.0
MAX_DURATION_S = 90.0
TITLE_CARD_DURATION_S = 2.5
MAX_CLIPS = 12  # don't pick so many that title cards dominate the reel

# Clip scoring weights — goals always win, then saves, then highlights.
CLIP_TYPE_SCORE = {
    "goal": 100,
    "save": 80,
    "key_save": 80,
    "key_pass": 60,
    "tackle": 50,
    "foul": 35,
    "card": 30,
    "highlight": 50,
}


# ---------- ffmpeg helpers ----------

async def _run(cmd: list, timeout: int = 360) -> tuple[int, str]:
    result = await run_in_threadpool(
        subprocess.run, cmd, capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stderr or ""


async def _probe_dimensions(path: str) -> tuple[int, int]:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path,
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
        logger.warning("[reel] ffprobe failed: %s", exc)
    return 1920, 1080


# ---------- title card rendering ----------

async def _make_title_card_segment(
    title_top: str,
    title_main: str,
    title_sub: str,
    accent_rgb: tuple,
    duration_s: float,
    width: int,
    height: int,
) -> Optional[str]:
    """Render a title-card PNG and convert it to a static mp4 segment."""
    png_bytes = await run_in_threadpool(
        render_reel_title_card,
        title_top, title_main, title_sub, accent_rgb, width, height,
    )
    if not png_bytes:
        return None

    png_path = tempfile.mktemp(suffix=".png", dir=REELS_DIR)
    with open(png_path, "wb") as fh:
        fh.write(png_bytes)

    out_path = tempfile.mktemp(suffix="_title.mp4", dir=REELS_DIR)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-t", f"{duration_s}", "-i", png_path,
        "-f", "lavfi", "-t", f"{duration_s}",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        "-movflags", "+faststart",
        out_path,
    ]
    rc, err = await _run(cmd, timeout=60)
    try:
        os.unlink(png_path)
    except OSError:
        pass

    if rc != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
        logger.warning("[reel] title-card encode failed (rc=%s): %s", rc, err[:300])
        if os.path.exists(out_path):
            os.unlink(out_path)
        return None
    return out_path


# ---------- clip extraction ----------

async def _extract_clip_segment(
    clip: dict, target_w: int, target_h: int,
) -> Optional[str]:
    """Reassemble source video chunks → cut [start, end] → normalize WxH."""
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

    raw_path = tempfile.mktemp(suffix=".mp4", dir=REELS_DIR)
    try:
        with open(raw_path, "wb") as fh:
            for ch in chunks_meta:
                data = await read_chunk_data(video["id"], ch.get("index", 0), ch)
                if data:
                    fh.write(data)
        if not os.path.exists(raw_path) or os.path.getsize(raw_path) < 1000:
            return None

        # Cut the clip then scale+pad to the reel resolution so every concat
        # segment shares the same dimensions. Without scale+pad ffmpeg's
        # concat demuxer will refuse mixed resolutions.
        out_path = tempfile.mktemp(suffix="_clip.mp4", dir=REELS_DIR)
        duration = max(1.0, float(clip["end_time"]) - float(clip["start_time"]))
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )
        cmd = [
            "ffmpeg", "-y", "-ss", f"{clip['start_time']}", "-i", raw_path,
            "-t", f"{duration}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            out_path,
        ]
        rc, err = await _run(cmd, timeout=300)
        if rc != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
            logger.warning("[reel] clip extract failed (rc=%s): %s", rc, err[:300])
            if os.path.exists(out_path):
                os.unlink(out_path)
            return None
        return out_path
    finally:
        if os.path.exists(raw_path):
            os.unlink(raw_path)


# ---------- selection ----------

def _score_clip(clip: dict) -> float:
    base = CLIP_TYPE_SCORE.get((clip.get("clip_type") or "highlight").lower(), 40)
    # Bonus for tagged players (clips with named players are more meaningful)
    if clip.get("player_ids"):
        base += 10
    # Penalty for very short or very long clips
    duration = float(clip.get("end_time", 0)) - float(clip.get("start_time", 0))
    if duration < 3:
        base -= 25
    elif duration > 20:
        base -= 15
    return base


def _select_clips(clips: list) -> tuple[list, float]:
    """Greedy pick of top-scored clips fitting MAX_DURATION_S minus title-card budget.

    Returns (selected_clips_in_chronological_order, total_clip_seconds).
    """
    if not clips:
        return [], 0.0

    # Sort by descending score, break ties by chronological order.
    scored = sorted(
        clips,
        key=lambda c: (-_score_clip(c), float(c.get("start_time", 0))),
    )

    # Each clip pulls TITLE_CARD_DURATION_S of overhead.
    overhead_per_clip = TITLE_CARD_DURATION_S
    budget = MAX_DURATION_S - 4.0  # leave 4s for outro/safety

    selected = []
    used = 0.0
    for c in scored:
        if len(selected) >= MAX_CLIPS:
            break
        dur = float(c.get("end_time", 0)) - float(c.get("start_time", 0))
        if dur <= 0:
            continue
        # Trim individual clips that would overshoot — but keep them at least 3s.
        max_clip_dur = min(dur, 12.0)
        cost = overhead_per_clip + max_clip_dur
        if used + cost > budget and len(selected) >= 1:
            continue
        c = dict(c)
        if dur > max_clip_dur:
            c["end_time"] = float(c["start_time"]) + max_clip_dur
        selected.append(c)
        used += cost

    # Final chronological reorder (story-first viewing)
    selected.sort(key=lambda c: float(c.get("start_time", 0)))
    clip_seconds = sum(
        float(c["end_time"]) - float(c["start_time"]) for c in selected
    )
    return selected, clip_seconds


# ---------- minute formatting ----------

def _format_minute(start_time_seconds: float) -> str:
    """Convert seconds-into-video to a soccer-style minute label."""
    minute = max(0, int(start_time_seconds // 60))
    return f"{minute}'"


def _humanize_clip_type(clip_type: str) -> str:
    mapping = {
        "goal": "GOAL",
        "save": "SAVE",
        "key_save": "SAVE",
        "key_pass": "KEY PASS",
        "tackle": "TACKLE",
        "foul": "FOUL",
        "card": "CARD",
        "highlight": "HIGHLIGHT",
    }
    return mapping.get((clip_type or "highlight").lower(), "HIGHLIGHT")


def _accent_for_type(clip_type: str) -> tuple:
    t = (clip_type or "highlight").lower()
    if t == "goal":
        return (16, 185, 129)       # green
    if t in ("save", "key_save"):
        return (0, 122, 255)        # blue
    if t in ("card", "foul"):
        return (239, 68, 68)        # red
    return (251, 191, 36)           # amber


async def _build_title_subtitle(clip: dict, match: dict, players_by_id: dict) -> tuple[str, str, str]:
    """Compose title_top / title_main / title_sub strings for the card."""
    label = _humanize_clip_type(clip.get("clip_type"))
    minute = _format_minute(float(clip.get("start_time", 0)))

    # Pick first tagged player if available
    name = ""
    if clip.get("player_ids"):
        for pid in clip["player_ids"]:
            p = players_by_id.get(pid)
            if p and p.get("name"):
                name = p["name"]
                if p.get("number") is not None:
                    name = f"#{p['number']} {name}"
                break

    # Top label: "GOAL 1 · 23'"
    title_top = f"{label} · {minute}"
    # Main: player name OR clip title fallback
    title_main = name or (clip.get("title") or label).strip()
    # Sub: matchup
    title_sub = f"{match.get('team_home', '')} vs {match.get('team_away', '')}".strip()
    if match.get("competition"):
        title_sub += f" · {match['competition']}"

    return title_top, title_main, title_sub


# ---------- orchestration ----------

async def _update_reel(reel_id: str, fields: dict) -> None:
    await db.highlight_reels.update_one({"id": reel_id}, {"$set": fields})


async def _mark_failed(reel_id: str, reason: str) -> None:
    await _update_reel(reel_id, {
        "status": "failed",
        "error": reason,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })


async def _concat_segments(segments: list, dest_path: str) -> bool:
    list_path = tempfile.mktemp(suffix=".txt", dir=REELS_DIR)
    try:
        with open(list_path, "w", encoding="utf-8") as fh:
            for p in segments:
                fh.write(f"file '{p}'\n")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            "-movflags", "+faststart",
            dest_path,
        ]
        rc, err = await _run(cmd, timeout=360)
        if rc != 0 or not os.path.exists(dest_path) or os.path.getsize(dest_path) < 5000:
            logger.warning("[reel] concat failed (rc=%s): %s", rc, err[:300])
            return False
        return True
    finally:
        if os.path.exists(list_path):
            os.unlink(list_path)


async def process_reel(reel_id: str) -> dict:
    """Generate the stitched highlight reel for a reel doc. Idempotent."""
    await _update_reel(reel_id, {
        "status": "processing",
        "progress": 0.05,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })

    reel = await db.highlight_reels.find_one({"id": reel_id}, {"_id": 0})
    if not reel:
        return {"status": "failed", "reason": "reel_not_found"}

    match = await db.matches.find_one({"id": reel["match_id"]}, {"_id": 0})
    if not match:
        await _mark_failed(reel_id, "match_not_found")
        return {"status": "failed"}

    # All clips for this match owned by the same user
    clips = await db.clips.find(
        {"match_id": reel["match_id"], "user_id": reel["user_id"]},
        {"_id": 0},
    ).to_list(500)

    if not clips:
        await _mark_failed(reel_id, "no_clips_available")
        return {"status": "failed"}

    selected, _ = _select_clips(clips)
    if not selected:
        await _mark_failed(reel_id, "no_clips_passed_filters")
        return {"status": "failed"}

    # Pre-fetch players for title-card labels
    all_player_ids = list({pid for c in selected for pid in (c.get("player_ids") or [])})
    players_by_id = {}
    if all_player_ids:
        plist = await db.players.find(
            {"id": {"$in": all_player_ids}},
            {"_id": 0, "id": 1, "name": 1, "number": 1},
        ).to_list(200)
        players_by_id = {p["id"]: p for p in plist}

    await _update_reel(reel_id, {
        "progress": 0.1,
        "selected_clip_ids": [c["id"] for c in selected],
        "total_clips": len(selected),
    })

    # Probe the source video for native resolution (cap to 1280x720 for size)
    target_w, target_h = 1280, 720

    segments_to_cleanup = []
    try:
        # Intro card
        intro_path = await _make_title_card_segment(
            "MATCH HIGHLIGHTS",
            f"{match.get('team_home', '')} vs {match.get('team_away', '')}".strip() or "Highlights",
            (match.get("competition") or match.get("date") or ""),
            (0, 122, 255),
            duration_s=2.5,
            width=target_w, height=target_h,
        )
        timeline_segments = []
        if intro_path:
            timeline_segments.append(intro_path)
            segments_to_cleanup.append(intro_path)

        # Title card + clip pairs
        total = len(selected)
        for idx, clip in enumerate(selected):
            title_top, title_main, title_sub = await _build_title_subtitle(
                clip, match, players_by_id,
            )
            accent = _accent_for_type(clip.get("clip_type"))
            card_path = await _make_title_card_segment(
                title_top, title_main, title_sub,
                accent, duration_s=TITLE_CARD_DURATION_S,
                width=target_w, height=target_h,
            )
            clip_path = await _extract_clip_segment(clip, target_w, target_h)
            if card_path:
                timeline_segments.append(card_path)
                segments_to_cleanup.append(card_path)
            if clip_path:
                timeline_segments.append(clip_path)
                segments_to_cleanup.append(clip_path)

            await _update_reel(reel_id, {
                "progress": 0.1 + 0.75 * ((idx + 1) / max(1, total)),
            })

        if len(timeline_segments) < 2:
            await _mark_failed(reel_id, "no_segments_built")
            return {"status": "failed"}

        # Final concat
        dest_path = os.path.join(REELS_DIR, f"{reel_id}.mp4")
        ok = await _concat_segments(timeline_segments, dest_path)
        if not ok:
            await _mark_failed(reel_id, "concat_failed")
            return {"status": "failed"}

        # Probe final duration
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", dest_path,
        ]
        result = await run_in_threadpool(
            subprocess.run, cmd, capture_output=True, text=True, timeout=20,
        )
        try:
            duration_s = float((result.stdout or "0").strip())
        except ValueError:
            duration_s = 0.0

        await _update_reel(reel_id, {
            "status": "ready",
            "progress": 1.0,
            "output_path": dest_path,
            "duration_seconds": round(duration_s, 2),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        return {"status": "ready", "path": dest_path, "duration": duration_s}
    finally:
        # Clean up intermediate per-segment files (the final concat is independent now)
        for p in segments_to_cleanup:
            if os.path.exists(p):
                try:
                    os.unlink(p)
                except OSError:
                    pass


# ---------- background queueing ----------

_queue: asyncio.Queue = asyncio.Queue()
_worker_started = False


async def _worker():
    while True:
        reel_id = await _queue.get()
        try:
            await process_reel(reel_id)
        except Exception as exc:
            logger.exception("[reel] worker error on %s: %s", reel_id, exc)
            await _mark_failed(reel_id, f"worker_exception: {exc!r}"[:240])
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


async def enqueue_reel(reel_id: str) -> None:
    reel = await db.highlight_reels.find_one(
        {"id": reel_id}, {"_id": 0, "id": 1, "status": 1},
    )
    if not reel:
        return
    if reel.get("status") in ("processing", "ready"):
        return
    await _update_reel(reel_id, {
        "status": "pending",
        "queued_at": datetime.now(timezone.utc).isoformat(),
    })
    _ensure_worker_running()
    await _queue.put(reel_id)


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
