"""Match Insights — Gemini-synthesised post-game report.

Pulls timeline markers + clips + roster + score for a single match, asks
Gemini 2.5 Flash to produce structured coaching insights, returns JSON.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import json as _json
import os
from datetime import datetime, timezone
from db import db
from routes.auth import get_current_user

router = APIRouter()

EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")


class MatchInsights(BaseModel):
    summary: str
    coaching_points: list[str]
    strengths: list[str]
    weaknesses: list[str]
    key_moments: list[dict]  # [{"time": float, "description": "...", "type": "..."}]
    score_context: Optional[str] = None
    generated_at: str
    model: str = "gemini-2.5-flash"


async def _load_match_signal(match_id: str, user_id: str) -> dict:
    """Pull the match record + timeline markers + clips + roster in parallel
    Mongo calls. Raises HTTPException(404) if match missing,
    HTTPException(400) if there's no video / no AI signal yet.

    Extracted from generate_match_insights() so that function stays under the
    CC=10 / 50-line / 15-locals targets."""
    match = await db.matches.find_one(
        {"id": match_id, "user_id": user_id}, {"_id": 0}
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if not match.get("video_id"):
        raise HTTPException(
            status_code=400, detail="Match has no video — upload one first"
        )

    markers = await db.markers.find(
        {"video_id": match["video_id"], "user_id": user_id},
        {"_id": 0, "time": 1, "type": 1, "description": 1, "team": 1, "importance": 1},
    ).sort("time", 1).to_list(500)

    clips = await db.clips.find(
        {"video_id": match["video_id"], "user_id": user_id},
        {"_id": 0, "title": 1, "clip_type": 1, "start_time": 1, "end_time": 1, "player_ids": 1},
    ).to_list(500)

    roster = await db.players.find(
        {"user_id": user_id, "match_id": match_id},
        {"_id": 0, "id": 1, "name": 1, "number": 1, "position": 1},
    ).to_list(200)

    if not markers and not clips:
        raise HTTPException(
            status_code=400,
            detail="No timeline markers or clips yet — process the video for AI analysis first.",
        )

    return {"match": match, "markers": markers, "clips": clips, "roster": roster}


def _format_marker_lines(markers: list) -> list[str]:
    """Compact one-line representation of timeline markers for the prompt."""
    return [
        f"  - {m.get('time', 0):.0f}s [{(m.get('type') or '?').upper()}] "
        f"{(m.get('team') or '?')}: {m.get('description', '')[:140]}"
        for m in markers[:80]
    ]


def _summarize_clip_types(clips: list) -> str:
    """Build a short '3 highlight, 2 goal' style summary string from clips."""
    counts: dict[str, int] = {}
    for c in clips:
        t = (c.get("clip_type") or "highlight").lower()
        counts[t] = counts.get(t, 0) + 1
    return ", ".join(f"{n} {t}" for t, n in counts.items()) or "none"


def _build_insights_prompt(signal: dict) -> str:
    """Compose the Gemini prompt from the loaded signal. Pure function so it
    can be unit-tested without hitting Mongo or the LLM."""
    match = signal["match"]
    markers = signal["markers"]

    home = match.get("team_home", "Home")
    away = match.get("team_away", "Away")
    competition = match.get("competition") or "League"
    date = match.get("date") or "?"
    marker_lines = _format_marker_lines(markers)
    clip_summary = _summarize_clip_types(signal["clips"])

    return f"""You are a senior soccer coach producing a post-game intelligence brief for a youth team coach.

Match: {home} vs {away}  ({competition}, {date})
Roster size: {len(signal["roster"])} players
Clip totals: {clip_summary}

Timeline markers ({len(markers)} total, showing first 80):
{chr(10).join(marker_lines) if marker_lines else "  (none)"}

Produce a JSON object with these exact keys (and nothing else, no markdown):
{{
  "summary": "1-2 sentence verdict on the match",
  "coaching_points": ["3 to 5 short, actionable coaching takeaways for next training"],
  "strengths": ["2-3 things the team did well"],
  "weaknesses": ["2-3 areas to work on"],
  "key_moments": [
    {{"time": <seconds>, "description": "<short>", "type": "<goal|chance|save|foul|other>"}},
    ... 3 to 6 of the most pivotal moments based on the timeline
  ],
  "score_context": "<optional 1-line score-narrative inferred from goals/markers, or null>"
}}

Be specific. Reference actual minute marks ("around 47'") when possible. Keep tone constructive."""


async def _call_gemini_insights(prompt: str, match_id: str) -> dict:
    """Call Gemini 2.5 Flash with the insights prompt, parse the JSON, and
    return a clean dict. Raises HTTPException on LLM key issues or bad JSON."""
    if not EMERGENT_KEY:
        raise HTTPException(status_code=500, detail="LLM key not configured")

    # Lazy-import so this module doesn't crash if emergentintegrations isn't installed
    from emergentintegrations.llm.chat import LlmChat, UserMessage

    chat = LlmChat(
        api_key=EMERGENT_KEY,
        session_id=f"insights-{match_id}",
        system_message="You are a sports vision assistant. Reply with valid JSON only.",
    ).with_model("gemini", "gemini-2.5-flash")

    response = await chat.send_message(UserMessage(text=prompt))
    raw_text = response if isinstance(response, str) else str(response)
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").lstrip("json").strip()

    try:
        return _json.loads(cleaned)
    except Exception:
        raise HTTPException(
            status_code=502,
            detail=f"AI returned an invalid response. Try regenerating. (debug: {cleaned[:120]})",
        )


def _shape_insights_response(parsed: dict) -> dict:
    """Trim/clamp the LLM output to safe sizes and add bookkeeping fields."""
    return {
        "summary": parsed.get("summary", "")[:600],
        "coaching_points": parsed.get("coaching_points", [])[:6],
        "strengths": parsed.get("strengths", [])[:4],
        "weaknesses": parsed.get("weaknesses", [])[:4],
        "key_moments": parsed.get("key_moments", [])[:8],
        "score_context": parsed.get("score_context"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "gemini-2.5-flash",
    }


@router.post("/matches/{match_id}/insights")
async def generate_match_insights(
    match_id: str, current_user: dict = Depends(get_current_user)
):
    """Generate (or refresh) AI coaching insights for a match.

    Cached on the match document — re-call to refresh.

    Refactored iter66 — extracted _load_match_signal, _build_insights_prompt,
    _call_gemini_insights, _shape_insights_response so this endpoint stays
    under CC=10 / 50-line / 15-locals targets."""
    signal = await _load_match_signal(match_id, current_user["id"])
    prompt = _build_insights_prompt(signal)
    parsed = await _call_gemini_insights(prompt, match_id)
    insights = _shape_insights_response(parsed)

    # Cache on the match document so refresh doesn't re-bill the LLM
    await db.matches.update_one(
        {"id": match_id}, {"$set": {"insights": insights}}
    )
    return insights


@router.get("/matches/{match_id}/insights")
async def get_match_insights(
    match_id: str, current_user: dict = Depends(get_current_user)
):
    """Return cached insights or 404 if never generated."""
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]},
        {"_id": 0, "insights": 1},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if not match.get("insights"):
        raise HTTPException(
            status_code=404, detail="No insights yet — generate them first via POST"
        )
    return match["insights"]
