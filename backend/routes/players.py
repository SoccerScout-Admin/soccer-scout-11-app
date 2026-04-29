"""Player management routes with multi-team support (max 2 teams per season)."""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from typing import Optional, List
from pydantic import BaseModel
import uuid
import csv
import io
from datetime import datetime, timezone
from starlette.concurrency import run_in_threadpool
from db import db, APP_NAME
from models import Player
from routes.auth import get_current_user
from services.storage import put_object_sync, get_object_sync

router = APIRouter()

MAX_TEAMS_PER_SEASON = 2


class PlayerCreate(BaseModel):
    match_id: Optional[str] = None
    # Accept either single team_id (legacy) or team_ids array. Both end up in team_ids.
    team_id: Optional[str] = None
    team_ids: Optional[List[str]] = None
    name: str
    number: Optional[int] = None
    position: Optional[str] = None
    team: Optional[str] = None


class CsvImport(BaseModel):
    match_id: Optional[str] = None
    team_id: Optional[str] = None
    csv_data: str
    team: Optional[str] = None


async def _enforce_season_cap(user_id: str, player_id: Optional[str], team_ids: List[str]) -> None:
    """Ensure no season has more than MAX_TEAMS_PER_SEASON entries for this player."""
    if not team_ids:
        return
    teams = await db.teams.find(
        {"id": {"$in": team_ids}, "user_id": user_id},
        {"_id": 0, "id": 1, "season": 1, "name": 1},
    ).to_list(50)

    by_season: dict[str, list[str]] = {}
    for t in teams:
        by_season.setdefault(t["season"], []).append(t["name"])

    for season, names in by_season.items():
        if len(names) > MAX_TEAMS_PER_SEASON:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Player can be on at most {MAX_TEAMS_PER_SEASON} teams in season "
                    f"{season} (got {len(names)}: {', '.join(names)})."
                ),
            )


def _strip_storage_fields(p: dict) -> dict:
    """Remove internal storage paths before returning to clients."""
    out = {k: v for k, v in p.items() if k != "profile_pic_path"}
    return out


@router.post("/players")
async def create_player(input: PlayerCreate, current_user: dict = Depends(get_current_user)):
    team_ids: List[str] = []
    if input.team_ids:
        team_ids = list(input.team_ids)
    elif input.team_id:
        team_ids = [input.team_id]

    await _enforce_season_cap(current_user["id"], None, team_ids)

    player = Player(
        user_id=current_user["id"],
        match_id=input.match_id,
        team_ids=team_ids,
        name=input.name,
        number=input.number,
        position=input.position,
        team=input.team,
    )
    await db.players.insert_one(player.model_dump())
    return player.model_dump()


@router.get("/players/match/{match_id}")
async def get_match_players(match_id: str, current_user: dict = Depends(get_current_user)):
    players = await db.players.find(
        {"match_id": match_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(200)
    return [_strip_storage_fields(p) for p in players]


@router.get("/players/team/{team_id}")
async def get_team_players(team_id: str, current_user: dict = Depends(get_current_user)):
    players = await db.players.find(
        {"team_ids": team_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(200)
    return [_strip_storage_fields(p) for p in players]


@router.delete("/players/{player_id}")
async def delete_player(player_id: str, current_user: dict = Depends(get_current_user)):
    """Hard-delete a player record entirely."""
    result = await db.players.delete_one({"id": player_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Player not found")
    return {"status": "deleted"}


@router.post("/players/{player_id}/teams/{team_id}")
async def add_player_to_team(
    player_id: str, team_id: str, current_user: dict = Depends(get_current_user)
):
    """Add an existing player to an additional team (respects 2-per-season cap)."""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    team = await db.teams.find_one(
        {"id": team_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    current_teams = list(player.get("team_ids") or [])
    if team_id in current_teams:
        return {"status": "already-on-team", "team_ids": current_teams}

    proposed = current_teams + [team_id]
    await _enforce_season_cap(current_user["id"], player_id, proposed)

    await db.players.update_one(
        {"id": player_id}, {"$set": {"team_ids": proposed}}
    )
    return {"status": "added", "team_ids": proposed}


@router.delete("/players/{player_id}/teams/{team_id}")
async def remove_player_from_team(
    player_id: str, team_id: str, current_user: dict = Depends(get_current_user)
):
    """Remove a player from a single team (player record stays if other teams remain)."""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    current_teams = list(player.get("team_ids") or [])
    if team_id not in current_teams:
        return {"status": "not-on-team"}
    new_teams = [t for t in current_teams if t != team_id]
    await db.players.update_one(
        {"id": player_id}, {"$set": {"team_ids": new_teams}}
    )
    return {"status": "removed", "team_ids": new_teams}


@router.post("/players/import-csv")
async def import_csv(input: CsvImport, current_user: dict = Depends(get_current_user)):
    """Import players from CSV data. Columns: name,number,position"""
    reader = csv.DictReader(io.StringIO(input.csv_data))
    imported = 0
    target_team_ids = [input.team_id] if input.team_id else []
    for row in reader:
        name = row.get("name", "").strip()
        if not name:
            continue
        number = None
        try:
            number = int(row.get("number", "").strip())
        except (ValueError, AttributeError):
            pass
        position = row.get("position", "").strip() or None
        player = Player(
            user_id=current_user["id"],
            match_id=input.match_id,
            team_ids=list(target_team_ids),
            name=name,
            number=number,
            position=position,
            team=input.team,
        )
        await db.players.insert_one(player.model_dump())
        imported += 1
    return {"imported": imported}


@router.post("/players/{player_id}/profile-pic")
async def upload_profile_pic(
    player_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    """Upload a player's profile picture"""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 5MB)")

    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    storage_path = f"{APP_NAME}/players/{current_user['id']}/{player_id}.{ext}"

    await run_in_threadpool(put_object_sync, storage_path, data, file.content_type)

    pic_url = f"/api/players/{player_id}/profile-pic/view"
    await db.players.update_one(
        {"id": player_id},
        {"$set": {"profile_pic_url": pic_url, "profile_pic_path": storage_path}},
    )
    return {"url": pic_url}


@router.get("/players/{player_id}/profile-pic/view")
async def view_profile_pic(player_id: str):
    """Serve a player's profile picture (public)"""
    player = await db.players.find_one(
        {"id": player_id}, {"_id": 0, "profile_pic_path": 1}
    )
    if not player or not player.get("profile_pic_path"):
        raise HTTPException(status_code=404, detail="No profile picture")
    try:
        data, content_type = await run_in_threadpool(
            get_object_sync, player["profile_pic_path"]
        )
        from fastapi.responses import Response
        return Response(content=data, media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")


@router.patch("/players/{player_id}")
async def update_player(
    player_id: str,
    name: Optional[str] = None,
    number: Optional[int] = None,
    position: Optional[str] = None,
    team: Optional[str] = None,
    match_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    updates = {}
    if name is not None:
        updates["name"] = name
    if number is not None:
        updates["number"] = number
    if position is not None:
        updates["position"] = position
    if team is not None:
        updates["team"] = team
    if match_id is not None:
        updates["match_id"] = match_id
    if updates:
        await db.players.update_one({"id": player_id}, {"$set": updates})
    return {"status": "updated"}


# ===== Roster discovery for "Add Existing Player" flow =====

@router.get("/teams/{team_id}/eligible-players")
async def eligible_players_for_team(
    team_id: str, current_user: dict = Depends(get_current_user)
):
    """Players who are NOT yet on this team, but are on another team in the same
    season. They're eligible to be added (subject to the 2-per-season cap)."""
    team = await db.teams.find_one(
        {"id": team_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    same_season_teams = await db.teams.find(
        {"user_id": current_user["id"], "season": team["season"], "id": {"$ne": team_id}},
        {"_id": 0, "id": 1, "name": 1},
    ).to_list(100)
    other_team_ids = [t["id"] for t in same_season_teams]
    if not other_team_ids:
        return []

    candidates = await db.players.find(
        {"user_id": current_user["id"], "team_ids": {"$in": other_team_ids}},
        {"_id": 0, "profile_pic_path": 0},
    ).to_list(500)

    team_name_by_id = {t["id"]: t["name"] for t in same_season_teams}
    out = []
    for p in candidates:
        p_team_ids = list(p.get("team_ids") or [])
        if team_id in p_team_ids:
            continue  # already on the target team
        # Annotate which other teams this player is on (for UI context)
        other_names = [
            team_name_by_id[tid] for tid in p_team_ids if tid in team_name_by_id
        ]
        # Block if at the cap (2) - they would exceed if we added them
        at_cap = len(p_team_ids) >= MAX_TEAMS_PER_SEASON
        out.append({**p, "other_team_names": other_names, "at_cap": at_cap})
    return out


# ===== Promote roster to next season =====

class PromoteRosterRequest(BaseModel):
    new_season: str
    new_team_name: Optional[str] = None  # default: same as source team
    keep_old: bool = True  # default: also keep on the old team


@router.post("/teams/{team_id}/promote")
async def promote_team_to_next_season(
    team_id: str,
    body: PromoteRosterRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a new team for next season in the same club and copy the entire
    roster's identity to it. Each player gets the new team appended to their
    `team_ids` so they appear on both rosters by default."""
    src = await db.teams.find_one(
        {"id": team_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not src:
        raise HTTPException(status_code=404, detail="Source team not found")
    if not body.new_season.strip():
        raise HTTPException(status_code=400, detail="new_season is required")
    if body.new_season == src["season"]:
        raise HTTPException(
            status_code=400, detail="new_season must differ from the current season"
        )

    new_team_id = str(uuid.uuid4())
    new_team = {
        "id": new_team_id,
        "user_id": current_user["id"],
        "name": body.new_team_name or src["name"],
        "club": src.get("club"),
        "season": body.new_season.strip(),
        "logo_url": None,
        "share_token": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.teams.insert_one(new_team)

    # Copy players: append new_team_id to each player's team_ids.
    # If keep_old=False, also remove the old team_id.
    roster = await db.players.find(
        {"team_ids": team_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(500)

    promoted = 0
    for p in roster:
        new_ids = list(p.get("team_ids") or [])
        if not body.keep_old and team_id in new_ids:
            new_ids = [t for t in new_ids if t != team_id]
        if new_team_id not in new_ids:
            new_ids.append(new_team_id)
        await db.players.update_one(
            {"id": p["id"]}, {"$set": {"team_ids": new_ids}}
        )
        promoted += 1

    return {
        "status": "promoted",
        "new_team_id": new_team_id,
        "promoted_count": promoted,
        "new_team": {k: v for k, v in new_team.items() if k != "_id"},
    }
