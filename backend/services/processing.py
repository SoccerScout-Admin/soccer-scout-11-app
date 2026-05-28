"""AI processing pipeline helpers.

Contains the pure helpers used by auto-processing (prompt construction, marker
parsing, single-analysis runs) AND the orchestrator (`run_auto_processing`)
plus FFmpeg-based video sample preparation (`prepare_video_sample`,
`prepare_video_segments_720p`).

`run_auto_processing` is invoked as a background task after upload and on
startup auto-resume. It takes an `auto_create_clips_callback` to remain
decoupled from the clip-creation helper that still lives in server.py.
"""
import logging
import json as _json
import uuid
import os
import tempfile
import subprocess
import time
from datetime import datetime, timezone
from starlette.concurrency import run_in_threadpool
from db import db
from services.storage import read_chunk_data, get_object_sync
from services.processing_events import log_event as _log_event

logger = logging.getLogger(__name__)


def _emergent_key() -> str:
    """Read EMERGENT_LLM_KEY at call time so key rotation doesn't require a restart."""
    return os.environ.get("EMERGENT_LLM_KEY", "")


def build_roster_context(roster: list) -> str:
    """Build the roster context block injected into AI prompts."""
    if not roster:
        return ""
    roster_lines = []
    for p in roster:
        line = f"#{p.get('number', '?')} {p['name']}"
        if p.get("position"):
            line += f" ({p['position']})"
        if p.get("team"):
            line += f" - {p['team']}"
        roster_lines.append(line)
    return (
        "\n\n**Known Players on the Roster:**\n"
        + "\n".join(roster_lines)
        + "\n\nReference these players by name and number in your analysis when you can identify them."
    )


def build_analysis_prompts(match: dict, roster_context: str, segment_preamble: str) -> dict:
    """Build the AI prompt dictionary for each analysis type."""
    return {
        "tactical": (
            f"Analyze this soccer match video between {match['team_home']} and {match['team_away']}. "
            "Provide detailed tactical analysis covering:\n\n"
            "1. **Formations** - What formations are each team using? Any formation changes during the match?\n"
            "2. **Pressing Patterns** - How do teams press? High press, mid-block, or low block?\n"
            "3. **Build-up Play** - How do teams build from the back? Through the middle or wide?\n"
            "4. **Defensive Organization** - Shape, line height, compactness\n"
            "5. **Key Tactical Moments** - Pivotal tactical decisions that influenced the game\n"
            f"6. **Recommendations** - Tactical improvements for both teams{roster_context}"
        ),
        "player_performance": (
            f"Analyze individual player performances in this soccer match between {match['team_home']} and {match['team_away']}.\n\n"
            "**IDENTIFY PLAYERS BY THEIR JERSEY NUMBER FIRST.** Throughout the match you will see jersey numbers — "
            "when you reference a player, ALWAYS open with their number (e.g., '#7 plays in the right wing role...'). "
            "If the roster below maps that number to a name, prefer the name + number (e.g., '#7 Marcus Lopez').\n\n"
            "For each notable player provide:\n\n"
            "1. **Standout Performers** - Who were the best players (by number/name) and why?\n"
            "2. **Key Contributions** - Goals, assists, key passes, tackles — tie each to a specific number when possible\n"
            "3. **Work Rate & Positioning** - Movement, runs, defensive contribution\n"
            "4. **Decision Making** - Quality of decisions in key moments\n"
            "5. **Areas for Improvement** - What each key player could do better\n"
            "6. **Player Ratings** - Rate key players (by number/name) out of 10 with justification\n\n"
            f"If you cannot make out a jersey number clearly, describe the player by position + appearance "
            f"(e.g., 'the holding midfielder in the dark kit') rather than guessing.{roster_context}"
        ),
        "highlights": (
            f"Identify and describe ALL key moments and highlights from this soccer match between {match['team_home']} and {match['team_away']}. "
            "Include:\n\n"
            "1. **Goals & Assists** - Describe each goal in detail with timestamps if visible\n"
            "2. **Near Misses** - Close chances that didn't result in goals\n"
            "3. **Outstanding Saves** - Goalkeeper heroics\n"
            "4. **Tactical Shifts** - Moments where the game's momentum changed\n"
            "5. **Key Fouls & Cards** - Significant disciplinary moments\n"
            "6. **Game-Changing Plays** - Moments that altered the match outcome\n\n"
            f"For each moment, indicate the approximate time if visible and rate its significance (1-5 stars).{roster_context}"
        ),
        "timeline_markers": (
            f"You are watching a soccer match between {match['team_home']} (home) and {match['team_away']} (away).\n\n"
            f"{segment_preamble}"
            "**YOUR JOB:** Identify EVERY key event with precise match timestamps (seconds from match start, NOT from segment start).\n\n"
            "**GOAL DETECTION — CRITICAL.** Goals are the most important events; do NOT miss them. "
            "Cues that indicate a goal was just scored:\n"
            "  • Ball clearly crosses the goal line into the net\n"
            "  • Net visibly bulges from impact\n"
            "  • Players celebrate (running, jumping, arms raised, group hug)\n"
            "  • The defending goalkeeper retrieves the ball from inside the net\n"
            "  • Play restarts from the CENTER CIRCLE (kickoff after goal)\n"
            "  • A scoreboard overlay shows an updated score\n"
            "If you see ANY of these cues, log a `goal` event with importance 5. "
            "When in doubt between `shot` and `goal`, log BOTH events (one as `shot` for the attempt, one as `goal` for the score if the ball went in). "
            "**If you see celebrations or a center-circle kickoff but the actual ball-cross moment is not in your sampled footage, STILL log a `goal` event** "
            "— estimate the timestamp from when the celebration started.\n\n"
            "**PLAYER IDENTIFICATION.** For each event, attempt to identify the involved player(s):\n"
            "  • If a jersey number is clearly visible in the footage, record it in `player_number`\n"
            "  • If you can match that number to a roster entry below, record `player_name` (use the EXACT name from the roster)\n"
            "  • **iter101: If the number is too small or blurry to read confidently, do NOT guess.** Leave `player_number` null and use the `label` field to add a descriptive hint (e.g., 'striker in dark kit', 'left winger, tall'). Better to leave the field null than to ship a wrong number.\n"
            "  • Always TRY to read at least the GOAL scorers' and KEEPER's numbers — those are the easiest to spot (the scorer is the celebrating player; the keeper is the one near the net wearing a different-colored kit).\n\n"
            "**OUTPUT FORMAT.** Return ONLY a JSON array of event objects. Each object MUST have:\n"
            "  - \"time\": match timestamp in seconds (number, from match start)\n"
            "  - \"type\": one of \"goal\", \"shot\", \"save\", \"foul\", \"card\", \"substitution\", \"tactical\", \"chance\"\n"
            "  - \"label\": short description (max 60 chars). For goals, include scorer's name/number if known, or appearance hint.\n"
            f"  - \"team\": which team (\"{match['team_home']}\" or \"{match['team_away']}\" or \"neutral\")\n"
            "  - \"importance\": 1-5 (5 = goal/red card, 4 = clear chance/save, 3 = shot, 2 = foul, 1 = minor)\n"
            "  - \"player_number\": jersey number if visible (integer or null — DO NOT GUESS)\n"
            "  - \"player_name\": exact roster name if you can identify the player (string or null)\n\n"
            "Be THOROUGH — aim for 20-35 events covering every goal, shot, save, key foul, and tactical moment. "
            "Coverage > brevity: better to log a near-miss as a `chance` than to skip it.\n\n"
            f"Return ONLY the JSON array, no other text.{roster_context}"
        ),
    }


async def parse_and_store_markers(
    response: str,
    video_id: str,
    match_id: str,
    user_id: str,
    auto_create_clips_callback=None,
) -> int:
    """Parse a timeline_markers JSON response and persist the markers.

    `auto_create_clips_callback(video_id, user_id, match_id)` is invoked at the
    end if provided — keeps this module decoupled from the clip-creation
    helper that still lives in server.py.
    """
    clean = response.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
    markers_data = _json.loads(clean)
    if not isinstance(markers_data, list):
        return 0
    await db.markers.delete_many(
        {"video_id": video_id, "user_id": user_id, "auto_generated": True}
    )
    for m in markers_data:
        # iter99 — capture player_number + player_name when Gemini provides them
        pn_raw = m.get("player_number")
        try:
            player_number = int(pn_raw) if pn_raw is not None and str(pn_raw).strip() != "" else None
        except (TypeError, ValueError):
            player_number = None
        player_name = m.get("player_name")
        if player_name is not None:
            player_name = str(player_name)[:60].strip() or None

        marker_doc = {
            "id": str(uuid.uuid4()),
            "video_id": video_id,
            "match_id": match_id,
            "user_id": user_id,
            "time": float(m.get("time", 0)),
            "type": m.get("type", "chance"),
            "label": str(m.get("label", ""))[:100],
            "team": m.get("team", "neutral"),
            "importance": min(5, max(1, int(m.get("importance", 3)))),
            "player_number": player_number,
            "player_name": player_name,
            "auto_generated": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.markers.insert_one(marker_doc)
    logger.info(f"Stored {len(markers_data)} AI timeline markers for video {video_id}")
    if auto_create_clips_callback is not None:
        try:
            await auto_create_clips_callback(video_id, user_id, match_id)
        except Exception as e:
            logger.warning(f"auto_create_clips_callback failed: {e}")
    return len(markers_data)


async def run_single_analysis(
    video_id: str,
    user_id: str,
    match_id: str,
    analysis_type: str,
    video_file_path: str,
    prompt: str,
    auto_create_clips_callback=None,
) -> str:
    """Send one analysis prompt to Gemini and persist the result.

    Lazy-imports emergentintegrations so this module loads even when the SDK
    isn't installed (e.g., during regression tests that don't call AI).
    """
    from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType

    chat = LlmChat(
        api_key=_emergent_key(),
        session_id=f"auto-{video_id}-{analysis_type}",
        system_message=(
            "You are an expert soccer analyst. You will receive the full match "
            "video (compressed). Analyze the entire match and provide detailed "
            "tactical insights, player assessments, highlight identification, "
            "and precise timestamp markers for key events."
        ),
    ).with_model("gemini", "gemini-3.1-pro-preview")

    video_file = FileContentWithMimeType(
        file_path=video_file_path, mime_type="video/mp4"
    )
    response = await chat.send_message(
        UserMessage(text=prompt, file_contents=[video_file])
    )

    analysis_doc = {
        "id": str(uuid.uuid4()),
        "video_id": video_id,
        "match_id": match_id,
        "user_id": user_id,
        "analysis_type": analysis_type,
        "content": response,
        "status": "completed",
        "auto_generated": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.analyses.insert_one(analysis_doc)
    logger.info(f"Auto-processing {video_id}: {analysis_type} COMPLETED")

    if analysis_type == "timeline_markers" and response:
        try:
            await parse_and_store_markers(
                response, video_id, match_id, user_id, auto_create_clips_callback
            )
        except Exception as parse_err:
            logger.warning(f"Failed to parse timeline markers JSON: {parse_err}")

    return response


async def prepare_video_sample(video: dict, trim_start: float = None, trim_end: float = None) -> str:
    """Compress entire video (or trimmed portion) to 360p for AI analysis.
    For Gemini File API: target <1.5GB, 360p resolution."""
    ext = video["original_filename"].split(".")[-1] if "." in video["original_filename"] else "mp4"
    raw_path = tempfile.mktemp(suffix=f".{ext}", dir="/var/video_chunks")
    clip_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")

    try:
        if video.get("is_chunked"):
            chunk_paths = video.get("chunk_paths", {})
            chunk_backends = video.get("chunk_backends", {})
            total_chunks = video.get("total_chunks", len(chunk_paths))

            logger.info(f"Assembling full video from {total_chunks} chunks")
            with open(raw_path, 'wb') as f:
                # iter87 (P0): fail-fast on missing/unreadable chunks instead
                # of zero-filling. Zero-filling a chunk that contains (or is
                # adjacent to) the moov atom silently corrupts the mp4 — and
                # ffmpeg surfaces it as the confusing "moov atom not found"
                # error instead of the actual root cause (chunk N is missing).
                # Surface it as a real error so the user gets the right action:
                # re-upload.
                for i in range(total_chunks):
                    path = chunk_paths.get(str(i))
                    backend = chunk_backends.get(str(i), "storage")
                    if not path:
                        raise RuntimeError(
                            f"Chunk {i} of {total_chunks} is missing — re-upload required. "
                            "This is a rare data-loss event; chunks are usually safe even "
                            "across pod restarts post-iter83."
                        )
                    # iter87: also handle persistent_filesystem (iter83) here,
                    # not just the legacy "filesystem" tag.
                    if backend in ("filesystem", "persistent_filesystem") and not os.path.exists(path):
                        raise RuntimeError(
                            f"Chunk {i} of {total_chunks} ({backend}) was lost — re-upload required. "
                            f"path={path}"
                        )
                    chunk_info = {"backend": backend, "path": path}
                    try:
                        data = await read_chunk_data(video["id"], i, chunk_info)
                        f.write(data)
                        del data
                    except Exception as e:
                        raise RuntimeError(
                            f"Chunk {i} of {total_chunks} unreadable ({backend}): {str(e)[:120]} — re-upload required."
                        ) from e

            raw_size = os.path.getsize(raw_path)
            logger.info(f"Assembled full video: {raw_size/(1024*1024*1024):.2f}GB")
        else:
            data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
            with open(raw_path, 'wb') as f:
                f.write(data)
            del data

        video_size_gb = os.path.getsize(raw_path) / (1024 * 1024 * 1024)

        # Build a tiered list of (scale, fps, crf, timeout_s, label) presets.
        # Tier 0 is the "ideal" quality for the file size; later tiers trade
        # quality for memory/time to survive constrained pods. The auto-retry
        # loop only escalates on transient failures (OOM, timeout) — NOT on
        # deterministic ones like moov-atom-missing or invalid-data, where
        # retrying with smaller settings won't change the outcome.
        # iter97 — Aggressive-tier threshold lowered from 2 GB to 800 MB.
        # Production bug 2026-05-27 video 1140ed3a (1.04 GB / 1:47:48 / 1080p30):
        # File landed in the <2 GB tier → started at 360p/12fps → pod OOM'd
        # within seconds of ffmpeg starting (the iter75 guard only catches it
        # after 3 attempts ≈ 30 min). Lowering to 800 MB means any video
        # large enough to risk OOM jumps straight to the safe 180p/5fps tier.
        # Quality loss is acceptable for Gemini AI analysis — it just needs to
        # see motion + spatial layout, not pretty pixels.
        if video_size_gb > 0.8:
            tiers = [
                ("scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2", "5", "40", 1800, "180p/5fps/crf40"),
                ("scale=240:135:force_original_aspect_ratio=decrease,pad=240:135:(ow-iw)/2:(oh-ih)/2", "3", "45", 900,  "135p/3fps/crf45 [retry-1]"),
            ]
        else:
            tiers = [
                ("scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2", "12", "35", 1800, "360p/12fps/crf35"),
                ("scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2", "6",  "42", 900,  "180p/6fps/crf42 [retry-1]"),
            ]

        last_error_msg = None
        video_id_for_log = video.get("id", "unknown")
        user_id_for_log = video.get("user_id", "unknown")
        for tier_idx, (scale_filter, fps, crf, tier_timeout, label) in enumerate(tiers):
            ffmpeg_cmd = ["ffmpeg", "-y"]
            # iter97 — Memory guards. -threads 1 prevents libx264 from spawning
            # 8 worker threads each with their own frame buffers. -bufsize and
            # -max_muxing_queue_size cap mux-side memory growth. -fflags
            # +discardcorrupt skips bad packets instead of buffering them
            # waiting for a clean GOP boundary.
            ffmpeg_cmd += ["-threads", "1", "-fflags", "+discardcorrupt"]
            if trim_start is not None and trim_start > 0:
                ffmpeg_cmd += ["-ss", str(int(trim_start))]
            ffmpeg_cmd += ["-i", raw_path]
            if trim_end is not None and trim_end > 0:
                duration = trim_end - (trim_start or 0)
                ffmpeg_cmd += ["-t", str(int(duration))]

            ffmpeg_cmd += [
                "-vf", scale_filter,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", crf,
                "-r", fps,
                "-c:a", "aac",
                "-b:a", "32k",
                "-ac", "1",
                "-bufsize", "16M",
                "-max_muxing_queue_size", "256",
                "-movflags", "+faststart",
                clip_path,
            ]

            logger.info(f"Compressing video tier {tier_idx} ({label}) trim={trim_start}-{trim_end}, src={video_size_gb:.1f}GB")
            tier_started = time.time()
            await _log_event(
                video_id=video_id_for_log, user_id=user_id_for_log,
                event_type="tier_attempt", tier_idx=tier_idx, tier_label=label,
                source_size_gb=video_size_gb,
            )
            try:
                result = await run_in_threadpool(
                    subprocess.run, ffmpeg_cmd,
                    capture_output=True, text=True, timeout=tier_timeout,
                )
            except subprocess.TimeoutExpired:
                # Timeout is transient enough to warrant a retry at smaller
                # scale. If we're already on the last tier, escalate to user.
                tier_duration = time.time() - tier_started
                last_error_msg = (
                    f"ffmpeg timed out after {tier_timeout // 60} min on a {video_size_gb:.1f}GB source. "
                    "Try trimming the match (only the first/second half), or compress further (CQ 28 / 720p in HandBrake)."
                )
                logger.warning(f"Tier {tier_idx} ({label}) timed out — escalating to next tier if available")
                await _log_event(
                    video_id=video_id_for_log, user_id=user_id_for_log,
                    event_type="tier_failed", tier_idx=tier_idx, tier_label=label,
                    failure_mode="timeout", duration_seconds=tier_duration,
                    source_size_gb=video_size_gb, error_message=last_error_msg,
                )
                # Clean partial output before retrying
                if os.path.exists(clip_path):
                    try:
                        os.unlink(clip_path)
                    except Exception:
                        pass
                continue

            # Success?
            if result.returncode == 0 and os.path.exists(clip_path) and os.path.getsize(clip_path) > 1000:
                clip_size = os.path.getsize(clip_path)
                tier_duration = time.time() - tier_started
                if tier_idx > 0:
                    logger.warning(f"Tier {tier_idx} ({label}) succeeded after earlier tier failures — using degraded preset")
                logger.info(f"Created {clip_size/(1024*1024):.1f}MB compressed video for AI ({label})")
                await _log_event(
                    video_id=video_id_for_log, user_id=user_id_for_log,
                    event_type="tier_succeeded", tier_idx=tier_idx, tier_label=label,
                    source_size_gb=video_size_gb, output_size_mb=clip_size / (1024 * 1024),
                    duration_seconds=tier_duration,
                )
                await _log_event(
                    video_id=video_id_for_log, user_id=user_id_for_log,
                    event_type="final_success", tier_idx=tier_idx, tier_label=label,
                    source_size_gb=video_size_gb, output_size_mb=clip_size / (1024 * 1024),
                )
                # Free the raw video before returning
                if os.path.exists(raw_path):
                    try:
                        os.unlink(raw_path)
                    except Exception:
                        pass
                return clip_path

            # Failed — classify so we know whether to retry or bail.
            stderr = result.stderr[-1000:] if result.stderr else ""
            stderr_lower = stderr.lower()
            tier_duration = time.time() - tier_started

            # Deterministic failures: do NOT retry — smaller scale won't help.
            if "moov atom not found" in stderr_lower:
                msg = "Video file is incomplete (moov atom missing). Please re-upload — the chunked transfer didn't finalize cleanly."
                await _log_event(
                    video_id=video_id_for_log, user_id=user_id_for_log,
                    event_type="final_failure", tier_idx=tier_idx, tier_label=label,
                    failure_mode="moov_missing", duration_seconds=tier_duration,
                    source_size_gb=video_size_gb, error_message=msg,
                )
                raise Exception(msg)
            if "invalid data found" in stderr_lower:
                msg = "File doesn't look like a valid video. Please re-export as MP4 (H.264) and upload again."
                await _log_event(
                    video_id=video_id_for_log, user_id=user_id_for_log,
                    event_type="final_failure", tier_idx=tier_idx, tier_label=label,
                    failure_mode="invalid_data", duration_seconds=tier_duration,
                    source_size_gb=video_size_gb, error_message=msg,
                )
                raise Exception(msg)
            if "no space left on device" in stderr_lower:
                msg = "Server disk is full. Please retry in a few minutes — auto-cleanup will free space."
                await _log_event(
                    video_id=video_id_for_log, user_id=user_id_for_log,
                    event_type="final_failure", tier_idx=tier_idx, tier_label=label,
                    failure_mode="no_space", duration_seconds=tier_duration,
                    source_size_gb=video_size_gb, error_message=msg,
                )
                raise Exception(msg)

            # Transient failures: retry at smaller scale.
            if result.returncode in (-9, 137) or "killed" in stderr_lower:
                last_error_msg = (
                    f"Video processing ran out of memory on a {video_size_gb:.1f}GB source. "
                    "Compress further (HandBrake → Fast 720p30 / CQ 28) or split the match film in half and upload each half as a separate match."
                )
                logger.warning(f"Tier {tier_idx} ({label}) OOM/killed — escalating to next tier if available")
                await _log_event(
                    video_id=video_id_for_log, user_id=user_id_for_log,
                    event_type="tier_failed", tier_idx=tier_idx, tier_label=label,
                    failure_mode="oom", duration_seconds=tier_duration,
                    source_size_gb=video_size_gb, error_message=last_error_msg,
                )
                if os.path.exists(clip_path):
                    try:
                        os.unlink(clip_path)
                    except Exception:
                        pass
                continue

            # Unknown failure — bail with stderr tail so the cause is visible.
            tail = stderr.strip().split("\n")[-1] if stderr.strip() else f"exit code {result.returncode}"
            logger.error(f"ffmpeg compress failed (tier {tier_idx} {label}): rc={result.returncode}, stderr={stderr}")
            msg = f"ffmpeg failed: {tail[:200]}"
            await _log_event(
                video_id=video_id_for_log, user_id=user_id_for_log,
                event_type="final_failure", tier_idx=tier_idx, tier_label=label,
                failure_mode="unknown", duration_seconds=tier_duration,
                source_size_gb=video_size_gb, error_message=msg,
            )
            raise Exception(msg)

        # All tiers exhausted — surface the last classified message (already
        # set to a coach-friendly string by the OOM/timeout branches above).
        if os.path.exists(raw_path):
            try:
                os.unlink(raw_path)
            except Exception:
                pass
        # We previously logged tier_failed events; emit one summary final_failure
        # so dashboards/queries can group by "did this video ever succeed?".
        await _log_event(
            video_id=video_id_for_log, user_id=user_id_for_log,
            event_type="final_failure", tier_idx=len(tiers) - 1,
            tier_label="all_tiers_exhausted",
            failure_mode="oom" if last_error_msg and "memory" in last_error_msg.lower() else "timeout",
            source_size_gb=video_size_gb, error_message=last_error_msg,
        )
        raise Exception(last_error_msg or "Video processing failed at every scaling tier. Please trim or compress further.")

    except Exception:
        for p in [raw_path, clip_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
        raise


async def _select_motion_windows(
    raw_path: str,
    duration: float,
    num_segments: int,
    window_duration: int,
) -> list:
    """iter101 — Scene-cut-biased segment selection.

    Runs ffmpeg's `scdet` filter on a low-res 240p proxy of the source to
    cheaply identify scene-change timestamps + scores. Aggregates scores
    into `window_duration`-second buckets, picks the `num_segments` highest-
    scoring NON-OVERLAPPING buckets, and returns their start timestamps.

    Returns [] on any failure (scdet binary missing, parse error, too few
    windows detected) — caller falls back to even spacing.

    Why scene-cut? Soccer goals always coincide with the highest-motion
    moment in the match (ball-in-net → celebration → restart). With even
    spacing, a 30-sec goal window in a 107-min match has ~30% chance of
    falling between samples. Scene-biased sampling pushes that to ~95%.
    """
    try:
        # Run scene detection on a 240p proxy — decoded fast, no encoding,
        # output discarded. Stderr carries the scdet metadata lines.
        cmd = [
            "ffmpeg", "-hide_banner", "-nostats",
            "-threads", "1",
            "-i", raw_path,
            "-vf", "scale=-2:240,scdet=threshold=8",
            "-an", "-f", "null", "-",
        ]
        # Soft timeout — scdet on a 107-min 1 GB file should finish in 30-90s
        # on a constrained pod. Bigger files could push higher; cap at 5 min.
        proc = await run_in_threadpool(
            subprocess.run, cmd,
            capture_output=True, text=True, timeout=300,
        )
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired:
        logger.warning("[scene-cut] scdet timed out — falling back to even spacing")
        return []
    except Exception as e:
        logger.warning(f"[scene-cut] scdet failed: {e} — falling back to even spacing")
        return []

    # Parse lines like:
    #   [scdet @ 0x...] lavfi.scd.mafd: 12.34 lavfi.scd.score: 17.42 lavfi.scd.time: 234.567
    import re
    scd_events: list[tuple[float, float]] = []  # (timestamp, score)
    for line in stderr.splitlines():
        if "lavfi.scd.time" not in line:
            continue
        m_t = re.search(r"lavfi\.scd\.time:\s*([\d.]+)", line)
        m_s = re.search(r"lavfi\.scd\.score:\s*([\d.]+)", line)
        if m_t and m_s:
            try:
                scd_events.append((float(m_t.group(1)), float(m_s.group(1))))
            except ValueError:
                continue

    if len(scd_events) < num_segments:
        logger.info(
            f"[scene-cut] only {len(scd_events)} scene events detected for "
            f"{duration:.0f}s video — falling back to even spacing"
        )
        return []

    # Aggregate scores into window_duration buckets keyed by bucket start.
    # Bucket = floor(t / window_duration) * window_duration.
    bucket_scores: dict[int, float] = {}
    for t, score in scd_events:
        if t < 0 or t > max(0.0, duration - window_duration):
            continue
        bucket = int(t // window_duration) * window_duration
        bucket_scores[bucket] = bucket_scores.get(bucket, 0.0) + score

    if not bucket_scores:
        return []

    # Sort buckets by descending score and greedily pick non-overlapping ones.
    sorted_buckets = sorted(bucket_scores.items(), key=lambda kv: kv[1], reverse=True)
    picked: list[float] = []
    for bucket_start, _ in sorted_buckets:
        if len(picked) >= num_segments:
            break
        # Enforce non-overlap: each window must be >= window_duration apart
        # from every already-picked window.
        if all(abs(bucket_start - p) >= window_duration for p in picked):
            # Pad backward by 5s to capture lead-up before the scene-cut peak
            # (e.g., the build-up before a goal).
            picked.append(max(0.0, bucket_start - 5))

    if len(picked) < max(8, num_segments // 2):
        # Not enough non-overlapping high-motion windows — fall back so we
        # don't ship a tiny sample size.
        logger.info(
            f"[scene-cut] only {len(picked)} non-overlapping windows survived "
            "dedup — falling back to even spacing"
        )
        return []

    picked.sort()
    logger.info(
        f"[scene-cut] selected {len(picked)} motion windows from "
        f"{len(scd_events)} scene events ({duration:.0f}s video)"
    )
    return picked


async def prepare_video_segments_720p(video: dict) -> tuple:
    """Extract multiple 480p segments from across the match for high-quality timeline analysis.
    Returns (clip_path, segment_info_text) — the concatenated segment file and
    a text block mapping each segment to its real match time offset."""
    ext = video["original_filename"].split(".")[-1] if "." in video["original_filename"] else "mp4"
    raw_path = tempfile.mktemp(suffix=f".{ext}", dir="/var/video_chunks")
    clip_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")
    segment_files = []

    try:
        if video.get("is_chunked"):
            chunk_paths = video.get("chunk_paths", {})
            chunk_backends = video.get("chunk_backends", {})
            total_chunks = video.get("total_chunks", len(chunk_paths))

            logger.info(f"[720p segments] Assembling full video from {total_chunks} chunks")
            with open(raw_path, 'wb') as f:
                # iter87 (P0): fail-fast on missing/unreadable chunks. See
                # the matching block in prepare_video_sample for rationale.
                for i in range(total_chunks):
                    path = chunk_paths.get(str(i))
                    backend = chunk_backends.get(str(i), "storage")
                    if not path:
                        raise RuntimeError(
                            f"Chunk {i} of {total_chunks} is missing — re-upload required."
                        )
                    if backend in ("filesystem", "persistent_filesystem") and not os.path.exists(path):
                        raise RuntimeError(
                            f"Chunk {i} of {total_chunks} ({backend}) was lost — re-upload required. "
                            f"path={path}"
                        )
                    chunk_info = {"backend": backend, "path": path}
                    try:
                        data = await read_chunk_data(video["id"], i, chunk_info)
                        f.write(data)
                        del data
                    except Exception as e:
                        raise RuntimeError(
                            f"Chunk {i} of {total_chunks} unreadable ({backend}): {str(e)[:120]} — re-upload required."
                        ) from e
        else:
            data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
            with open(raw_path, 'wb') as f:
                f.write(data)
            del data

        probe = await run_in_threadpool(
            subprocess.run,
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", raw_path],
            capture_output=True, text=True, timeout=60,
        )
        duration = 0
        if probe.returncode == 0 and probe.stdout.strip():
            try:
                duration = float(probe.stdout.strip())
            except ValueError:
                pass
        logger.info(f"[720p segments] Video duration: {duration:.0f}s ({duration/60:.1f}min)")

        if duration <= 0:
            raise Exception("Could not determine video duration")

        # iter101 — Scene-cut-biased segment selection.
        # Even-spaced sampling (iter99) was missing goals because goals are
        # 10-30 sec windows in a 107-min match — chance alignment with the
        # 45s sample windows was ~30%. Goals always coincide with the
        # highest-motion moment in soccer (ball-in-net → celebration →
        # kickoff). Use ffmpeg `scdet` filter on a cheap 240p proxy stream
        # to find scene-change peaks, then pick the 18 best-spaced peaks.
        # Falls back to iter99 even spacing if scene detection yields too
        # few peaks (e.g., static cameras with no cuts, or scdet failure).
        segment_duration = 45
        num_segments = 18
        if duration < segment_duration * num_segments:
            num_segments = max(1, int(duration / segment_duration))

        # iter103 — Tier-down for memory-constrained pods.
        # Production bug 2026-05-28 (LFC 2007B vs AYSO 1.04 GB / 1:47:48):
        # iter101 introduced 720p segments + scdet pre-pass, which together
        # pushed total processing memory above the cgroup limit on the
        # production pod. iter97 already does the same trick on
        # `prepare_video_sample` (>800 MB → drop to 180p safe tier). Apply
        # the same gating to the segment path:
        #   • >800 MB source: 480p / 12fps / CRF 28 segments + SKIP scdet
        #     (use even spacing). Matches iter99-era settings that were
        #     proven to work on this pod.
        #   • ≤800 MB source: 720p / 15fps / CRF 24 + scdet (iter101 path).
        video_size_gb = video.get("file_size_bytes", 0) / (1024 ** 3) if video.get("file_size_bytes") else 0
        heavy_file = video_size_gb > 0.8
        if heavy_file:
            seg_scale = "scale=-2:480"
            seg_fps = "12"
            seg_crf = "28"
            tier_label = f"480p/12fps/crf28 (heavy file {video_size_gb:.2f}GB — skipping scdet)"
            segment_starts = []  # skip the scdet pass — directly use even spacing below
        else:
            seg_scale = "scale=-2:720"
            seg_fps = "15"
            seg_crf = "24"
            tier_label = "720p/15fps/crf24 (iter101 high-quality tier)"
            segment_starts = await _select_motion_windows(
                raw_path=raw_path,
                duration=duration,
                num_segments=num_segments,
                window_duration=segment_duration,
            )

        if not segment_starts:
            # Fallback to iter99 even spacing (safer than crashing if scdet
            # binary is missing or the source has zero scene changes — also
            # the heavy-file path lands here intentionally).
            if heavy_file:
                logger.info(
                    f"[scene-cut] heavy file ({video_size_gb:.2f}GB) — using even spacing"
                )
            else:
                logger.warning(
                    "[scene-cut] no usable motion windows detected — falling back to even spacing"
                )
            segment_starts = []
            for i in range(num_segments):
                pct = i / max(1, num_segments - 1)
                start = pct * max(0, duration - segment_duration)
                segment_starts.append(max(0, start))

        logger.info(f"[segments] Extracting {num_segments} x {segment_duration}s at {tier_label}")

        segment_info_parts = []
        for idx, start in enumerate(segment_starts):
            seg_path = tempfile.mktemp(suffix=f"_seg{idx}.mp4", dir="/var/video_chunks")
            seg_cmd = [
                "ffmpeg", "-y",
                "-threads", "1",  # iter97 memory guard
                "-fflags", "+discardcorrupt",
                "-ss", str(int(start)),
                "-i", raw_path,
                "-t", str(segment_duration),
                "-vf", seg_scale,  # iter103 — tier-adaptive: 480p heavy / 720p light
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", seg_crf,  # iter103 — tier-adaptive
                "-r", seg_fps,    # iter103 — tier-adaptive
                "-c:a", "aac",
                "-b:a", "48k",
                "-bufsize", "16M",  # iter97 memory guard
                "-max_muxing_queue_size", "256",  # iter97 memory guard
                "-movflags", "+faststart",
                seg_path,
            ]
            seg_result = await run_in_threadpool(
                subprocess.run, seg_cmd,
                capture_output=True, text=True, timeout=300,
            )
            if seg_result.returncode == 0 and os.path.exists(seg_path) and os.path.getsize(seg_path) > 1000:
                seg_size = os.path.getsize(seg_path) / (1024 * 1024)
                segment_files.append(seg_path)
                s_min, s_sec = divmod(int(start), 60)
                e_min, e_sec = divmod(int(start + segment_duration), 60)
                segment_info_parts.append(
                    f"Segment {idx+1}: match time {s_min}:{s_sec:02d} to {e_min}:{e_sec:02d}"
                )
                logger.info(f"  Segment {idx+1}/{num_segments}: {start:.0f}s, {seg_size:.1f}MB")
            else:
                logger.warning(f"  Segment {idx+1} failed at {start:.0f}s")
                if os.path.exists(seg_path):
                    os.unlink(seg_path)

        if os.path.exists(raw_path):
            os.unlink(raw_path)
            logger.info("[720p segments] Deleted raw video file")

        if not segment_files:
            raise Exception("Failed to extract any video segments")

        if len(segment_files) == 1:
            os.rename(segment_files[0], clip_path)
            segment_files = []
        else:
            concat_list = tempfile.mktemp(suffix=".txt", dir="/var/video_chunks")
            with open(concat_list, 'w') as f:
                for seg in segment_files:
                    f.write(f"file '{seg}'\n")
            concat_result = await run_in_threadpool(
                subprocess.run,
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_list, "-c", "copy", "-movflags", "+faststart", clip_path],
                capture_output=True, text=True, timeout=300,
            )
            if os.path.exists(concat_list):
                os.unlink(concat_list)
            for seg in segment_files:
                if os.path.exists(seg):
                    os.unlink(seg)
            segment_files = []
            if concat_result.returncode != 0:
                raise Exception("Failed to concatenate video segments")

        clip_size = os.path.getsize(clip_path) / (1024 * 1024)
        segment_info_text = "\n".join(segment_info_parts)
        logger.info(f"[720p segments] Created {clip_size:.1f}MB combined clip ({len(segment_info_parts)} segments)")
        return clip_path, segment_info_text

    except Exception:
        for p in [raw_path, clip_path] + segment_files:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
        raise


async def _check_chunk_integrity(video: dict) -> tuple[str, int, int]:
    """Return (integrity, available, total) for a chunked video. Mirrors the
    logic in routes/videos.py::get_video_metadata so the UI banner and the
    processing fail-fast guard agree on what counts as "incomplete".

    Returns ("full", N, N) for non-chunked videos (we trust that single-shot
    uploads either fully landed or never created a video document at all).
    """
    if not video.get("is_chunked"):
        return ("full", 0, 0)
    chunk_paths = video.get("chunk_paths", {})
    chunk_backends = video.get("chunk_backends", {})
    total = video.get("total_chunks", len(chunk_paths))
    available = 0
    for i in range(total):
        path = chunk_paths.get(str(i))
        backend = chunk_backends.get(str(i), "storage")
        # iter88: chunks tagged "lost" by the migration loop are unrecoverable —
        # never count them as available no matter what chunk_paths says.
        if backend == "lost":
            continue
        if not path:
            continue
        # iter87: also check persistent_filesystem (iter83) — pre-iter87 a
        # migration race could leave the DB pointing at a deleted local file.
        if backend in ("filesystem", "persistent_filesystem") and not os.path.exists(path):
            continue
        available += 1
    if total == 0:
        return ("full", 0, 0)
    if available == total:
        return ("full", available, total)
    if available > 0:
        return ("partial", available, total)
    return ("unavailable", available, total)


async def run_auto_processing(
    video_id: str,
    user_id: str,
    only_types: list = None,
    auto_create_clips_callback=None,
):
    """Background task: runs analysis types after upload. Saves each independently
    so partial completion survives restarts.

    `auto_create_clips_callback(video_id, user_id, match_id)` is invoked after
    timeline markers are stored — kept as a callback so this module doesn't import
    server.py.
    """
    all_types = ["tactical", "player_performance", "highlights", "timeline_markers"]
    analysis_types = only_types if only_types else all_types
    tmp_path = None
    tmp_path_720p = None

    try:
        await db.videos.update_one(
            {"id": video_id},
            {"$set": {"processing_status": "processing", "processing_progress": 0}},
        )

        video = await db.videos.find_one({"id": video_id}, {"_id": 0})
        if not video:
            logger.error(f"Auto-processing: video {video_id} not found")
            return

        # Fail-fast on incomplete uploads. Without this, prepare_video_sample
        # would either silently produce a broken sample or get OOM-killed
        # mid-pass on a 9 GB+ source — and the user would just see the
        # processing-status banner sit at 0% forever (real production bug
        # 2026-05-16, video 48823490, 980/991 chunks).
        integrity, available, total = await _check_chunk_integrity(video)
        if integrity != "full":
            pct = round((available / total) * 100, 1) if total else 0
            msg = (
                f"Upload incomplete ({available} of {total} chunks, {pct}%). "
                "Re-upload required — AI analysis can't run on a partial file."
            )
            logger.error(f"Auto-processing: refusing to process {video_id}: {msg}")
            await db.videos.update_one(
                {"id": video_id},
                {"$set": {
                    "processing_status": "failed",
                    "processing_error": msg,
                    "processing_progress": 0,
                    "processing_current": None,
                    "processing_completed_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
            try:
                await _log_event(
                    video_id=video_id,
                    user_id=user_id,
                    event_type="final_failure",
                    failure_mode="incomplete_upload",
                    source_size_gb=(video.get("file_size_bytes") or 0) / (1024 ** 3) or None,
                    error_message=msg,
                )
            except Exception:
                # Instrumentation must never break the pipeline it instruments
                pass
            return

        match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})
        if not match:
            logger.error(f"Auto-processing: match for video {video_id} not found")
            return

        roster = await db.players.find({"match_id": video["match_id"]}, {"_id": 0}).to_list(100)
        roster_context = build_roster_context(roster)

        try:
            tmp_path = await prepare_video_sample(video)
        except Exception as e:
            # The new prepare_video_sample raises user-facing exceptions with
            # actionable copy ("compress further", "trim the match", etc).
            # Pass them through unchanged instead of burying them under another
            # "Failed to prepare video: " prefix + 200-char truncation that
            # hid the real cause on production iter62.
            msg = str(e).strip() or "Video preparation failed"
            logger.error(f"Auto-processing: failed to prepare video sample: {msg}")
            await db.videos.update_one(
                {"id": video_id},
                {"$set": {"processing_status": "failed", "processing_error": msg[:500]}},
            )
            return

        segments_info = None
        if "timeline_markers" in analysis_types:
            try:
                tmp_path_720p, segments_info = await prepare_video_segments_720p(video)
                logger.info("Prepared 720p segments for timeline markers")
            except Exception as e:
                logger.warning(f"720p segments failed, will fall back to standard sample: {e}")

        segment_preamble = ""
        if segments_info:
            segment_preamble = "Segment timing (these are the real match times shown in the video):\n" + segments_info + "\n\n"
        prompts = build_analysis_prompts(match, roster_context, segment_preamble)

        for idx, analysis_type in enumerate(analysis_types):
            progress = int((idx / len(analysis_types)) * 100)
            await db.videos.update_one(
                {"id": video_id},
                {"$set": {"processing_progress": progress, "processing_current": analysis_type}},
            )
            logger.info(f"Auto-processing {video_id}: {analysis_type} ({progress}%)")

            use_path = tmp_path_720p if (analysis_type == "timeline_markers" and tmp_path_720p) else tmp_path

            try:
                await run_single_analysis(
                    video_id, user_id, video["match_id"], analysis_type, use_path,
                    prompts[analysis_type], auto_create_clips_callback,
                )
            except Exception as e:
                logger.error(f"Auto-processing {video_id}: {analysis_type} FAILED: {e}")
                analysis_doc = {
                    "id": str(uuid.uuid4()),
                    "video_id": video_id,
                    "match_id": video["match_id"],
                    "user_id": user_id,
                    "analysis_type": analysis_type,
                    "content": f"Analysis could not be completed: {str(e)[:200]}",
                    "status": "failed",
                    "auto_generated": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                await db.analyses.insert_one(analysis_doc)

        completed_analyses = await db.analyses.find(
            {"video_id": video_id, "user_id": user_id, "status": "completed"},
            {"_id": 0, "analysis_type": 1},
        ).to_list(10)
        final_status = "completed" if len(completed_analyses) > 0 else "failed"
        await db.videos.update_one(
            {"id": video_id},
            {"$set": {"processing_status": final_status, "processing_progress": 100, "processing_current": None, "processing_completed_at": datetime.now(timezone.utc).isoformat()}},
        )
        logger.info(f"Auto-processing {'COMPLETE' if final_status == 'completed' else 'FAILED (all types)'} for video {video_id}")

        # Fire push notification (best-effort, non-blocking)
        try:
            from services.push_notifications import send_to_user
            match = await db.matches.find_one(
                {"video_id": video_id},
                {"_id": 0, "team_home": 1, "team_away": 1, "id": 1},
            )
            if match:
                match_label = f"{match.get('team_home','?')} vs {match.get('team_away','?')}"
                title = "Match analysis ready" if final_status == "completed" else "Match analysis finished with issues"
                body = f"AI tactical breakdown is ready for {match_label}." if final_status == "completed" else f"Some analyses for {match_label} didn't complete — tap to review."
                deep_link = f"/match/{match['id']}"
                await send_to_user(user_id, title, body, url=deep_link)
                # iter86 — also write to user_notifications so the in-app
                # poller on OTHER devices (which didn't necessarily subscribe
                # to push) shows the same toast + browser notification.
                try:
                    import uuid as _uuid
                    await db.user_notifications.insert_one({
                        "id": str(_uuid.uuid4()),
                        "user_id": user_id,
                        "type": "processing_complete" if final_status == "completed" else "processing_partial",
                        "title": title,
                        "body": body,
                        "deep_link": deep_link,
                        "video_id": video_id,
                        "match_id": match["id"],
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception as notif_err:
                    logger.info("user_notifications insert skipped: %s", notif_err)
        except Exception as push_err:
            logger.info("push notify skipped: %s", push_err)

    except Exception as e:
        logger.error(f"Auto-processing FAILED for video {video_id}: {e}")
        await db.videos.update_one(
            {"id": video_id},
            {"$set": {"processing_status": "failed", "processing_error": str(e)[:200]}},
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if tmp_path_720p and os.path.exists(tmp_path_720p):
            os.unlink(tmp_path_720p)
