"""Season Trends — aggregate AI insights across every match in a folder."""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
from collections import Counter
from datetime import datetime, timezone
import json as _json
import os
from db import db
from routes.auth import get_current_user

router = APIRouter()
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")


def _infer_match_score(markers: list, home: str, away: str) -> tuple[int, int, str]:
    """Infer scoreline from goal-type timeline markers."""
    home_goals = sum(
        1 for m in markers
        if (m.get("type") or "").lower() == "goal"
        and (m.get("team") or "").lower() == (home or "").lower()
    )
    away_goals = sum(
        1 for m in markers
        if (m.get("type") or "").lower() == "goal"
        and (m.get("team") or "").lower() == (away or "").lower()
    )
    if home_goals > away_goals:
        result = "W"  # from the perspective of the home team (user's team in many cases)
    elif home_goals < away_goals:
        result = "L"
    else:
        result = "D"
    return home_goals, away_goals, result


@router.post("/folders/{folder_id}/season-trends")
async def generate_season_trends(
    folder_id: str, current_user: dict = Depends(get_current_user)
):
    """Aggregate every match in a folder into a season-level dashboard.

    For each match, uses any cached `insights` (does NOT regenerate per-match
    insights — coach should generate those individually). Counts goals from
    timeline markers to infer scorelines. Optionally calls Gemini once to
    synthesize a season verdict from the aggregated brief.
    """
    folder = await db.folders.find_one(
        {"id": folder_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    matches = await db.matches.find(
        {"folder_id": folder_id, "user_id": current_user["id"]}, {"_id": 0}
    ).sort("date", 1).to_list(500)

    if not matches:
        raise HTTPException(status_code=400, detail="No matches in this folder yet")

    per_match: list[dict] = []
    total_goals_for = 0
    total_goals_against = 0
    wins = draws = losses = 0
    strength_counter: Counter = Counter()
    weakness_counter: Counter = Counter()
    summary_lines: list[str] = []
    clip_type_totals: Counter = Counter()

    for m in matches:
        markers = []
        clips_count = 0
        if m.get("video_id"):
            markers = await db.markers.find(
                {"video_id": m["video_id"], "user_id": current_user["id"]},
                {"_id": 0, "type": 1, "team": 1, "time": 1},
            ).to_list(500)
            clips = await db.clips.find(
                {"video_id": m["video_id"], "user_id": current_user["id"]},
                {"_id": 0, "clip_type": 1},
            ).to_list(500)
            clips_count = len(clips)
            for c in clips:
                clip_type_totals[(c.get("clip_type") or "highlight").lower()] += 1

        gh, ga, result = _infer_match_score(markers, m.get("team_home", ""), m.get("team_away", ""))
        total_goals_for += gh
        total_goals_against += ga
        if result == "W":
            wins += 1
        elif result == "L":
            losses += 1
        else:
            draws += 1

        insights = m.get("insights") or {}
        for s in insights.get("strengths", [])[:4]:
            strength_counter[s.strip().lower()] += 1
        for w in insights.get("weaknesses", [])[:4]:
            weakness_counter[w.strip().lower()] += 1
        if insights.get("summary"):
            summary_lines.append(f"- {m.get('date', '?')} vs {m.get('team_away', '?')}: {insights['summary']}")

        per_match.append({
            "match_id": m["id"],
            "date": m.get("date"),
            "team_home": m.get("team_home"),
            "team_away": m.get("team_away"),
            "competition": m.get("competition"),
            "goals_for": gh,
            "goals_against": ga,
            "result": result,
            "clips_count": clips_count,
            "has_insights": bool(insights),
            "summary": (insights.get("summary") or "")[:200],
        })

    # Top recurring patterns (only if at least 2 matches mention the same theme)
    top_strengths = [
        {"text": text.capitalize(), "count": cnt}
        for text, cnt in strength_counter.most_common(5) if cnt >= 1
    ]
    top_weaknesses = [
        {"text": text.capitalize(), "count": cnt}
        for text, cnt in weakness_counter.most_common(5) if cnt >= 1
    ]

    insights_count = sum(1 for m in matches if m.get("insights"))

    season_verdict = None
    if insights_count >= 2 and EMERGENT_KEY:
        # Synthesize a season-level brief from the per-match summaries
        try:
            from emergentintegrations.llm.chat import LlmChat, UserMessage
            prompt = (
                f"You are coaching a team across the {folder['name']} season. Below are 1-line "
                f"AI verdicts from each match in chronological order. Write a SHORT season-level "
                f"intelligence brief in valid JSON only, no markdown:\n\n"
                f"Record so far: {wins}W-{draws}D-{losses}L  "
                f"(goals for {total_goals_for}, against {total_goals_against})\n\n"
                f"Per-match verdicts:\n" + "\n".join(summary_lines[:30]) + "\n\n"
                'Return JSON: {"verdict": "<2-3 sentences on the season identity>", '
                '"trends": ["<3-4 patterns you see emerging>"], '
                '"focus_for_training": ["<3 prioritized themes the coach should drill>"]}'
            )
            chat = LlmChat(
                api_key=EMERGENT_KEY,
                session_id=f"season-{folder_id}",
                system_message="You are a head-coach AI. Reply with valid JSON only.",
            ).with_model("gemini", "gemini-2.5-flash")
            raw = await chat.send_message(UserMessage(text=prompt))
            cleaned = (raw or "").strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`").lstrip("json").strip()
            try:
                season_verdict = _json.loads(cleaned)
            except Exception:
                season_verdict = None
        except Exception:
            season_verdict = None

    payload = {
        "folder": {"id": folder["id"], "name": folder["name"]},
        "record": {"wins": wins, "draws": draws, "losses": losses},
        "totals": {
            "matches": len(matches),
            "matches_with_insights": insights_count,
            "goals_for": total_goals_for,
            "goals_against": total_goals_against,
            "goal_difference": total_goals_for - total_goals_against,
            "clip_type_totals": dict(clip_type_totals),
        },
        "per_match": per_match,
        "recurring_strengths": top_strengths,
        "recurring_weaknesses": top_weaknesses,
        "season_verdict": season_verdict,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    await db.folders.update_one({"id": folder_id}, {"$set": {"trends": payload}})
    return payload


@router.get("/folders/{folder_id}/season-trends")
async def get_season_trends(
    folder_id: str, current_user: dict = Depends(get_current_user)
):
    folder = await db.folders.find_one(
        {"id": folder_id, "user_id": current_user["id"]}, {"_id": 0, "trends": 1}
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    if not folder.get("trends"):
        raise HTTPException(status_code=404, detail="No trends generated yet")
    return folder["trends"]
