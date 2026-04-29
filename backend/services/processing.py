"""AI processing pipeline helpers.

This module holds the *pure* helpers used by the auto-processing pipeline:
prompt construction, marker parsing, single-analysis runs against Gemini.

The orchestrator `run_auto_processing` and FFmpeg-based video sample
preparation (`prepare_video_sample`, `prepare_video_segments_720p`) remain
in `server.py` because they have deep coupling with global processing state,
the chunked-upload pipeline (`read_chunk_data`), and circuit-breaker logic.
Moving those is a separate refactor with much higher regression risk.
"""
import logging
import json as _json
import uuid
import os
from datetime import datetime, timezone
from db import db

logger = logging.getLogger(__name__)
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")


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
        api_key=EMERGENT_KEY,
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
