"""Team management routes"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import uuid
from datetime import datetime, timezone
from db import db
from models import Team
from routes.auth import get_current_user

router = APIRouter()


class TeamCreate:
    def __init__(self, name: str, season: str, club: Optional[str] = None):
        self.name = name
        self.season = season
        self.club = club

class TeamUpdate:
    def __init__(self, name: Optional[str] = None, season: Optional[str] = None, club: Optional[str] = None):
        self.name = name
        self.season = season
        self.club = club


@router.post("/teams")
async def create_team(name: str, season: str, club: Optional[str] = None, current_user: dict = Depends(get_current_user)):
    team = Team(user_id=current_user["id"], name=name, season=season, club=club)
    await db.teams.insert_one(team.model_dump())
    result = team.model_dump()
    return result


@router.get("/teams")
async def get_teams(current_user: dict = Depends(get_current_user)):
    teams = await db.teams.find({"user_id": current_user["id"]}, {"_id": 0}).to_list(100)
    return teams


@router.get("/teams/{team_id}")
async def get_team(team_id: str, current_user: dict = Depends(get_current_user)):
    team = await db.teams.find_one({"id": team_id, "user_id": current_user["id"]}, {"_id": 0})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    # Include player count
    player_count = await db.players.count_documents({"team_id": team_id, "user_id": current_user["id"]})
    team["player_count"] = player_count
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
    # Unlink players from this team (don't delete them)
    await db.players.update_many({"team_id": team_id}, {"$set": {"team_id": None}})
    return {"status": "deleted"}


@router.get("/teams/{team_id}/players")
async def get_team_players(team_id: str, current_user: dict = Depends(get_current_user)):
    """Get all players registered to a specific team"""
    players = await db.players.find({"team_id": team_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(200)
    return players
