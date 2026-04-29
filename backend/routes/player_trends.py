"""Player Season Trends — per-player season dashboard with team-need analysis
and recruiter-grade evaluation."""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
from collections import Counter
from datetime import datetime, timezone
import json as _json
import os
from db import db
from routes.auth import get_current_user

router = APIRouter()
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")


# Position-specific recruiter rubric — what D1 college and pro scouts evaluate
# Sourced from US Soccer Development Academy / NCAA D1 / pro academy scout guides.
POSITION_RUBRICS = {
    "goalkeeper": {
        "label": "Goalkeeper",
        "key_attributes": [
            "Shot stopping (reflexes + footwork)",
            "Command of the box (crosses + corners)",
            "Distribution (short + long, both feet)",
            "Sweeper-keeper instincts (line height, recovery)",
            "Communication & defensive organization",
        ],
        "recruiter_focus": (
            "College and pro scouts at the GK position prioritize SHOT-STOPPING reflex, "
            "ABILITY TO COMMAND THE PENALTY AREA on crosses, DISTRIBUTION quality "
            "(especially playing out from the back under pressure), and HEIGHT/PRESENCE. "
            "By age 17, D1 schools want consistent ball-playing GKs comfortable under high press."
        ),
    },
    "defender": {
        "label": "Defender (CB / FB)",
        "key_attributes": [
            "1v1 defending (positioning + body shape)",
            "Aerial duels (timing + spring)",
            "Ball-playing under pressure (line breaks)",
            "Recovery pace (sprint + acceleration)",
            "Crossing / overlap quality (FBs)",
        ],
        "recruiter_focus": (
            "Modern D1 and pro academy scouts demand BALL-PLAYING defenders who can "
            "break lines with progressive passes, plus elite RECOVERY PACE. CBs need "
            "dominance in AERIAL DUELS and 1v1 defending. FBs need OVERLAPPING ENDURANCE, "
            "QUALITY CROSSING, and the engine to defend deep. Composure under high press "
            "is non-negotiable at the next level."
        ),
    },
    "midfielder": {
        "label": "Midfielder",
        "key_attributes": [
            "Ball progression (line breaks + switches)",
            "Vision & decision-making under pressure",
            "Defensive work rate (recoveries + screening)",
            "Press resistance (first touch + body shape)",
            "Stamina & recovery runs",
        ],
        "recruiter_focus": (
            "The most coveted profile at college / pro level is the BOX-TO-BOX midfielder "
            "with ELITE PRESS RESISTANCE, NUMBERS-UP RECEIVING, and a high RECOVERY/PRESSING "
            "engine. Defensive midfielders are scouted for TACTICAL POSITIONING and "
            "INTERCEPTIONS; attacking mids are scouted for VISION and PROGRESSIVE PASS COMPLETION."
        ),
    },
    "winger": {
        "label": "Winger",
        "key_attributes": [
            "1v1 dribbling (off both feet)",
            "Pace & change of direction",
            "Crossing under pressure",
            "End product (goals + assists)",
            "Defensive work rate (tracking back)",
        ],
        "recruiter_focus": (
            "Scouts at the next level want wingers who BEAT THEIR DEFENDER 1v1 consistently, "
            "have ELITE PACE off both feet, and produce CROSSING/SHOOTING END PRODUCT. "
            "Inverted wingers need a sharp left-foot/right-foot bias. DEFENSIVE TRACKBACK "
            "is the #1 reason wingers fall out of D1 recruitment."
        ),
    },
    "forward": {
        "label": "Forward / Striker",
        "key_attributes": [
            "Finishing (composure + variety)",
            "Off-ball movement (timing of runs)",
            "Hold-up play (back-to-goal control)",
            "Link play & combination passing",
            "Pressing intensity (first defender)",
        ],
        "recruiter_focus": (
            "Pro and D1 scouts evaluate strikers on FINISHING CONVERSION RATE, "
            "OFF-BALL MOVEMENT INTELLIGENCE (the runs you don't see on TV), HOLD-UP PLAY "
            "physicality, and PRESSING INTENSITY (modern strikers are first defenders). "
            "Goal output matters but the work between goals matters more at the next level."
        ),
    },
}


def _normalize_position(position: str) -> str:
    """Map free-form position strings to one of the rubric keys."""
    if not position:
        return "midfielder"
    p = position.lower().strip()
    if "keeper" in p or p == "gk":
        return "goalkeeper"
    if "defend" in p or p in ("cb", "fb", "lb", "rb", "rwb", "lwb", "back"):
        return "defender"
    if "wing" in p or p in ("lw", "rw"):
        return "winger"
    if "forward" in p or "striker" in p or p in ("st", "cf"):
        return "forward"
    return "midfielder"


@router.post("/players/{player_id}/season-trends")
async def generate_player_season_trends(
    player_id: str,
    team_id: Optional[str] = Query(None, description="Scope to one team's season; defaults to most recent season"),
    current_user: dict = Depends(get_current_user),
):
    """Aggregate every clip tagged with this player_id and produce a season report
    plus a recruiter-grade evaluation scoped to their position."""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]},
        {"_id": 0, "profile_pic_path": 0},
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    # Resolve team context (for season scope + team-need framing)
    team_ids = list(player.get("team_ids") or [])
    if not team_ids:
        raise HTTPException(
            status_code=400,
            detail="Player isn't on any team yet — assign them to a team first.",
        )

    target_team = None
    if team_id and team_id in team_ids:
        target_team = await db.teams.find_one(
            {"id": team_id, "user_id": current_user["id"]}, {"_id": 0}
        )
    if not target_team:
        # Default: most recent season among player's teams
        teams = await db.teams.find(
            {"id": {"$in": team_ids}, "user_id": current_user["id"]}, {"_id": 0}
        ).sort("season", -1).to_list(20)
        if teams:
            target_team = teams[0]
    if not target_team:
        raise HTTPException(status_code=400, detail="Could not resolve team context")

    season = target_team.get("season", "")
    team_name = target_team.get("name", "")

    # Find matches in this team's season — match folder linkage may not exist,
    # so fall back to "all matches with this player on the roster".
    matches = await db.matches.find(
        {"user_id": current_user["id"]},
        {"_id": 0, "id": 1, "team_home": 1, "team_away": 1, "date": 1, "video_id": 1, "competition": 1, "insights": 1},
    ).sort("date", 1).to_list(500)

    # Clips tagged with this player
    player_clips = await db.clips.find(
        {"player_ids": player_id, "user_id": current_user["id"]},
        {"_id": 0},
    ).sort("created_at", 1).to_list(1000)

    # Group clips by match, compute per-match stats
    per_match_clips: dict[str, list] = {}
    for c in player_clips:
        mid = c.get("match_id")
        if mid:
            per_match_clips.setdefault(mid, []).append(c)

    # Aggregate stats by clip type
    stats: Counter = Counter()
    total_seconds = 0.0
    for c in player_clips:
        t = (c.get("clip_type") or "highlight").lower()
        stats[t] += 1
        total_seconds += max(0, (c.get("end_time") or 0) - (c.get("start_time") or 0))

    # Per-match summary
    per_match: list[dict] = []
    for m in matches:
        clips_for_match = per_match_clips.get(m["id"], [])
        if not clips_for_match:
            continue
        match_stats: Counter = Counter()
        for c in clips_for_match:
            match_stats[(c.get("clip_type") or "highlight").lower()] += 1
        per_match.append({
            "match_id": m["id"],
            "date": m.get("date"),
            "team_home": m.get("team_home"),
            "team_away": m.get("team_away"),
            "competition": m.get("competition"),
            "clip_count": len(clips_for_match),
            "by_type": dict(match_stats),
            "match_summary": (m.get("insights", {}) or {}).get("summary", "")[:200],
        })

    if not player_clips:
        raise HTTPException(
            status_code=400,
            detail=(
                "No clips tagged with this player yet. Tag the player on clips during analysis "
                "to unlock season trends and the recruiter evaluation."
            ),
        )

    # Position-specific rubric
    rubric_key = _normalize_position(player.get("position", ""))
    rubric = POSITION_RUBRICS[rubric_key]

    # Build Gemini prompt
    if not EMERGENT_KEY:
        raise HTTPException(status_code=500, detail="LLM key not configured")

    stat_lines = ", ".join(f"{n} {k}" for k, n in stats.most_common())
    per_match_lines = "\n".join(
        f"- {m['date']} {m['team_home']} vs {m['team_away']}: "
        f"{m['clip_count']} clips ({', '.join(f'{n} {k}' for k, n in m['by_type'].items())})"
        for m in per_match[:20]
    )

    prompt = f"""You are a senior soccer scout writing a season report for a single player.

PLAYER:
- Name: {player.get('name')}
- Jersey #: {player.get('number', '?')}
- Position: {player.get('position', 'Unknown')} (rubric category: {rubric['label']})
- Team: {team_name}
- Season: {season}

SEASON ACTIVITY (clips tagged with this player):
- Total clips: {len(player_clips)}
- Stats: {stat_lines}
- Total clip duration: {round(total_seconds, 1)} seconds

PER-MATCH BREAKDOWN:
{per_match_lines if per_match_lines else "(no per-match data)"}

POSITION-SPECIFIC SCOUT RUBRIC ({rubric['label']}):
Key attributes scouts evaluate:
{chr(10).join(f"  - {a}" for a in rubric['key_attributes'])}

What recruiters look for at this position:
{rubric['recruiter_focus']}

YOUR TASK
Produce a JSON object only (no markdown), with these EXACT keys:

{{
  "player_summary": "<2-3 sentence verdict on the player's season>",
  "team_role": {{
    "current_role": "<1 sentence on how they functioned for {team_name} this season>",
    "strengths_for_team": ["<3 bullet points on what they did well in this team's system>"],
    "opportunities_for_team": ["<3 bullet points on where they could grow within this team's needs>"]
  }},
  "recruiter_view": {{
    "estimated_level": "<one of: 'Youth Recreational', 'Youth Competitive', 'High School Varsity', 'College D3/D2', 'College D1', 'Pro Academy'>",
    "scout_score": <number 1-10 reflecting next-level readiness>,
    "scout_score_rationale": "<1-2 sentence justification>",
    "scout_attributes": [
      {{"attribute": "<one of the rubric key attributes>", "rating": <1-10>, "notes": "<short observation tying to the clip data>"}},
      ... one row per rubric attribute (so {len(rubric['key_attributes'])} rows)
    ],
    "where_they_excel": ["<2-3 bullets on standout recruiter traits>"],
    "development_priorities": ["<3 specific, actionable areas this player must improve to reach the next recruitment level>"]
  }},
  "recommended_drills": ["<3-4 specific training drills tailored to development priorities>"]
}}

Be specific. Reference the clip counts in your reasoning. Be honest about ratings — at youth level, a 6-7 is realistic; reserve 8+ for clear standouts. Do NOT inflate scores."""

    from emergentintegrations.llm.chat import LlmChat, UserMessage

    chat = LlmChat(
        api_key=EMERGENT_KEY,
        session_id=f"player-trends-{player_id}-{team_id or 'default'}",
        system_message="You are a top-tier soccer scout. Reply with valid JSON only.",
    ).with_model("gemini", "gemini-2.5-flash")

    raw = await chat.send_message(UserMessage(text=prompt))
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").lstrip("json").strip()
    try:
        parsed = _json.loads(cleaned)
    except Exception:
        raise HTTPException(
            status_code=502,
            detail=f"AI returned invalid JSON. Try regenerating. (debug: {cleaned[:120]})",
        )

    payload = {
        "player": {
            "id": player["id"],
            "name": player.get("name"),
            "number": player.get("number"),
            "position": player.get("position"),
            "profile_pic_url": player.get("profile_pic_url"),
        },
        "team": {"id": target_team["id"], "name": team_name, "season": season},
        "stats": {
            "total_clips": len(player_clips),
            "total_seconds": round(total_seconds, 1),
            "by_type": dict(stats),
        },
        "per_match": per_match,
        "rubric": {"key": rubric_key, "label": rubric["label"], "attributes": rubric["key_attributes"]},
        "report": parsed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Cache on the player document keyed by team_id
    cache_key = f"trends.{target_team['id']}"
    await db.players.update_one(
        {"id": player_id}, {"$set": {cache_key: payload}}
    )
    return payload


@router.get("/players/{player_id}/season-trends")
async def get_player_season_trends(
    player_id: str,
    team_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Return cached player season trends for a given team (or most recent)."""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0, "trends": 1, "team_ids": 1}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    trends = (player.get("trends") or {})
    if team_id:
        cached = trends.get(team_id)
    else:
        # First available cached entry (any team)
        cached = next((v for v in trends.values() if isinstance(v, dict)), None)
    if not cached:
        raise HTTPException(status_code=404, detail="No trends generated yet")
    return cached
