"""Player management routes with profile pic upload"""
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
from services.storage import put_object_sync, get_object_sync, init_storage

router = APIRouter()


class PlayerCreate(BaseModel):
    match_id: Optional[str] = None
    team_id: Optional[str] = None
    name: str
    number: Optional[int] = None
    position: Optional[str] = None
    team: Optional[str] = None

class CsvImport(BaseModel):
    match_id: Optional[str] = None
    team_id: Optional[str] = None
    csv_data: str
    team: Optional[str] = None


@router.post("/players")
async def create_player(input: PlayerCreate, current_user: dict = Depends(get_current_user)):
    player = Player(
        user_id=current_user["id"],
        match_id=input.match_id,
        team_id=input.team_id,
        name=input.name,
        number=input.number,
        position=input.position,
        team=input.team
    )
    await db.players.insert_one(player.model_dump())
    return player.model_dump()


@router.get("/players/match/{match_id}")
async def get_match_players(match_id: str, current_user: dict = Depends(get_current_user)):
    players = await db.players.find({"match_id": match_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(200)
    return players


@router.get("/players/team/{team_id}")
async def get_team_players(team_id: str, current_user: dict = Depends(get_current_user)):
    players = await db.players.find({"team_id": team_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(200)
    return players


@router.delete("/players/{player_id}")
async def delete_player(player_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.players.delete_one({"id": player_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Player not found")
    return {"status": "deleted"}


@router.post("/players/import-csv")
async def import_csv(input: CsvImport, current_user: dict = Depends(get_current_user)):
    """Import players from CSV data. Columns: name,number,position"""
    reader = csv.DictReader(io.StringIO(input.csv_data))
    imported = 0
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
            team_id=input.team_id,
            name=name,
            number=number,
            position=position,
            team=input.team
        )
        await db.players.insert_one(player.model_dump())
        imported += 1
    return {"imported": imported}


@router.post("/players/{player_id}/profile-pic")
async def upload_profile_pic(player_id: str, file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Upload a player's profile picture"""
    player = await db.players.find_one({"id": player_id, "user_id": current_user["id"]}, {"_id": 0})
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

    # Store a URL that the frontend can use
    pic_url = f"/api/players/{player_id}/profile-pic/view"
    await db.players.update_one(
        {"id": player_id},
        {"$set": {"profile_pic_url": pic_url, "profile_pic_path": storage_path}}
    )
    return {"url": pic_url}


@router.get("/players/{player_id}/profile-pic/view")
async def view_profile_pic(player_id: str):
    """Serve a player's profile picture (public)"""
    player = await db.players.find_one({"id": player_id}, {"_id": 0, "profile_pic_path": 1})
    if not player or not player.get("profile_pic_path"):
        raise HTTPException(status_code=404, detail="No profile picture")
    try:
        data, content_type = await run_in_threadpool(get_object_sync, player["profile_pic_path"])
        from fastapi.responses import Response
        return Response(content=data, media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")


@router.patch("/players/{player_id}")
async def update_player(player_id: str, name: Optional[str] = None, number: Optional[int] = None,
                        position: Optional[str] = None, team: Optional[str] = None,
                        team_id: Optional[str] = None, match_id: Optional[str] = None,
                        current_user: dict = Depends(get_current_user)):
    player = await db.players.find_one({"id": player_id, "user_id": current_user["id"]}, {"_id": 0})
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
    if team_id is not None:
        updates["team_id"] = team_id
    if match_id is not None:
        updates["match_id"] = match_id
    if updates:
        await db.players.update_one({"id": player_id}, {"$set": updates})
    return {"status": "updated"}
