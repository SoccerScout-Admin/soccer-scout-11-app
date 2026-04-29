"""Team and Club management routes"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import Response
from typing import Optional
from starlette.concurrency import run_in_threadpool
import uuid
from datetime import datetime, timezone
from db import db, APP_NAME
from models import Team
from routes.auth import get_current_user
from services.storage import put_object_sync, get_object_sync

router = APIRouter()


@router.post("/teams")
async def create_team(name: str, season: str, club: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    team = Team(user_id=current_user["id"], name=name, season=season, club=club)
    data = team.model_dump()
    await db.teams.insert_one(data)
    return {k: v for k, v in data.items() if k != "_id"}


@router.get("/teams")
async def get_teams(current_user: dict = Depends(get_current_user)):
    teams = await db.teams.find({"user_id": current_user["id"]}, {"_id": 0}).to_list(100)
    # Enrich with player count and club info
    for team in teams:
        team["player_count"] = await db.players.count_documents({"team_id": team["id"], "user_id": current_user["id"]})
        if team.get("club"):
            club = await db.clubs.find_one({"id": team["club"], "user_id": current_user["id"]}, {"_id": 0, "name": 1, "logo_url": 1})
            team["club_info"] = club
    return teams


@router.get("/teams/{team_id}")
async def get_team(team_id: str, current_user: dict = Depends(get_current_user)):
    team = await db.teams.find_one({"id": team_id, "user_id": current_user["id"]}, {"_id": 0})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    team["player_count"] = await db.players.count_documents({"team_id": team_id, "user_id": current_user["id"]})
    return team


@router.patch("/teams/{team_id}")
async def update_team(team_id: str, name: Optional[str] = None, season: Optional[str] = None, club: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    team = await db.teams.find_one({"id": team_id, "user_id": current_user["id"]}, {"_id": 0})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    updates = {}
    if name is not None:
        updates["name"] = name
    if season is not None:
        updates["season"] = season
    if club is not None:
        updates["club"] = club
    if updates:
        await db.teams.update_one({"id": team_id}, {"$set": updates})
    return {"status": "updated"}


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str, current_user: dict = Depends(get_current_user)):
    team = await db.teams.find_one({"id": team_id, "user_id": current_user["id"]}, {"_id": 0})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    await db.teams.delete_one({"id": team_id})
    await db.players.update_many({"team_id": team_id}, {"$set": {"team_id": None}})
    return {"status": "deleted"}


@router.get("/teams/{team_id}/players")
async def get_team_players(team_id: str, current_user: dict = Depends(get_current_user)):
    players = await db.players.find({"team_id": team_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(200)
    return players


# ===== Clubs =====

@router.post("/clubs")
async def create_club(name: str, current_user: dict = Depends(get_current_user)):
    club = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "name": name,
        "logo_url": None,
        "logo_path": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.clubs.insert_one(club)
    return {"id": club["id"], "name": club["name"], "logo_url": club["logo_url"], "created_at": club["created_at"]}


@router.get("/clubs")
async def get_clubs(current_user: dict = Depends(get_current_user)):
    clubs = await db.clubs.find({"user_id": current_user["id"]}, {"_id": 0, "logo_path": 0}).to_list(50)
    # Add team count per club
    for club in clubs:
        club["team_count"] = await db.teams.count_documents({"club": club["id"], "user_id": current_user["id"]})
    return clubs


@router.patch("/clubs/{club_id}")
async def update_club(club_id: str, name: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    club = await db.clubs.find_one({"id": club_id, "user_id": current_user["id"]}, {"_id": 0})
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    if name:
        await db.clubs.update_one({"id": club_id}, {"$set": {"name": name}})
    return {"status": "updated"}


@router.delete("/clubs/{club_id}")
async def delete_club(club_id: str, current_user: dict = Depends(get_current_user)):
    club = await db.clubs.find_one({"id": club_id, "user_id": current_user["id"]}, {"_id": 0})
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    await db.clubs.delete_one({"id": club_id})
    # Unlink teams from this club
    await db.teams.update_many({"club": club_id}, {"$set": {"club": None}})
    return {"status": "deleted"}


@router.post("/clubs/{club_id}/logo")
async def upload_club_logo(club_id: str, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Upload a club logo/crest"""
    club = await db.clubs.find_one({"id": club_id, "user_id": current_user["id"]}, {"_id": 0})
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 5MB)")
    ext = file.filename.split(".")[-1] if "." in file.filename else "png"
    storage_path = f"{APP_NAME}/clubs/{current_user['id']}/{club_id}.{ext}"
    await run_in_threadpool(put_object_sync, storage_path, data, file.content_type)
    logo_url = f"/api/clubs/{club_id}/logo/view"
    await db.clubs.update_one({"id": club_id}, {"$set": {"logo_url": logo_url, "logo_path": storage_path}})
    return {"url": logo_url}


@router.get("/clubs/{club_id}/logo/view")
async def view_club_logo(club_id: str):
    """Serve a club logo (public)"""
    club = await db.clubs.find_one({"id": club_id}, {"_id": 0, "logo_path": 1})
    if not club or not club.get("logo_path"):
        raise HTTPException(status_code=404, detail="No logo uploaded")
    try:
        data, content_type = await run_in_threadpool(get_object_sync, club["logo_path"])
        return Response(content=data, media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Logo not found")
