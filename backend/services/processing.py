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
    # iter107 — Jersey color context. When the user sets jersey colors during
    # match creation, prepend a kit-color preamble to EVERY prompt so Gemini
    # can disambiguate teams in 480p/720p footage instead of guessing by
    # position. The color disambiguator matters even more after iter103's
    # tier-down because 480p makes both teams look similar at distance.
    home_color = (match.get("team_home_jersey_color") or "").strip()
    away_color = (match.get("team_away_jersey_color") or "").strip()
    kit_preamble = ""
    if home_color or away_color:
        kit_parts = []
        if home_color:
            kit_parts.append(f"{match['team_home']} (home) wears {home_color}")
        if away_color:
            kit_parts.append(f"{match['team_away']} (away) wears {away_color}")
        kit_preamble = (
            "**TEAM KIT COLORS — use this to disambiguate teams.** "
            + "; ".join(kit_parts) + ".\n\n"
        )

    return {
        "tactical": (
            f"Analyze this soccer match video between {match['team_home']} and {match['team_away']}.\n\n"
            f"{kit_preamble}"
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
            f"{kit_preamble}"
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
            f"Identify and describe ALL key moments and highlights from this soccer match between {match['team_home']} and {match['team_away']}.\n\n"
            f"{kit_preamble}"
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
            f"{kit_preamble}"
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
        # iter107 — Veo-style match stats (possession + pass strings).
        # Returns a structured JSON object that the frontend can render as
        # a prominent stat card at the top of the video analysis page.
        "possession_stats": (
            f"You are watching a soccer match between {match['team_home']} (home) and {match['team_away']} (away).\n\n"
            f"{kit_preamble}"
            f"{segment_preamble}"
            "**YOUR JOB:** Estimate match-level possession + pass-stringing statistics for both teams. "
            "These are coarse estimates from the sampled segments — close enough is fine.\n\n"
            "**METHODOLOGY HINTS:**\n"
            "  • Possession = % of total ball-in-play time each team had the ball at their feet. "
            "Out-of-play time (throw-ins waiting, goal kicks not yet taken) doesn't count.\n"
            "  • Pass string = a sequence of consecutive passes by one team without the ball going dead "
            "(out of bounds, fouled, intercepted). A turnover via tackle or interception breaks the string.\n"
            "  • Longest pass string = the highest number of consecutive passes you observed in your "
            "samples for each team. Typical youth/HS games show 3-8; pro games 10-25.\n"
            "  • Total passes estimate = scale up from what you saw across the sampled segments. "
            "If you saw N passes total across X minutes of sampled footage in a Y-minute match, scale by Y/X.\n\n"
            "**OUTPUT FORMAT.** Return ONLY a JSON object (no array, no preamble) with these fields:\n"
            "{\n"
            f"  \"team_home_possession_pct\": integer 0-100 (must sum to 100 with away),\n"
            f"  \"team_away_possession_pct\": integer 0-100,\n"
            f"  \"team_home_longest_pass_string\": integer (consecutive passes),\n"
            f"  \"team_away_longest_pass_string\": integer,\n"
            f"  \"team_home_total_passes_estimate\": integer,\n"
            f"  \"team_away_total_passes_estimate\": integer,\n"
            "  \"summary\": short string explaining what the stats imply tactically (max 240 chars)\n"
            "}\n\n"
            f"Return ONLY the JSON object, no other text.{roster_context}"
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

    Backward-compatible wrapper around the iter109 split helpers
    (`_parse_markers_response` + `_store_markers`). Used by the single-call
    manual-regenerate path in server.py and the iter99 tests.
    """
    normalized = _parse_markers_response(response, time_offset=0.0)
    return await _store_markers(
        video_id, match_id, user_id, normalized, auto_create_clips_callback
    )


def _parse_markers_response(response: str, time_offset: float = 0.0) -> list:
    """Pure parse: strip code fences, JSON-decode, normalize each event.

    `time_offset` is added to every event's `time` — used by the iter109
    full-coverage chunk flow so per-clip (0-based) timestamps become absolute
    match seconds. Returns a list of normalized marker dicts (NO db ids yet).
    Returns [] on any parse failure instead of raising.
    """
    clean = (response or "").strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
    try:
        markers_data = _json.loads(clean)
    except (ValueError, TypeError):
        return []
    if not isinstance(markers_data, list):
        return []

    normalized = []
    for m in markers_data:
        if not isinstance(m, dict):
            continue
        pn_raw = m.get("player_number")
        try:
            player_number = int(pn_raw) if pn_raw is not None and str(pn_raw).strip() != "" else None
        except (TypeError, ValueError):
            player_number = None
        player_name = m.get("player_name")
        if player_name is not None:
            player_name = str(player_name)[:60].strip() or None
        try:
            t = float(m.get("time", 0)) + time_offset
        except (TypeError, ValueError):
            t = time_offset
        normalized.append({
            "time": max(0.0, t),
            "type": m.get("type", "chance"),
            "label": str(m.get("label", ""))[:100],
            "team": m.get("team", "neutral"),
            "importance": min(5, max(1, int(m.get("importance", 3)) if str(m.get("importance", 3)).strip().isdigit() else 3)),
            "player_number": player_number,
            "player_name": player_name,
        })
    return normalized


def _dedupe_markers(normalized: list, window_sec: float = 7.0) -> list:
    """Merge near-duplicate events (same type within `window_sec`) that arise
    from the small overlap between adjacent full-coverage chunks. Keeps the
    higher-importance copy."""
    out = []
    for m in sorted(normalized, key=lambda x: x["time"]):
        dup = None
        for k in out:
            if k["type"] == m["type"] and abs(k["time"] - m["time"]) < window_sec:
                dup = k
                break
        if dup is None:
            out.append(m)
        elif m["importance"] > dup["importance"]:
            dup.update(m)
    return out


async def _store_markers(
    video_id: str,
    match_id: str,
    user_id: str,
    normalized: list,
    auto_create_clips_callback=None,
) -> int:
    """Replace this video's auto-generated markers with `normalized` (one
    atomic delete + insert pass) and fire the clip-creation callback once."""
    await db.markers.delete_many(
        {"video_id": video_id, "user_id": user_id, "auto_generated": True}
    )
    for n in normalized:
        marker_doc = {
            "id": str(uuid.uuid4()),
            "video_id": video_id,
            "match_id": match_id,
            "user_id": user_id,
            "auto_generated": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **n,
        }
        await db.markers.insert_one(marker_doc)
    logger.info(f"Stored {len(normalized)} AI timeline markers for video {video_id}")
    if auto_create_clips_callback is not None:
        try:
            await auto_create_clips_callback(video_id, user_id, match_id)
        except Exception as e:
            logger.warning(f"auto_create_clips_callback failed: {e}")
    return len(normalized)


_DEFAULT_VIDEO_SYSTEM_MESSAGE = (
    "You are an expert soccer analyst. You will receive the full match "
    "video (compressed). Analyze the entire match and provide detailed "
    "tactical insights, player assessments, highlight identification, "
    "and precise timestamp markers for key events."
)


async def _send_video_to_gemini(
    video_file_path: str,
    prompt: str,
    session_id: str,
    system_message: str = _DEFAULT_VIDEO_SYSTEM_MESSAGE,
) -> str:
    """Send one video + prompt to Gemini and return the raw text response.

    Lazy-imports emergentintegrations so this module loads even when the SDK
    isn't installed (e.g., during regression tests that don't call AI).
    """
    from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType

    chat = LlmChat(
        api_key=_emergent_key(),
        session_id=session_id,
        system_message=system_message,
    ).with_model("gemini", "gemini-3.1-pro-preview")

    video_file = FileContentWithMimeType(file_path=video_file_path, mime_type="video/mp4")
    return await chat.send_message(
        UserMessage(text=prompt, file_contents=[video_file])
    )


async def _send_text_to_gemini(
    prompt: str,
    session_id: str,
    system_message: str = "You are an expert soccer analyst writing a polished match report.",
) -> str:
    """Send a TEXT-ONLY prompt to Gemini (no video). Used by the iter110
    map-reduce 'reduce' step that synthesizes per-segment analysis notes into a
    single cohesive report — cheap since it carries no video tokens."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    chat = LlmChat(
        api_key=_emergent_key(),
        session_id=session_id,
        system_message=system_message,
    ).with_model("gemini", "gemini-3.1-pro-preview")
    return await chat.send_message(UserMessage(text=prompt))


async def run_single_analysis(
    video_id: str,
    user_id: str,
    match_id: str,
    analysis_type: str,
    video_file_path: str,
    prompt: str,
    auto_create_clips_callback=None,
) -> str:
    """Send one analysis prompt to Gemini and persist the result."""
    response = await _send_video_to_gemini(
        video_file_path, prompt, session_id=f"auto-{video_id}-{analysis_type}"
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


# ===========================================================================
# iter109 — Full-match coverage for AI timeline markers.
#
# ROOT CAUSE this replaces: prepare_video_segments_720p sampled only 18 x 45s
# windows (~13 min) out of a 100+ min match for heavy files — so goals outside
# those windows were NEVER shown to Gemini and produced ~1 marker for a whole
# match. The fix: transcode the ENTIRE match to a low-res / low-fps proxy and
# feed it to Gemini in contiguous time-chunks (each well under Gemini's ~1h
# per-call video limit), then merge + dedupe the events. Gemini samples video
# at ~1 fps, so a goal's multi-second celebration + center-circle kickoff is
# always captured. Each chunk file is sized like the proven-working payload
# (~40-55 MB) and transcoded in a single streaming pass (-threads 1) so the
# 4 GB production pod stays well under its memory budget.
# ===========================================================================
_FULL_COVERAGE_CHUNK_SECONDS = 1500   # 25 min of match time per Gemini call
_FULL_COVERAGE_SCALE = "scale=-2:360"  # 360p — proven safe (480p segments worked)
_FULL_COVERAGE_FPS = "3"               # Gemini samples ~1fps; 3 gives headroom
_FULL_COVERAGE_CRF = "32"
_FULL_COVERAGE_OVERLAP = 10            # sec of overlap so boundary goals aren't split


def build_timeline_markers_chunk_prompt(
    match: dict, roster_context: str, clip_start_sec: float, clip_end_sec: float
) -> str:
    """Timeline-markers prompt for ONE contiguous clip of the match.

    Timestamps are requested RELATIVE TO THIS CLIP (0-based); the caller adds
    the clip's match-time offset afterwards. This is far more reliable than
    asking the model to do offset arithmetic itself.
    """
    home_color = (match.get("team_home_jersey_color") or "").strip()
    away_color = (match.get("team_away_jersey_color") or "").strip()
    kit_preamble = ""
    if home_color or away_color:
        kit_parts = []
        if home_color:
            kit_parts.append(f"{match['team_home']} (home) wears {home_color}")
        if away_color:
            kit_parts.append(f"{match['team_away']} (away) wears {away_color}")
        kit_preamble = (
            "**TEAM KIT COLORS — use this to disambiguate teams.** "
            + "; ".join(kit_parts) + ".\n\n"
        )

    s_min, s_sec = divmod(int(clip_start_sec), 60)
    e_min, e_sec = divmod(int(clip_end_sec), 60)
    clip_len = int(clip_end_sec - clip_start_sec)

    return (
        f"You are watching a CONTINUOUS portion of a soccer match between "
        f"{match['team_home']} (home) and {match['team_away']} (away).\n\n"
        f"{kit_preamble}"
        f"This clip covers match time {s_min}:{s_sec:02d} to {e_min}:{e_sec:02d}, "
        f"and is {clip_len} seconds long start-to-finish (no cuts — it is one "
        f"unbroken stretch of play).\n\n"
        "**YOUR JOB:** Identify EVERY key event in this clip.\n\n"
        "**GOAL DETECTION — CRITICAL.** Goals are the most important events; do NOT miss them. "
        "Cues that indicate a goal was just scored:\n"
        "  • Ball clearly crosses the goal line into the net\n"
        "  • Net visibly bulges from impact\n"
        "  • Players celebrate (running, jumping, arms raised, group hug)\n"
        "  • The defending goalkeeper retrieves the ball from inside the net\n"
        "  • Play restarts from the CENTER CIRCLE (kickoff after goal)\n"
        "  • A scoreboard overlay shows an updated score\n"
        "If you see ANY of these cues, log a `goal` event with importance 5. "
        "If you see celebrations or a center-circle kickoff but the ball-cross moment itself isn't visible, "
        "STILL log a `goal` — estimate the time from when the celebration started.\n\n"
        "**PLAYER IDENTIFICATION.** If a jersey number is clearly visible, record it in `player_number` "
        "(and `player_name` if it matches the roster below). If the number is too small/blurry to read "
        "confidently, leave `player_number` null and add an appearance hint in `label` — do NOT guess.\n\n"
        "**OUTPUT FORMAT.** Return ONLY a JSON array of event objects. Each object MUST have:\n"
        "  - \"time\": seconds FROM THE START OF THIS CLIP (number, 0 to "
        f"{clip_len}) — NOT absolute match time\n"
        "  - \"type\": one of \"goal\", \"shot\", \"save\", \"foul\", \"card\", \"substitution\", \"tactical\", \"chance\"\n"
        "  - \"label\": short description (max 60 chars)\n"
        f"  - \"team\": \"{match['team_home']}\" or \"{match['team_away']}\" or \"neutral\"\n"
        "  - \"importance\": 1-5 (5 = goal/red card, 4 = clear chance/save, 3 = shot, 2 = foul, 1 = minor)\n"
        "  - \"player_number\": jersey number if visible (integer or null — DO NOT GUESS)\n"
        "  - \"player_name\": exact roster name if identifiable (string or null)\n\n"
        "Be THOROUGH — log every goal, shot, save, key foul and tactical moment you see in this clip. "
        "Coverage > brevity. If nothing notable happens, return an empty array [].\n\n"
        f"Return ONLY the JSON array, no other text.{roster_context}"
    )


async def _assemble_raw_for_coverage(video: dict, raw_path: str) -> None:
    """Write the full source video to `raw_path`, fail-fast on missing chunks.
    Mirrors the assembly used by prepare_video_sample / _720p."""
    if video.get("is_chunked"):
        chunk_paths = video.get("chunk_paths", {})
        chunk_backends = video.get("chunk_backends", {})
        total_chunks = video.get("total_chunks", len(chunk_paths))
        logger.info(f"[full-coverage] Assembling full video from {total_chunks} chunks")
        with open(raw_path, "wb") as f:
            for i in range(total_chunks):
                path = chunk_paths.get(str(i))
                backend = chunk_backends.get(str(i), "storage")
                if not path:
                    raise RuntimeError(f"Chunk {i} of {total_chunks} is missing — re-upload required.")
                if backend in ("filesystem", "persistent_filesystem") and not os.path.exists(path):
                    raise RuntimeError(
                        f"Chunk {i} of {total_chunks} ({backend}) was lost — re-upload required. path={path}"
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
        with open(raw_path, "wb") as f:
            f.write(data)
        del data


def _compute_coverage_windows(duration: float, chunk_seconds: float = None,
                              overlap: float = None) -> list:
    """Split `duration` into contiguous equal-length windows that cover 100%
    of the runtime (no tiny trailing chunk). Each window after the first starts
    `overlap` seconds early so a goal on a boundary isn't split.
    Returns a list of (start_seconds, length_seconds). Pure + unit-testable."""
    import math
    cs = chunk_seconds if chunk_seconds is not None else _FULL_COVERAGE_CHUNK_SECONDS
    ov = overlap if overlap is not None else _FULL_COVERAGE_OVERLAP
    if duration <= 0:
        return []
    n = max(1, math.ceil(duration / cs))
    base = duration / n
    windows = []
    for i in range(n):
        raw_start = i * base
        start = max(0.0, raw_start - (ov if i > 0 else 0))
        end = min(duration, raw_start + base)
        if end - start >= 1:
            windows.append((start, end - start))
    return windows


async def prepare_full_coverage_chunks(video: dict) -> list:
    """Transcode the ENTIRE match into contiguous low-res chunks covering 100%
    of the runtime. Returns a list of (chunk_path, offset_seconds, length_seconds).
    Caller is responsible for deleting each chunk_path."""
    ext = video["original_filename"].split(".")[-1] if "." in video["original_filename"] else "mp4"
    raw_path = tempfile.mktemp(suffix=f".{ext}", dir="/var/video_chunks")
    produced = []
    try:
        await _assemble_raw_for_coverage(video, raw_path)

        probe = await run_in_threadpool(
            subprocess.run,
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", raw_path],
            capture_output=True, text=True, timeout=60,
        )
        duration = 0.0
        if probe.returncode == 0 and probe.stdout.strip():
            try:
                duration = float(probe.stdout.strip())
            except ValueError:
                pass
        if duration <= 0:
            raise Exception("Could not determine video duration")
        logger.info(f"[full-coverage] duration {duration:.0f}s ({duration/60:.1f}min)")

        windows = _compute_coverage_windows(duration)
        n_chunks = len(windows)
        logger.info(
            f"[full-coverage] {n_chunks} chunk(s) at "
            f"{_FULL_COVERAGE_SCALE}/{_FULL_COVERAGE_FPS}fps/crf{_FULL_COVERAGE_CRF}"
        )

        for i, (start, length) in enumerate(windows):
            end = start + length
            chunk_path = tempfile.mktemp(suffix=f"_cov{i}.mp4", dir="/var/video_chunks")
            cmd = [
                "ffmpeg", "-y",
                "-threads", "1",
                "-fflags", "+discardcorrupt",
                "-ss", str(int(start)),
                "-i", raw_path,
                "-t", str(int(length) + 1),
                "-an",  # markers don't need audio — smaller payload + raises Gemini duration ceiling
                "-vf", _FULL_COVERAGE_SCALE,
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", _FULL_COVERAGE_CRF,
                "-r", _FULL_COVERAGE_FPS,
                "-bufsize", "16M",
                "-max_muxing_queue_size", "256",
                "-movflags", "+faststart",
                chunk_path,
            ]
            res = await run_in_threadpool(
                subprocess.run, cmd, capture_output=True, text=True, timeout=600,
            )
            if res.returncode == 0 and os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 1000:
                mb = os.path.getsize(chunk_path) / (1024 * 1024)
                produced.append((chunk_path, start, length))
                logger.info(f"[full-coverage] chunk {i+1}/{n_chunks}: {start:.0f}-{end:.0f}s, {mb:.1f}MB")
            else:
                logger.warning(f"[full-coverage] chunk {i+1} failed at {start:.0f}s: {(res.stderr or '')[-200:]}")
                if os.path.exists(chunk_path):
                    os.unlink(chunk_path)

        if not produced:
            raise Exception("Failed to extract any full-coverage chunks")
        return produced
    finally:
        if os.path.exists(raw_path):
            try:
                os.unlink(raw_path)
                logger.info("[full-coverage] Deleted raw video file")
            except Exception:
                pass


async def run_timeline_markers_full_coverage(
    video: dict,
    match: dict,
    roster_context: str,
    video_id: str,
    user_id: str,
    match_id: str,
    auto_create_clips_callback=None,
) -> int:
    """iter109 — Detect timeline markers across the ENTIRE match.

    Thin wrapper: builds the full-coverage chunks, processes them, and cleans
    them up. Used by the manual markers-only regenerate path. The auto-process
    orchestrator builds chunks ONCE and calls `_markers_from_chunks` directly so
    the (expensive) transcode is shared with the text analyses.
    """
    chunks = await prepare_full_coverage_chunks(video)
    try:
        return await _markers_from_chunks(
            chunks, match, roster_context, video_id, user_id, match_id,
            auto_create_clips_callback,
        )
    finally:
        _cleanup_chunks(chunks)


def _cleanup_chunks(chunks: list) -> None:
    """Best-effort delete of transcoded chunk files (path, offset, length)."""
    for path, _o, _l in chunks or []:
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except Exception:
                pass


async def _markers_from_chunks(
    chunks: list,
    match: dict,
    roster_context: str,
    video_id: str,
    user_id: str,
    match_id: str,
    auto_create_clips_callback=None,
) -> int:
    """Run timeline-marker detection over pre-built chunks (does NOT delete the
    chunk files — the caller owns their lifecycle so they can be shared across
    analysis types). Offsets per-chunk timestamps to absolute match time,
    merges + dedupes, and stores the markers in one atomic pass."""
    all_markers = []
    n = len(chunks)
    system_message = (
        "You are an expert soccer analyst reviewing a continuous portion of a "
        "match. Detect every key event (goals, shots, saves, cards, fouls) and "
        "report precise timestamps relative to the clip you are given."
    )
    for idx, (path, offset, length) in enumerate(chunks):
        try:
            prompt = build_timeline_markers_chunk_prompt(
                match, roster_context, offset, offset + length
            )
            response = await _send_video_to_gemini(
                path, prompt, session_id=f"markers-{video_id}-{idx}",
                system_message=system_message,
            )
            chunk_markers = _parse_markers_response(response, time_offset=offset)
            all_markers.extend(chunk_markers)
            logger.info(
                f"[full-coverage markers] chunk {idx+1}/{n} "
                f"({offset:.0f}-{offset+length:.0f}s): {len(chunk_markers)} events"
            )
        except Exception as e:
            logger.warning(f"[full-coverage markers] chunk {idx+1}/{n} failed: {e}")

    merged = _dedupe_markers(all_markers)
    count = await _store_markers(
        video_id, match_id, user_id, merged, auto_create_clips_callback
    )

    # Persist one timeline_markers analysis doc for UI consistency. Content is
    # the merged event array (same shape parse_and_store_markers consumes).
    await db.analyses.delete_many({
        "video_id": video_id, "user_id": user_id,
        "analysis_type": "timeline_markers",
    })
    await db.analyses.insert_one({
        "id": str(uuid.uuid4()),
        "video_id": video_id,
        "match_id": match_id,
        "user_id": user_id,
        "analysis_type": "timeline_markers",
        "content": _json.dumps(merged),
        "status": "completed",
        "auto_generated": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(
        f"[full-coverage markers] video {video_id}: {count} merged events "
        f"from {n} chunk(s)"
    )
    return count


# ===========================================================================
# iter110 — Full-match coverage for the PROSE analyses (tactical, player
# performance, highlights) + possession stats.
#
# ROOT CAUSE this fixes (production 2026-06-04): these four analyses sent the
# ENTIRE match as ONE Gemini call via prepare_video_sample. A 1h43m match is
# ~6,180s of video ≈ 1.6M video tokens at Gemini's 1fps sampling — OVER the
# model input limit — so Gemini rejected the request with
# `400 INVALID_ARGUMENT "Request contains an invalid argument."` and every
# non-marker analysis failed. emergentintegrations exposes no media-resolution
# / fps knob, so (per the verified playbook) the only fix is to chunk the
# video into sub-limit segments and make multiple calls.
#
# We reuse iter109's `prepare_full_coverage_chunks` (25-min, 360p/3fps/no-audio
# chunks ≈ 387K tokens/call — safely under the limit) and run each prose prompt
# per chunk (MAP), then synthesize the per-segment notes into one cohesive
# report with a cheap TEXT-ONLY call (REDUCE). possession_stats is reduced by
# deterministic numeric aggregation instead (no extra LLM call).
# ===========================================================================
_PROSE_TYPE_LABELS = {
    "tactical": "tactical",
    "player_performance": "player performance",
    "highlights": "match highlights",
}


def _fmt_mmss(sec: float) -> str:
    m, s = divmod(int(max(0, sec)), 60)
    return f"{m}:{s:02d}"


def _aggregate_possession(partials: list, match: dict) -> str:
    """Combine per-segment possession_stats JSON objects into one match-level
    JSON string. Possession % = duration-weighted average (normalized to 100);
    total passes = sum; longest pass string = max. Deterministic, no LLM."""
    total_len = 0.0
    home_acc = away_acc = 0.0
    home_passes = away_passes = 0
    home_longest = away_longest = 0
    summaries = []
    parsed_any = False
    for offset, length, resp in partials:
        clean = (resp or "").strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            clean = clean.strip()
        try:
            d = _json.loads(clean)
        except (ValueError, TypeError):
            continue
        if not isinstance(d, dict):
            continue
        parsed_any = True
        w = max(1.0, float(length))
        try:
            hp = float(d.get("team_home_possession_pct", 50) or 50)
            ap = float(d.get("team_away_possession_pct", 50) or 50)
        except (TypeError, ValueError):
            hp, ap = 50.0, 50.0
        home_acc += hp * w
        away_acc += ap * w
        total_len += w

        def _int(v):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return 0
        home_passes += _int(d.get("team_home_total_passes_estimate", 0))
        away_passes += _int(d.get("team_away_total_passes_estimate", 0))
        home_longest = max(home_longest, _int(d.get("team_home_longest_pass_string", 0)))
        away_longest = max(away_longest, _int(d.get("team_away_longest_pass_string", 0)))
        s = d.get("summary")
        if s:
            summaries.append(str(s))

    if not parsed_any:
        # Could not parse any segment — hand back the first raw response so the
        # frontend card can attempt its own parse rather than showing nothing.
        return partials[0][2] if partials else "{}"

    h = home_acc / total_len if total_len else 50.0
    a = away_acc / total_len if total_len else 50.0
    tot = h + a
    if tot > 0:
        h = round(h / tot * 100)
        a = 100 - h
    else:
        h, a = 50, 50
    summary = summaries[0] if summaries else (
        f"{match['team_home']} held {int(h)}% possession across the full match."
    )
    return _json.dumps({
        "team_home_possession_pct": int(h),
        "team_away_possession_pct": int(a),
        "team_home_longest_pass_string": home_longest,
        "team_away_longest_pass_string": away_longest,
        "team_home_total_passes_estimate": home_passes,
        "team_away_total_passes_estimate": away_passes,
        "summary": summary[:240],
    })


def _segment_note(analysis_type: str, idx: int, n: int, offset: float, length: float) -> str:
    """Preamble injected before the base prompt for each chunk so Gemini knows
    it's analyzing ONE segment of a longer match."""
    rng = f"{_fmt_mmss(offset)}\u2013{_fmt_mmss(offset + length)}"
    note = (
        f"**IMPORTANT: This video is ONE continuous segment of a longer match "
        f"\u2014 segment {idx + 1} of {n}, covering match time {rng}. Analyze ONLY "
        f"what you can observe in THIS segment; your notes will be combined with "
        f"the other segments afterward.**\n\n"
    )
    if analysis_type == "possession_stats":
        note += (
            "Report possession % and pass stats for THIS SEGMENT ONLY. Do NOT "
            "scale up to the full match \u2014 give the numbers for just this "
            "segment; we combine the segments ourselves.\n\n"
        )
    return note


async def run_chunked_text_analysis(
    chunks: list,
    match: dict,
    analysis_type: str,
    base_prompt: str,
    video_id: str,
    user_id: str,
    match_id: str,
    analysis_id: str = None,
) -> str:
    """iter110 — Run a prose/stat analysis across ALL match chunks (map) then
    synthesize one cohesive result (reduce). Stores ONE completed analysis doc
    (delete-prior + insert) and returns its content. Does NOT delete the chunk
    files \u2014 the caller owns their lifecycle (shared across analysis types)."""
    n = len(chunks)
    partials = []
    for idx, (path, offset, length) in enumerate(chunks):
        prompt = _segment_note(analysis_type, idx, n, offset, length) + base_prompt
        try:
            resp = await _send_video_to_gemini(
                path, prompt, session_id=f"{analysis_type}-{video_id}-{idx}",
            )
            partials.append((offset, length, resp))
            logger.info(f"[chunked {analysis_type}] chunk {idx+1}/{n}: {len(resp or '')} chars")
        except Exception as e:
            logger.warning(f"[chunked {analysis_type}] chunk {idx+1}/{n} failed: {e}")

    if not partials:
        raise Exception(f"All {n} segment analyses failed for {analysis_type}")

    # ---- REDUCE ----
    if analysis_type == "possession_stats":
        content = _aggregate_possession(partials, match)
    elif len(partials) == 1:
        # Short match (single chunk) — no synthesis needed, saves an LLM call.
        content = partials[0][2]
    else:
        label = _PROSE_TYPE_LABELS.get(analysis_type, "match")
        combined = "\n\n".join(
            f"=== Segment covering {_fmt_mmss(o)}\u2013{_fmt_mmss(o + ln)} ===\n{r}"
            for (o, ln, r) in partials
        )
        reduce_prompt = (
            f"You are an expert soccer analyst. You analyzed a match between "
            f"{match['team_home']} and {match['team_away']} in {len(partials)} "
            f"consecutive segments and wrote the per-segment notes below. "
            f"Synthesize them into a SINGLE cohesive {label} analysis for the WHOLE "
            f"match. Merge duplicate observations, keep a chronological narrative "
            f"where relevant, preserve the section structure of a normal full-match "
            f"analysis, and do NOT refer to 'segments', 'clips', or 'parts' in your "
            f"final output \u2014 write it as one continuous report.\n\n{combined}"
        )
        content = await _send_text_to_gemini(
            reduce_prompt, session_id=f"{analysis_type}-{video_id}-reduce",
        )

    await db.analyses.delete_many({
        "video_id": video_id, "user_id": user_id, "analysis_type": analysis_type,
    })
    await db.analyses.insert_one({
        "id": analysis_id or str(uuid.uuid4()),
        "video_id": video_id,
        "match_id": match_id,
        "user_id": user_id,
        "analysis_type": analysis_type,
        "content": content,
        "status": "completed",
        "auto_generated": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    logger.info(
        f"[chunked {analysis_type}] video {video_id}: stored from "
        f"{len(partials)}/{n} segment(s)"
    )
    return content



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
    all_types = ["tactical", "player_performance", "highlights", "timeline_markers", "possession_stats"]
    analysis_types = only_types if only_types else all_types
    chunks = None

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

        # iter110 — ALL analysis types now run on the SHARED full-coverage chunk
        # set (25-min, 360p/3fps/no-audio). This fixes the production Gemini
        # "400 INVALID_ARGUMENT" caused by sending a 1h43m match as a single call
        # (the prose analyses used to do this via prepare_video_sample), and
        # removes the redundant second full-match transcode — markers + the four
        # prose/stat analyses now reuse ONE transcode pass.
        try:
            chunks = await prepare_full_coverage_chunks(video)
        except Exception as e:
            # prepare_full_coverage_chunks raises user-facing exceptions with
            # actionable copy (re-upload required, etc.). Pass them through.
            msg = str(e).strip() or "Video preparation failed"
            logger.error(f"Auto-processing: failed to prepare coverage chunks: {msg}")
            await db.videos.update_one(
                {"id": video_id},
                {"$set": {"processing_status": "failed", "processing_error": msg[:500]}},
            )
            return

        prompts = build_analysis_prompts(match, roster_context, "")

        for idx, analysis_type in enumerate(analysis_types):
            progress = int((idx / len(analysis_types)) * 100)
            await db.videos.update_one(
                {"id": video_id},
                {"$set": {"processing_progress": progress, "processing_current": analysis_type}},
            )
            logger.info(f"Auto-processing {video_id}: {analysis_type} ({progress}%)")

            try:
                if analysis_type == "timeline_markers":
                    # iter109/110 — analyze the ENTIRE match in contiguous chunks
                    # so no goal is missed (root-cause fix for "1 highlight" bug).
                    await _markers_from_chunks(
                        chunks, match, roster_context, video_id, user_id,
                        video["match_id"], auto_create_clips_callback,
                    )
                else:
                    # iter110 — prose/stat analyses run per-chunk + reduce.
                    await run_chunked_text_analysis(
                        chunks, match, analysis_type, prompts[analysis_type],
                        video_id, user_id, video["match_id"],
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
        _cleanup_chunks(chunks)
