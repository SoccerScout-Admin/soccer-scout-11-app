"""Match CRUD + recently-deleted-videos lookup."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import uuid
import os
from db import db
from routes.auth import get_current_user

router = APIRouter()


class Match(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    team_home: str
    team_away: str
    date: str
    competition: str = ""
    folder_id: Optional[str] = None
    video_id: Optional[str] = None
    has_manual_result: bool = False
    manual_result: Optional[dict] = None
    insights: Optional[dict] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class MatchCreate(BaseModel):
    team_home: str
    team_away: str
    date: str
    competition: str = ""
    folder_id: Optional[str] = None


@router.post("/matches", response_model=Match)
async def create_match(input: MatchCreate, current_user: dict = Depends(get_current_user)):
    match_obj = Match(user_id=current_user["id"], **input.model_dump())
    await db.matches.insert_one(match_obj.model_dump())
    return match_obj


@router.get("/matches", response_model=List[Match])
async def get_matches(current_user: dict = Depends(get_current_user)):
    matches = await db.matches.find(
        {"user_id": current_user["id"]}, {"_id": 0}
    ).to_list(1000)
    for match in matches:
        if match.get("video_id"):
            video = await db.videos.find_one(
                {"id": match["video_id"]},
                {"_id": 0, "processing_status": 1, "processing_progress": 1},
            )
            if video:
                match["processing_status"] = video.get("processing_status", "none")
                match["processing_progress"] = video.get("processing_progress", 0)
    return matches

@router.get("/matches/{match_id}", response_model=Match)
async def get_match(match_id: str, current_user: dict = Depends(get_current_user)):
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match


@router.patch("/matches/{match_id}")
async def update_match(
    match_id: str, updates: dict, current_user: dict = Depends(get_current_user)
):
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    allowed = {"folder_id", "team_home", "team_away", "date", "competition"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if filtered:
        await db.matches.update_one({"id": match_id}, {"$set": filtered})
    return {"status": "updated"}


async def _cascade_delete_reels_for_match(match_id: str, user_id: str) -> None:
    """Delete all highlight reels (+ disk mp4s + view rows) for a match.

    Reels are owned by the match author, so we cascade them on match delete to
    avoid orphaned mp4 files in `/var/video_chunks/reels/` and dangling view
    rows that would otherwise leak into the trending feed.
    """
    reels = await db.highlight_reels.find(
        {"match_id": match_id, "user_id": user_id},
        {"_id": 0, "id": 1, "output_path": 1},
    ).to_list(100)
    if not reels:
        return
    reel_ids = [r["id"] for r in reels]
    for r in reels:
        out = r.get("output_path")
        if out and os.path.exists(out):
            try:
                os.unlink(out)
            except OSError:
                pass
    await db.highlight_reels.delete_many({"id": {"$in": reel_ids}})
    await db.highlight_reel_views.delete_many({"reel_id": {"$in": reel_ids}})



@router.delete("/matches/{match_id}")
async def delete_match(
    match_id: str, current_user: dict = Depends(get_current_user)
):
    """Delete a single match and cascade-delete its derived data.

    Same semantics as bulk-delete: hard-delete clips/analyses/markers for the
    match's video, soft-delete the video so the 24h restore window applies,
    then remove the match document itself.
    """
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]},
        {"_id": 0, "id": 1, "video_id": 1},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    video_id = match.get("video_id")
    if video_id:
        await db.clips.delete_many(
            {"video_id": video_id, "user_id": current_user["id"]}
        )
        await db.analyses.delete_many(
            {"video_id": video_id, "user_id": current_user["id"]}
        )
        await db.markers.delete_many(
            {"video_id": video_id, "user_id": current_user["id"]}
        )
        await db.videos.update_one(
            {"id": video_id, "user_id": current_user["id"]},
            {"$set": {
                "is_deleted": True,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    # Cascade-delete highlight reels (mp4 files + view rows). Done here, not
    # gated on `video_id`, because a coach could regenerate reels later and we
    # still want to scrub anything stale.
    await _cascade_delete_reels_for_match(match_id, current_user["id"])

    await db.matches.delete_one({"id": match_id})
    return {"status": "deleted", "id": match_id}


@router.get("/matches/{match_id}/deleted-videos")
async def list_deleted_videos(
    match_id: str, current_user: dict = Depends(get_current_user)
):
    """Recently deleted videos for a match (24h restore window)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return await db.videos.find(
        {
            "match_id": match_id,
            "user_id": current_user["id"],
            "is_deleted": True,
            "deleted_at": {"$gte": cutoff},
        },
        {"_id": 0, "chunk_paths": 0, "chunk_sizes": 0, "chunk_backends": 0},
    ).sort("deleted_at", -1).to_list(20)


class ImportTeamRosterRequest(BaseModel):
    team_id: str


@router.post("/matches/{match_id}/import-team-roster")
async def import_team_roster_to_match(
    match_id: str,
    body: ImportTeamRosterRequest,
    current_user: dict = Depends(get_current_user),
):
    """Copy every player on `team_id` into this match's roster.

    Creates fresh player documents with `match_id={match_id}` and
    `team_ids=[team_id]`. The original team roster is untouched — we duplicate
    rather than mutate so the team can be re-used across multiple matches in a
    season without entanglement.

    No-op safe: if some of these players have already been imported (same
    name+number+team_id combo), they're skipped. Returns counts so the UI can
    show "imported 14 of 18 players (4 skipped — already on this match)".

    Wired into the Create Match → Roster step UX. See user feedback 2026-05-13
    where coaches said "I should be able to pull my existing team roster into
    a match instead of building it from scratch every game."
    """
    user_id = current_user["id"]

    match = await db.matches.find_one({"id": match_id, "user_id": user_id}, {"_id": 0, "id": 1})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    team = await db.teams.find_one({"id": body.team_id, "user_id": user_id}, {"_id": 0, "id": 1, "name": 1})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    source_players = await db.players.find(
        {"team_ids": body.team_id, "user_id": user_id},
        {"_id": 0, "profile_pic_path": 0, "share_token": 0, "id": 0, "created_at": 0, "match_id": 0},
    ).to_list(200)

    if not source_players:
        return {"imported": 0, "skipped": 0, "team_name": team["name"]}

    # Build a quick lookup of players already on this match (by name+number
    # which is the usual natural key) so re-runs are idempotent.
    existing = await db.players.find(
        {"match_id": match_id, "user_id": user_id},
        {"_id": 0, "name": 1, "number": 1},
    ).to_list(200)
    existing_keys = {(p.get("name", "").strip().lower(), p.get("number")) for p in existing}

    imported = 0
    skipped = 0
    new_docs = []
    for sp in source_players:
        # Only consider players who are PURE team members (no match_id) — skip
        # match-bound copies that may have been imported elsewhere. This keeps
        # the source roster clean of fan-out duplicates.
        if sp.get("match_id"):
            continue
        key = (sp.get("name", "").strip().lower(), sp.get("number"))
        if key in existing_keys:
            skipped += 1
            continue
        sp["id"] = str(uuid.uuid4())
        sp["user_id"] = user_id
        sp["match_id"] = match_id
        # Match-bound copies are snapshots — they do NOT carry team_ids back.
        # The team roster stays authoritative; the match roster is a frozen
        # point-in-time picture for tactical attribution. If the team adds a
        # player tomorrow, today's match roster doesn't grow retroactively.
        sp["team_ids"] = []
        sp["created_at"] = datetime.now(timezone.utc).isoformat()
        new_docs.append(sp)
        imported += 1

    if new_docs:
        await db.players.insert_many(new_docs)

    return {"imported": imported, "skipped": skipped, "team_name": team["name"]}


@router.get("/matches/{match_id}/roster-status")
async def get_match_roster_status(
    match_id: str, current_user: dict = Depends(get_current_user)
):
    """Lightweight check used by the upload flow + video page banner to decide
    whether AI analysis should auto-start or wait for the coach to add a
    roster first. Single count query — kept separate from `/players/match/{id}`
    so polling is cheap."""
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]}, {"_id": 0, "id": 1}
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    count = await db.players.count_documents(
        {"match_id": match_id, "user_id": current_user["id"]}
    )
    return {"player_count": count, "has_roster": count > 0}




class ManualKeyEvent(BaseModel):
    type: str  # 'goal', 'shot', 'save', 'foul', 'card', 'sub', 'note'
    minute: int = 0
    team: str = ""  # must match team_home or team_away
    player_id: Optional[str] = None
    description: str = ""


class ManualResult(BaseModel):
    home_score: int = Field(ge=0, le=99)
    away_score: int = Field(ge=0, le=99)
    key_events: List[ManualKeyEvent] = Field(default_factory=list, max_length=60)
    notes: str = Field(default="", max_length=2000)


@router.put("/matches/{match_id}/manual-result")
async def save_manual_result(
    match_id: str,
    body: ManualResult,
    current_user: dict = Depends(get_current_user),
):
    """Record the outcome of a match that has no video uploaded.

    Counts toward Season Trends (W/D/L, GF/GA) just like video-derived results.
    Safe to call multiple times — replaces previous manual result.
    """
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]}, {"_id": 0, "id": 1, "team_home": 1, "team_away": 1},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    payload = body.model_dump()
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload["updated_by"] = current_user["id"]
    # Compute derived outcome from the home team's perspective so downstream
    # aggregations don't have to recompute.
    payload["outcome"] = (
        "W" if body.home_score > body.away_score
        else "L" if body.home_score < body.away_score
        else "D"
    )
    await db.matches.update_one(
        {"id": match_id},
        {"$set": {"manual_result": payload, "has_manual_result": True}},
    )
    return {"status": "saved", "manual_result": payload}


@router.delete("/matches/{match_id}/manual-result")
async def delete_manual_result(
    match_id: str, current_user: dict = Depends(get_current_user)
):
    """Remove a manual result (e.g. once video is uploaded and processed)."""
    res = await db.matches.update_one(
        {"id": match_id, "user_id": current_user["id"]},
        {"$unset": {"manual_result": "", "has_manual_result": ""}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Match not found")
    return {"status": "deleted"}


@router.get("/matches/{match_id}/manual-result")
async def get_manual_result(
    match_id: str, current_user: dict = Depends(get_current_user)
):
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]},
        {"_id": 0, "id": 1, "manual_result": 1},
    )
    if match is None:
        raise HTTPException(status_code=404, detail="Match not found")
    return match.get("manual_result") or {}


# ===== Finish Match — locks scoreline + auto-generates AI recap =====


class FinishMatchResponse(BaseModel):
    status: str = "finished"
    summary: str
    is_locked: bool = True
    finished_at: str


def _build_match_recap_prompt(match: dict) -> str:
    """Compact, fact-rich prompt the LLM can turn into a 1-paragraph narrative."""
    mr = match.get("manual_result") or {}
    home, away = match.get("team_home", "Home"), match.get("team_away", "Away")
    hs, as_ = mr.get("home_score", 0), mr.get("away_score", 0)
    outcome = mr.get("outcome") or ("W" if hs > as_ else "L" if hs < as_ else "D")
    competition = match.get("competition") or "Friendly"
    notes = (mr.get("notes") or "").strip()
    events = mr.get("events") or []

    event_lines = []
    for e in events:
        minute = e.get("minute") or 0
        team = e.get("team") or "—"
        kind = (e.get("type") or "event").title()
        desc = (e.get("description") or "").strip()
        line = f"  • {minute}' — {team}: {kind}"
        if desc:
            line += f" ({desc})"
        event_lines.append(line)

    return (
        f"Match: {home} vs {away}\n"
        f"Final score: {hs}-{as_} ({outcome} for {home})\n"
        f"Competition: {competition}\n"
        f"Date: {match.get('date', 'unknown')}\n"
        f"Events ({len(events)}):\n" + ("\n".join(event_lines) if event_lines else "  (none recorded)")
        + (f"\nCoach's notes:\n{notes}" if notes else "")
    )


async def _generate_match_recap(match: dict) -> Optional[str]:
    """Run a 1-paragraph recap through Gemini via Emergent LLM key.
    Returns None if the LLM isn't configured or generation fails — the caller
    falls back to a deterministic plain-English summary so Finish Match still works."""
    import os
    import logging
    logger = logging.getLogger(__name__)
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        return None
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=key,
            session_id=f"finish-match-{match['id']}",
            system_message=(
                "You are a sports broadcaster writing a single-paragraph match recap "
                "(80–120 words) for a youth/amateur soccer coach. "
                "Lead with the result, integrate goal scorers and key moments in chronological order, "
                "end with one tactical takeaway the coach can use in their next session. "
                "Plain text only — no markdown, no headers, no lists, no quotes."
            ),
        ).with_model("gemini", "gemini-2.5-flash")
        msg = UserMessage(text=_build_match_recap_prompt(match))
        text = (await chat.send_message(msg)).strip()
        # Strip any accidental code-fences or quotes
        import re
        text = re.sub(r"^```(?:text)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
        text = text.strip("\"'\u201c\u201d\u2018\u2019").strip()
        return text or None
    except Exception as e:
        logger.warning("[finish-match] Gemini recap failed: %s — using deterministic fallback", str(e)[:160])
        return None


def _deterministic_recap(match: dict) -> str:
    """Plain-English fallback when LLM isn't available or fails."""
    mr = match.get("manual_result") or {}
    home, away = match.get("team_home", "Home"), match.get("team_away", "Away")
    hs, as_ = mr.get("home_score", 0), mr.get("away_score", 0)
    outcome = mr.get("outcome") or ("W" if hs > as_ else "L" if hs < as_ else "D")
    competition = match.get("competition") or "Friendly"
    events = mr.get("events") or []
    goals = [e for e in events if (e.get("type") or "").lower() == "goal"]

    if outcome == "W":
        verb = "took the win"
    elif outcome == "L":
        verb = "fell"
    else:
        verb = "drew"

    intro = f"{home} {verb} {hs}-{as_} against {away} in {competition}."
    if goals:
        goal_summary = ", ".join(
            f"{g.get('minute', '?')}' {g.get('team', '—')}" for g in goals[:6]
        )
        intro += f" Goal timeline: {goal_summary}."
    if mr.get("notes"):
        intro += f" Coach's note: {mr['notes'][:160]}"
    return intro


@router.post("/matches/{match_id}/finish", response_model=FinishMatchResponse)
async def finish_match(
    match_id: str, current_user: dict = Depends(get_current_user),
):
    """Lock the scoreline + events and auto-generate a 1-paragraph AI recap.

    Preconditions:
      - Match must have a `manual_result` (i.e. POST /manual-result first).
      - Cannot be called twice (manual_result.is_final blocks it).

    Side effects:
      - Sets manual_result.is_final = True and finished_at = now.
      - Generates a recap via Gemini and stores it in match.insights.summary
        (matching the spoken_summary contract so existing UI surfaces it).
      - Falls back to a deterministic plain-English recap if Gemini is unavailable.
    """
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    mr = match.get("manual_result") or {}
    if not mr:
        raise HTTPException(status_code=400, detail="Add a manual result first (score + events) before finishing")
    if mr.get("is_final"):
        raise HTTPException(status_code=409, detail="Match already finished — unlock from the form to edit")

    summary = await _generate_match_recap(match)
    summary_source = "ai_recap"
    if not summary:
        summary = _deterministic_recap(match)
        summary_source = "deterministic_recap"

    finished_at = datetime.now(timezone.utc).isoformat()
    mr["is_final"] = True
    mr["finished_at"] = finished_at

    insights = match.get("insights") or {}
    insights["summary"] = summary
    insights["summary_source"] = summary_source
    insights["summary_generated_at"] = finished_at

    await db.matches.update_one(
        {"id": match_id},
        {"$set": {"manual_result": mr, "has_manual_result": True, "insights": insights}},
    )
    return FinishMatchResponse(
        status="finished", summary=summary, is_locked=True, finished_at=finished_at
    )


@router.post("/matches/{match_id}/unlock")
async def unlock_match(
    match_id: str, current_user: dict = Depends(get_current_user),
):
    """Clear is_final so the coach can edit again. Keeps the AI recap."""
    res = await db.matches.update_one(
        {"id": match_id, "user_id": current_user["id"]},
        {"$unset": {"manual_result.is_final": "", "manual_result.finished_at": ""}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Match not found")
    return {"status": "unlocked"}


@router.post("/matches/{match_id}/share-recap")
async def share_recap(
    match_id: str, current_user: dict = Depends(get_current_user),
):
    """Generate (or revoke) a shareable token for the AI match recap.

    Idempotent: calling twice toggles the share. The token unlocks
    `GET /api/og/match-recap/{token}` and its image variant for crawler unfurls
    (WhatsApp/Slack/Twitter) and a public web view.
    """
    import secrets
    match = await db.matches.find_one(
        {"id": match_id, "user_id": current_user["id"]}, {"_id": 0},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    if not (match.get("insights") or {}).get("summary"):
        raise HTTPException(
            status_code=400,
            detail="No AI recap to share — finish the match first to generate one.",
        )

    existing_token = (match.get("manual_result") or {}).get("recap_share_token")
    if existing_token:
        # Revoke
        await db.matches.update_one(
            {"id": match_id},
            {"$unset": {"manual_result.recap_share_token": ""}},
        )
        return {"status": "revoked"}

    token = secrets.token_urlsafe(16)
    await db.matches.update_one(
        {"id": match_id},
        {"$set": {"manual_result.recap_share_token": token}},
    )
    return {"status": "shared", "share_token": token}


# ===== Bulk match operations =====


class BulkMatchAction(BaseModel):
    match_ids: List[str] = Field(min_length=1, max_length=200)
    folder_id: Optional[str] = None  # for "move" action
    competition: Optional[str] = None  # for "set_competition" action


@router.post("/matches/bulk/move")
async def bulk_move_matches(
    body: BulkMatchAction, current_user: dict = Depends(get_current_user)
):
    """Move selected matches into a folder (or to root if folder_id is null)."""
    if body.folder_id:
        folder = await db.folders.find_one(
            {"id": body.folder_id, "user_id": current_user["id"]}, {"_id": 0}
        )
        if not folder:
            raise HTTPException(status_code=404, detail="Target folder not found")
    res = await db.matches.update_many(
        {"id": {"$in": body.match_ids}, "user_id": current_user["id"]},
        {"$set": {"folder_id": body.folder_id}},
    )
    return {"status": "moved", "count": res.modified_count}


@router.post("/matches/bulk/competition")
async def bulk_set_competition(
    body: BulkMatchAction, current_user: dict = Depends(get_current_user)
):
    """Set the same competition value across multiple matches."""
    if body.competition is None:
        raise HTTPException(status_code=400, detail="competition is required")
    res = await db.matches.update_many(
        {"id": {"$in": body.match_ids}, "user_id": current_user["id"]},
        {"$set": {"competition": body.competition}},
    )
    return {"status": "updated", "count": res.modified_count}


@router.post("/matches/bulk/delete")
async def bulk_delete_matches(
    body: BulkMatchAction, current_user: dict = Depends(get_current_user)
):
    """Delete multiple matches and cascade-delete their derived data.

    For each match, also: hard-delete clips/analyses/markers tied to the match's
    video, and unlink any folder references. The video file itself is left
    soft-deleted (not purged) so the same 24h restore window applies.
    """
    matches = await db.matches.find(
        {"id": {"$in": body.match_ids}, "user_id": current_user["id"]},
        {"_id": 0, "id": 1, "video_id": 1},
    ).to_list(500)

    video_ids = [m["video_id"] for m in matches if m.get("video_id")]
    deleted_count = 0
    for m in matches:
        # Cascade derived data
        if m.get("video_id"):
            await db.clips.delete_many(
                {"video_id": m["video_id"], "user_id": current_user["id"]}
            )
            await db.analyses.delete_many(
                {"video_id": m["video_id"], "user_id": current_user["id"]}
            )
            await db.markers.delete_many(
                {"video_id": m["video_id"], "user_id": current_user["id"]}
            )
        # Cascade-delete highlight reels for this match (mp4 files + view rows)
        await _cascade_delete_reels_for_match(m["id"], current_user["id"])
        await db.matches.delete_one({"id": m["id"]})
        deleted_count += 1

    # Soft-delete associated videos so the 24h restore window still applies if
    # the user changes their mind. Permanent purge happens via the sweeper.
    if video_ids:
        await db.videos.update_many(
            {"id": {"$in": video_ids}, "user_id": current_user["id"]},
            {"$set": {
                "is_deleted": True,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
            }},
        )

    return {"status": "deleted", "count": deleted_count}
