"""Team and Club management routes"""
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Request
from fastapi.responses import Response, HTMLResponse
from typing import Optional
from starlette.concurrency import run_in_threadpool
import html as html_lib
import uuid
from datetime import datetime, timezone
from db import db, APP_NAME
from models import Team
from routes.auth import get_current_user
from services.storage import put_object_sync, get_object_sync
from services.og_card import render_team_card

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
        team["player_count"] = await db.players.count_documents({"team_ids": team["id"], "user_id": current_user["id"]})
        if team.get("club"):
            club = await db.clubs.find_one({"id": team["club"], "user_id": current_user["id"]}, {"_id": 0, "name": 1, "logo_url": 1})
            team["club_info"] = club
    return teams


@router.get("/teams/{team_id}")
async def get_team(team_id: str, current_user: dict = Depends(get_current_user)):
    team = await db.teams.find_one({"id": team_id, "user_id": current_user["id"]}, {"_id": 0})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    team["player_count"] = await db.players.count_documents({"team_ids": team_id, "user_id": current_user["id"]})
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
    # Pull this team_id from any players that referenced it
    await db.players.update_many(
        {"team_ids": team_id, "user_id": current_user["id"]},
        {"$pull": {"team_ids": team_id}},
    )
    return {"status": "deleted"}


@router.get("/teams/{team_id}/players")
async def get_team_players(team_id: str, current_user: dict = Depends(get_current_user)):
    players = await db.players.find(
        {"team_ids": team_id, "user_id": current_user["id"]},
        {"_id": 0, "profile_pic_path": 0},
    ).to_list(200)
    return players


@router.post("/teams/{team_id}/share")
async def toggle_team_share(team_id: str, current_user: dict = Depends(get_current_user)):
    """Toggle public share link for a team's roster page"""
    team = await db.teams.find_one({"id": team_id, "user_id": current_user["id"]}, {"_id": 0})
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.get("share_token"):
        await db.teams.update_one({"id": team_id}, {"$set": {"share_token": None}})
        return {"status": "unshared", "share_token": None}
    token = str(uuid.uuid4())[:12]
    await db.teams.update_one({"id": team_id}, {"$set": {"share_token": token}})
    return {"status": "shared", "share_token": token}


@router.get("/shared/team/{share_token}")
async def get_shared_team(share_token: str):
    """Public endpoint: view a team's roster + recently shared matches (no auth)"""
    team = await db.teams.find_one({"share_token": share_token}, {"_id": 0})
    if not team:
        raise HTTPException(status_code=404, detail="Shared team not found or link expired")

    # Roster (sanitize: drop internal fields like storage paths and user_id)
    players_raw = await db.players.find(
        {"team_ids": team["id"], "user_id": team["user_id"]}, {"_id": 0}
    ).to_list(200)
    public_fields = {"id", "name", "number", "position", "profile_pic_url"}
    players = [{k: p.get(k) for k in public_fields} for p in players_raw]

    # Club info (for crest)
    club_info = None
    if team.get("club"):
        club = await db.clubs.find_one(
            {"id": team["club"], "user_id": team["user_id"]},
            {"_id": 0, "name": 1, "logo_url": 1, "id": 1}
        )
        if club:
            club_info = club

    # Owner / coach
    owner = await db.users.find_one({"id": team["user_id"]}, {"_id": 0, "name": 1, "role": 1})

    # Recently shared matches: find matches owned by this team's coach where the
    # parent folder is publicly shared. Match folder.share_token = token so
    # the public viewer can navigate from team page → folder share view.
    shared_folders = await db.folders.find(
        {"user_id": team["user_id"], "share_token": {"$ne": None}, "is_private": False},
        {"_id": 0, "id": 1, "name": 1, "share_token": 1}
    ).to_list(100)

    folder_by_id = {f["id"]: f for f in shared_folders}
    shared_matches = []
    if folder_by_id:
        matches = await db.matches.find(
            {
                "user_id": team["user_id"],
                "folder_id": {"$in": list(folder_by_id.keys())},
            },
            {"_id": 0, "id": 1, "team_home": 1, "team_away": 1, "date": 1,
             "competition": 1, "folder_id": 1, "video_id": 1}
        ).sort("date", -1).to_list(20)
        for m in matches:
            f = folder_by_id.get(m.get("folder_id"))
            if f:
                m["folder_share_token"] = f["share_token"]
                m["folder_name"] = f["name"]
                shared_matches.append(m)

    return {
        "team": {
            "id": team["id"],
            "name": team["name"],
            "season": team["season"],
        },
        "club": club_info,
        "owner": {"name": (owner or {}).get("name", "Coach")},
        "players": players,
        "shared_matches": shared_matches,
    }


@router.get("/og/team/{share_token}")
async def og_team_preview(share_token: str, request: Request):
    """Server-rendered OG/Twitter card for a shared team page.

    Crawlers (WhatsApp, Slack, Twitter, LinkedIn, Discord, FB) read the static
    HTML for unfurl previews. Real browsers JS-redirect to the React route.
    """
    team = await db.teams.find_one({"share_token": share_token}, {"_id": 0})
    if not team:
        return HTMLResponse(
            "<html><body><h1>Link Unavailable</h1></body></html>",
            status_code=404,
        )

    player_count = await db.players.count_documents(
        {"team_ids": team["id"], "user_id": team["user_id"]}
    )

    club_name = ""
    if team.get("club"):
        club = await db.clubs.find_one(
            {"id": team["club"], "user_id": team["user_id"]},
            {"_id": 0, "name": 1},
        )
        if club:
            club_name = club.get("name", "")

    title = f"{team['name']} — {team['season']}"
    if club_name:
        title = f"{team['name']} — {club_name} ({team['season']})"
    description = f"Squad of {player_count} players. View the full roster, jersey numbers, and recent match film."

    # Frontend SPA route the user is redirected to
    spa_url = f"/shared-team/{share_token}"
    # Use the public-facing host (X-Forwarded-Host) when behind ingress so the
    # generated og:image URL is reachable by WhatsApp/Slack/Twitter crawlers,
    # not the internal cluster URL that request.base_url returns.
    fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    fwd_proto = request.headers.get("x-forwarded-proto", "https")
    public_base = f"{fwd_proto}://{fwd_host}" if fwd_host else str(request.base_url).rstrip("/")
    og_image_url = f"{public_base}/api/og/team/{share_token}/image.png"

    e_title = html_lib.escape(title)
    e_desc = html_lib.escape(description)
    e_img = html_lib.escape(og_image_url)
    e_spa = html_lib.escape(spa_url)

    image_tags = f"""
    <meta property="og:image" content="{e_img}" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:type" content="image/png" />
    <meta name="twitter:image" content="{e_img}" />"""

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <title>{e_title}</title>
    <meta name="description" content="{e_desc}" />

    <meta property="og:type" content="profile" />
    <meta property="og:title" content="{e_title}" />
    <meta property="og:description" content="{e_desc}" />
    <meta property="og:site_name" content="Soccer Scout" />

    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{e_title}" />
    <meta name="twitter:description" content="{e_desc}" />{image_tags}

    <meta http-equiv="refresh" content="0; url={e_spa}" />
    <script>window.location.replace({_js_string(spa_url)});</script>
</head>
<body style="background:#0A0A0A;color:#fff;font-family:system-ui;padding:48px;text-align:center">
    <p>Loading team page&hellip; <a href="{e_spa}" style="color:#007AFF">Click here</a> if not redirected.</p>
</body>
</html>"""
    return HTMLResponse(body)


@router.get("/og/team/{share_token}/image.png")
async def og_team_image(share_token: str):
    """Render a dynamic 1200x630 OG card PNG for the shared team."""
    team = await db.teams.find_one({"share_token": share_token}, {"_id": 0})
    if not team:
        raise HTTPException(status_code=404, detail="Not found")

    # Player count + first few avatars
    cursor = db.players.find(
        {"team_ids": team["id"], "user_id": team["user_id"]},
        {"_id": 0, "profile_pic_path": 1, "number": 1, "name": 1, "position": 1},
    ).sort("number", 1)
    all_players = await cursor.to_list(50)
    player_count = len(all_players)

    # Fetch up to 6 player avatar bytes from object storage
    avatar_blobs = []
    for p in all_players:
        if len(avatar_blobs) >= 6:
            break
        path = p.get("profile_pic_path")
        if not path:
            continue
        try:
            data, _ = await run_in_threadpool(get_object_sync, path)
            avatar_blobs.append(data)
        except Exception:
            continue

    # Club info / logo bytes
    club_name = ""
    club_logo_bytes = None
    if team.get("club"):
        club = await db.clubs.find_one(
            {"id": team["club"], "user_id": team["user_id"]},
            {"_id": 0, "name": 1, "logo_path": 1},
        )
        if club:
            club_name = club.get("name", "")
            if club.get("logo_path"):
                try:
                    club_logo_bytes, _ = await run_in_threadpool(
                        get_object_sync, club["logo_path"]
                    )
                except Exception:
                    pass

    png = await run_in_threadpool(
        render_team_card,
        team["name"],
        team["season"],
        club_name,
        player_count,
        club_logo_bytes,
        avatar_blobs,
    )
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


def _js_string(s: str) -> str:
    """JSON-safe JS string literal to avoid script injection in window.location."""
    import json
    return json.dumps(s)


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



# ===== Club Sharing =====

@router.post("/clubs/{club_id}/share")
async def toggle_club_share(club_id: str, current_user: dict = Depends(get_current_user)):
    """Toggle a public share token for an entire club (all teams + crest)."""
    club = await db.clubs.find_one(
        {"id": club_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    if club.get("share_token"):
        await db.clubs.update_one({"id": club_id}, {"$set": {"share_token": None}})
        return {"status": "unshared", "share_token": None}
    token = str(uuid.uuid4())[:12]
    await db.clubs.update_one({"id": club_id}, {"$set": {"share_token": token}})
    return {"status": "shared", "share_token": token}


@router.get("/shared/club/{share_token}")
async def get_shared_club(share_token: str):
    """Public: club crest + all its teams (with player counts) for a club home page."""
    club = await db.clubs.find_one({"share_token": share_token}, {"_id": 0})
    if not club:
        raise HTTPException(status_code=404, detail="Shared club not found")

    teams = await db.teams.find(
        {"club": club["id"], "user_id": club["user_id"]},
        {"_id": 0, "id": 1, "name": 1, "season": 1, "share_token": 1},
    ).sort("season", -1).to_list(200)

    # Enrich with player counts
    for t in teams:
        t["player_count"] = await db.players.count_documents(
            {"team_ids": t["id"], "user_id": club["user_id"]}
        )

    owner = await db.users.find_one({"id": club["user_id"]}, {"_id": 0, "name": 1})

    return {
        "club": {
            "id": club["id"],
            "name": club["name"],
            "logo_url": club.get("logo_url"),
        },
        "owner": {"name": (owner or {}).get("name", "Coach")},
        "teams": teams,
    }
