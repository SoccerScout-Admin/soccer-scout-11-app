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
from datetime import datetime, timezone
from starlette.concurrency import run_in_threadpool
from db import db, CHUNK_SIZE
from services.storage import read_chunk_data, get_object_sync

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
            f"Analyze individual player performances in this soccer match between {match['team_home']} and {match['team_away']}. "
            "For each notable player provide:\n\n"
            "1. **Standout Performers** - Who were the best players and why?\n"
            "2. **Key Contributions** - Goals, assists, key passes, tackles\n"
            "3. **Work Rate & Positioning** - Movement, runs, defensive contribution\n"
            "4. **Decision Making** - Quality of decisions in key moments\n"
            "5. **Areas for Improvement** - What each key player could do better\n"
            f"6. **Player Ratings** - Rate key players out of 10 with justification{roster_context}"
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
            f"Watch this soccer match video between {match['team_home']} and {match['team_away']}. "
            "The video contains multiple segments from across the full match at high quality.\n\n"
            f"{segment_preamble}"
            "Identify EVERY key event with precise match timestamps (in seconds from the start of the match, NOT from the start of each segment).\n\n"
            "Return ONLY a JSON array of event objects. Each object must have:\n"
            "- \"time\": match timestamp in seconds (number, from match start)\n"
            "- \"type\": one of \"goal\", \"shot\", \"save\", \"foul\", \"card\", \"substitution\", \"tactical\", \"chance\"\n"
            "- \"label\": short description (max 60 chars)\n"
            f"- \"team\": which team (\"{match['team_home']}\" or \"{match['team_away']}\" or \"neutral\")\n"
            "- \"importance\": 1-5 (5 = most important, e.g. goals)\n\n"
            "Be thorough — identify goals, shots on target, saves, dangerous attacks, key fouls, tactical changes. "
            "Aim for 15-30 events across the full match.\n\n"
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
            chunk_size = video.get("chunk_size", CHUNK_SIZE)

            logger.info(f"Assembling full video from {total_chunks} chunks")
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
                    chunk_info = {"backend": backend, "path": path}
                    try:
                        data = await read_chunk_data(video["id"], i, chunk_info)
                        f.write(data)
                        del data
                    except Exception as e:
                        logger.warning(f"  Skipping chunk {i}: {str(e)[:60]}")
                        f.write(b'\x00' * chunk_size)

            raw_size = os.path.getsize(raw_path)
            logger.info(f"Assembled full video: {raw_size/(1024*1024*1024):.2f}GB")
        else:
            data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
            with open(raw_path, 'wb') as f:
                f.write(data)
            del data

        video_size_gb = os.path.getsize(raw_path) / (1024 * 1024 * 1024)
        if video_size_gb > 2:
            scale_filter = "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2"
            fps = "5"
            crf = "40"
        else:
            scale_filter = "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2"
            fps = "12"
            crf = "35"

        ffmpeg_cmd = ["ffmpeg", "-y"]
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
            "-movflags", "+faststart",
            clip_path,
        ]

        logger.info(f"Compressing video to {'240p/8fps' if video_size_gb > 2 else '360p/12fps'} (trim={trim_start}-{trim_end}, src={video_size_gb:.1f}GB)")
        result = await run_in_threadpool(
            subprocess.run, ffmpeg_cmd,
            capture_output=True, text=True, timeout=1800,
        )

        if os.path.exists(raw_path):
            os.unlink(raw_path)
            logger.info("Deleted raw video file")

        if result.returncode == 0 and os.path.exists(clip_path) and os.path.getsize(clip_path) > 1000:
            clip_size = os.path.getsize(clip_path)
            logger.info(f"Created {clip_size/(1024*1024):.1f}MB compressed video for AI")
            return clip_path

        stderr = result.stderr[-500:] if result.stderr else ""
        if "moov atom not found" in stderr:
            raise Exception("Video data incomplete — moov atom missing. Re-upload needed.")
        if "Invalid data found" in stderr:
            raise Exception("Not a valid video format. Re-upload a valid video file.")
        logger.error(f"ffmpeg compress failed: rc={result.returncode}, stderr={stderr}")
        raise Exception("Failed to compress video for analysis")

    except Exception:
        for p in [raw_path, clip_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
        raise


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
            chunk_size = video.get("chunk_size", CHUNK_SIZE)

            logger.info(f"[720p segments] Assembling full video from {total_chunks} chunks")
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
                    chunk_info = {"backend": backend, "path": path}
                    try:
                        data = await read_chunk_data(video["id"], i, chunk_info)
                        f.write(data)
                        del data
                    except Exception as e:
                        logger.warning(f"  Skipping chunk {i}: {str(e)[:60]}")
                        f.write(b'\x00' * chunk_size)
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

        segment_duration = 60
        num_segments = 12
        if duration < segment_duration * num_segments:
            num_segments = max(1, int(duration / segment_duration))

        segment_starts = []
        for i in range(num_segments):
            pct = i / max(1, num_segments - 1)
            start = pct * max(0, duration - segment_duration)
            segment_starts.append(max(0, start))

        logger.info(f"[720p segments] Extracting {num_segments} x {segment_duration}s segments at 480p")

        segment_info_parts = []
        for idx, start in enumerate(segment_starts):
            seg_path = tempfile.mktemp(suffix=f"_seg{idx}.mp4", dir="/var/video_chunks")
            seg_cmd = [
                "ffmpeg", "-y",
                "-ss", str(int(start)),
                "-i", raw_path,
                "-t", str(segment_duration),
                "-vf", "scale=-2:480",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "30",
                "-r", "12",
                "-c:a", "aac",
                "-b:a", "48k",
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

        match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})
        if not match:
            logger.error(f"Auto-processing: match for video {video_id} not found")
            return

        roster = await db.players.find({"match_id": video["match_id"]}, {"_id": 0}).to_list(100)
        roster_context = build_roster_context(roster)

        try:
            tmp_path = await prepare_video_sample(video)
        except Exception as e:
            logger.error(f"Auto-processing: failed to prepare video sample: {e}")
            await db.videos.update_one(
                {"id": video_id},
                {"$set": {"processing_status": "failed", "processing_error": f"Failed to prepare video: {str(e)[:200]}"}},
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
                await send_to_user(user_id, title, body, url=f"/match/{match['id']}")
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
