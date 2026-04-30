"""Scouting packet PDF endpoint.

Admin/owner-gated endpoint that assembles a scouting packet for a given
player and streams back a PDF. Coach provides an optional `coach_notes` string
as query param or JSON body.

Call pattern:
    POST /api/scouting-packets/player/{player_id}
    { "coach_notes": "optional 1-3 paragraph recommendation" }

Response: application/pdf with `Content-Disposition: attachment`.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from db import db
from routes.auth import get_current_user
from services.scouting_packet import render_scouting_packet
from services.storage import get_object_sync

router = APIRouter()
logger = logging.getLogger(__name__)


class ScoutingPacketRequest(BaseModel):
    coach_notes: Optional[str] = Field(default="", max_length=3000)


def _require_admin(user: dict) -> None:
    role = (user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(
            status_code=403,
            detail="Scouting packets are an admin/owner feature. Ask an admin to generate one.",
        )


async def _assemble_packet(player_id: str, current_user: dict, coach_notes: str, request: Request) -> dict:
    """Gather everything needed to render the PDF."""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    # All matches the player appears in
    team_ids = [player.get("team_id")] if player.get("team_id") else []
    matches = []
    if team_ids:
        matches = await db.matches.find(
            {"user_id": current_user["id"], "$or": [
                {"team_id": {"$in": team_ids}},
                {"team_home_id": {"$in": team_ids}},
                {"team_away_id": {"$in": team_ids}},
            ]},
            {"_id": 0},
        ).sort("date", 1).to_list(50)

    # Clips tagged to this player (newest first)
    clips = await db.clips.find(
        {"user_id": current_user["id"], "player_ids": player_id},
        {"_id": 0},
    ).sort("created_at", -1).to_list(60)

    # Club crest
    club = None
    crest_bytes = None
    if player.get("team_id"):
        team = await db.teams.find_one({"id": player["team_id"]}, {"_id": 0, "club": 1})
        if team and team.get("club"):
            club = await db.clubs.find_one(
                {"id": team["club"]}, {"_id": 0, "id": 1, "name": 1, "logo_path": 1},
            )
            if club and club.get("logo_path"):
                try:
                    crest_bytes, _ = await run_in_threadpool(get_object_sync, club["logo_path"])
                except Exception as e:
                    logger.info("crest fetch failed: %s", e)

    # Teams summary (for cover)
    team_docs = []
    if player.get("team_id"):
        t = await db.teams.find_one(
            {"id": player["team_id"]}, {"_id": 0, "name": 1, "age_group": 1},
        )
        if t:
            team_docs.append(t)

    # Aggregate per-match performance
    per_match = []
    goals_total, assists_total = 0, 0
    for m in matches:
        goals = 0
        assists = 0
        # Try manual-result key events first (authoritative when entered)
        manual = m.get("manual_result") or {}
        for ev in manual.get("key_events", []):
            if ev.get("player_id") == player_id:
                if (ev.get("type") or "").lower() == "goal":
                    goals += 1
                elif (ev.get("type") or "").lower() == "assist":
                    assists += 1
        if goals == 0 and assists == 0:
            # Fall back to clip counts: any clip tagged for this player of type goal counts as a goal
            mc = [c for c in clips if c.get("match_id") == m.get("id")]
            goals = sum(1 for c in mc if (c.get("clip_type") or "").lower() == "goal")
            assists = sum(1 for c in mc if (c.get("clip_type") or "").lower() == "assist")

        goals_total += goals
        assists_total += assists
        result = None
        if manual.get("outcome"):
            result = manual["outcome"]
        else:
            # Infer from clip markers: too fragile, default to draw for unknown
            result = "D"
        per_match.append({
            "match_id": m.get("id"),
            "opponent": m.get("team_away") if m.get("team_home") == (team_docs[0].get("name") if team_docs else None) else m.get("team_home") or m.get("team_away"),
            "goals": goals,
            "assists": assists,
            "result": result,
            "date": m.get("date"),
        })

    # Compute stats
    minutes_est = len(matches) * 70  # rough — until per-match minute tracking is added
    stats = {
        "matches": len(matches),
        "goals": goals_total,
        "assists": assists_total,
        "minutes": minutes_est,
    }

    # Pull strengths/weaknesses from insights on the latest match (AI output)
    strengths, weaknesses, verdict = [], [], None
    if matches:
        # Combine across all matches, dedup
        strength_set, weakness_set = [], []
        for m in matches[-10:]:
            ins = m.get("insights") or {}
            for s in (ins.get("strengths") or [])[:3]:
                if s and s not in strength_set:
                    strength_set.append(s)
            for w in (ins.get("weaknesses") or [])[:3]:
                if w and w not in weakness_set:
                    weakness_set.append(w)
        strengths = strength_set[:6]
        weaknesses = weakness_set[:6]
        latest_ins = matches[-1].get("insights") or {}
        verdict = latest_ins.get("summary")

    # Clip rows for PDF
    clip_rows = []
    for c in clips[:30]:
        dur = max(0, float(c.get("end_time") or 0) - float(c.get("start_time") or 0))
        dur_label = f"{int(dur // 60)}:{int(dur % 60):02d}" if dur else ""
        match_label = ""
        for m in matches:
            if m.get("id") == c.get("match_id"):
                match_label = f"{m.get('team_home', '?')} vs {m.get('team_away', '?')}"
                break
        clip_rows.append({
            "title": c.get("title") or "Clip",
            "share_token": c.get("share_token"),
            "clip_type": (c.get("clip_type") or "highlight"),
            "match_label": match_label,
            "duration_label": dur_label,
        })

    # Build public base URL for QR codes
    base_url = os.environ.get("PUBLIC_APP_URL", "").rstrip("/")
    if not base_url:
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
        if host:
            base_url = f"https://{host}"

    return {
        "player": {
            "id": player.get("id"),
            "name": player.get("name") or "",
            "number": player.get("number"),
            "position": player.get("position") or "",
        },
        "club": club or {},
        "club_crest_bytes": crest_bytes,
        "season": matches[-1].get("date", "")[:4] + "-" + str(int(matches[-1].get("date", "0000")[:4]) + 1)[-2:] if matches else "",
        "coach_name": current_user.get("name") or current_user.get("email", ""),
        "generated_at_label": datetime.now(timezone.utc).strftime("%B %d, %Y"),
        "teams_summary": ", ".join(t.get("name", "") for t in team_docs),
        "stats": stats,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "verdict": verdict,
        "per_match": per_match,
        "clips": clip_rows,
        "coach_notes": (coach_notes or "").strip(),
        "public_base_url": base_url,
    }


@router.post("/scouting-packets/player/{player_id}")
async def generate_player_packet(
    player_id: str,
    body: ScoutingPacketRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Admin/owner-gated. Returns a branded PDF scouting packet for the given
    player. Coaches can supply optional free-text recommendation via body.
    """
    _require_admin(current_user)
    packet = await _assemble_packet(player_id, current_user, body.coach_notes or "", request)
    try:
        pdf_bytes = await run_in_threadpool(render_scouting_packet, packet)
    except Exception as e:
        logger.error("scouting packet render failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to generate PDF: {e}")

    filename = f"scouting-packet-{packet['player']['name'].replace(' ', '-').lower() or 'player'}.pdf"
    # Persist an audit record so admins can see who generated what (non-blocking)
    try:
        await db.scouting_packets.insert_one({
            "id": f"sp-{player_id}-{int(datetime.now(timezone.utc).timestamp())}",
            "user_id": current_user["id"],
            "player_id": player_id,
            "size_bytes": len(pdf_bytes),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.info("scouting packet audit write failed: %s", e)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Packet-Size": str(len(pdf_bytes)),
        },
    )


@router.get("/scouting-packets/player/{player_id}/preview")
async def preview_packet_metadata(
    player_id: str, request: Request, current_user: dict = Depends(get_current_user)
):
    """Admin/owner-gated. Returns the packet payload (JSON, without binary crest)
    so the frontend can show a preview before triggering the PDF download.
    """
    _require_admin(current_user)
    packet = await _assemble_packet(player_id, current_user, "", request)
    # Strip the binary crest from the preview payload
    packet.pop("club_crest_bytes", None)
    return packet
