"""Player profile aggregation, public share, and clip-collection (batch share) endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone
import uuid
from db import db
from routes.auth import get_current_user

router = APIRouter()


async def _build_profile_payload(player: dict, user_id: str, public: bool) -> dict:
    """Aggregate player identity + teams + clip-derived stats + highlight reel.

    When `public=True`, sanitize internal fields and ensure each clip has a
    share_token so its existing public stream endpoint serves the video.
    """
    team_ids = player.get("team_ids") or []
    teams = []
    if team_ids:
        teams = await db.teams.find(
            {"id": {"$in": team_ids}, "user_id": user_id},
            {"_id": 0, "id": 1, "name": 1, "season": 1, "club": 1},
        ).to_list(50)

    clips = await db.clips.find(
        {"player_ids": player["id"], "user_id": user_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(500)

    stats_by_type: dict[str, int] = {}
    for c in clips:
        t = (c.get("clip_type") or "highlight").lower()
        stats_by_type[t] = stats_by_type.get(t, 0) + 1
    total_duration = sum(
        max(0, (c.get("end_time") or 0) - (c.get("start_time") or 0)) for c in clips
    )

    match_ids = list({c.get("match_id") for c in clips if c.get("match_id")})
    matches = []
    if match_ids:
        matches = await db.matches.find(
            {"id": {"$in": match_ids}, "user_id": user_id},
            {"_id": 0, "id": 1, "team_home": 1, "team_away": 1, "date": 1, "competition": 1},
        ).to_list(500)
    match_by_id = {m["id"]: m for m in matches}

    if public:
        # Auto-grant a share_token on each highlight clip so streams work for viewers
        for c in clips[:50]:
            if not c.get("share_token"):
                tok = str(uuid.uuid4())[:12]
                await db.clips.update_one(
                    {"id": c["id"]}, {"$set": {"share_token": tok}}
                )
                c["share_token"] = tok

        public_player = {
            k: player.get(k)
            for k in {"id", "name", "number", "position", "profile_pic_url", "team"}
        }
        public_clip_fields = {
            "id", "title", "clip_type", "start_time", "end_time",
            "auto_generated", "share_token", "match_id",
        }
        sanitized_clips = [
            {**{k: c.get(k) for k in public_clip_fields},
             "match": match_by_id.get(c.get("match_id"))}
            for c in clips[:50]
        ]
        owner = await db.users.find_one(
            {"id": user_id}, {"_id": 0, "name": 1}
        )
        return {
            "player": public_player,
            "teams": teams,
            "stats": {
                "total_clips": len(clips),
                "total_seconds": round(total_duration, 1),
                "by_type": stats_by_type,
            },
            "clips": sanitized_clips,
            "owner": (owner or {}).get("name", "Coach"),
        }

    return {
        "player": player,
        "teams": teams,
        "stats": {
            "total_clips": len(clips),
            "total_seconds": round(total_duration, 1),
            "by_type": stats_by_type,
        },
        "clips": [
            {**c, "match": match_by_id.get(c.get("match_id"))}
            for c in clips[:50]
        ],
    }


# ===== Player profile =====

@router.get("/players/{player_id}/profile")
async def get_player_profile(
    player_id: str, current_user: dict = Depends(get_current_user)
):
    """Aggregated profile (auth)."""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]},
        {"_id": 0, "profile_pic_path": 0},
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    return await _build_profile_payload(player, current_user["id"], public=False)


@router.post("/players/{player_id}/share")
async def toggle_player_share(
    player_id: str, current_user: dict = Depends(get_current_user)
):
    """Toggle a public share token on a player's profile."""
    player = await db.players.find_one(
        {"id": player_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")
    if player.get("share_token"):
        await db.players.update_one(
            {"id": player_id}, {"$set": {"share_token": None}}
        )
        return {"status": "unshared", "share_token": None}
    token = str(uuid.uuid4())[:12]
    await db.players.update_one(
        {"id": player_id}, {"$set": {"share_token": token}}
    )
    return {"status": "shared", "share_token": token}


@router.get("/shared/player/{share_token}")
async def get_shared_player(share_token: str):
    """Public dossier (no auth)."""
    player = await db.players.find_one(
        {"share_token": share_token}, {"_id": 0, "profile_pic_path": 0}
    )
    if not player:
        raise HTTPException(status_code=404, detail="Player share link not found")
    return await _build_profile_payload(player, player["user_id"], public=True)


# ===== Clip collections (batch share) =====


class ClipCollectionCreate(BaseModel):
    title: Optional[str] = None
    clip_ids: List[str] = Field(min_length=1)


@router.post("/clip-collections")
async def create_clip_collection(
    body: ClipCollectionCreate, current_user: dict = Depends(get_current_user)
):
    owned = await db.clips.find(
        {"id": {"$in": body.clip_ids}, "user_id": current_user["id"]},
        {"_id": 0, "id": 1},
    ).to_list(500)
    owned_ids = {c["id"] for c in owned}
    unknown = [cid for cid in body.clip_ids if cid not in owned_ids]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or unauthorized clip ids: {', '.join(unknown)}",
        )

    title = body.title or f"{len(body.clip_ids)} Clips"
    coll = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "title": title,
        "clip_ids": list(body.clip_ids),
        "share_token": str(uuid.uuid4())[:12],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.clip_collections.insert_one(coll)
    return {k: v for k, v in coll.items() if k != "_id"}


@router.get("/clip-collections")
async def list_clip_collections(current_user: dict = Depends(get_current_user)):
    return await db.clip_collections.find(
        {"user_id": current_user["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)


@router.delete("/clip-collections/{collection_id}")
async def delete_clip_collection(
    collection_id: str, current_user: dict = Depends(get_current_user)
):
    res = await db.clip_collections.delete_one(
        {"id": collection_id, "user_id": current_user["id"]}
    )
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"status": "deleted"}


@router.get("/shared/clip-collection/{share_token}")
async def get_shared_clip_collection(share_token: str):
    coll = await db.clip_collections.find_one({"share_token": share_token}, {"_id": 0})
    if not coll:
        raise HTTPException(status_code=404, detail="Not found")

    clips_raw = await db.clips.find(
        {"id": {"$in": coll["clip_ids"]}, "user_id": coll["user_id"]}, {"_id": 0}
    ).to_list(500)
    by_id = {c["id"]: c for c in clips_raw}
    ordered_clips: list[dict] = []
    for cid in coll["clip_ids"]:
        c = by_id.get(cid)
        if not c:
            continue
        if not c.get("share_token"):
            tok = str(uuid.uuid4())[:12]
            await db.clips.update_one(
                {"id": cid}, {"$set": {"share_token": tok}}
            )
            c["share_token"] = tok
        ordered_clips.append(c)

    match_ids = list({c.get("match_id") for c in ordered_clips if c.get("match_id")})
    matches = []
    if match_ids:
        matches = await db.matches.find(
            {"id": {"$in": match_ids}},
            {"_id": 0, "id": 1, "team_home": 1, "team_away": 1, "date": 1, "competition": 1},
        ).to_list(200)
    match_by_id = {m["id"]: m for m in matches}

    owner = await db.users.find_one(
        {"id": coll["user_id"]}, {"_id": 0, "name": 1}
    )

    return {
        "collection": {
            "id": coll["id"],
            "title": coll["title"],
            "created_at": coll["created_at"],
        },
        "owner": (owner or {}).get("name", "Coach"),
        "clips": [
            {**c, "match": match_by_id.get(c.get("match_id"))}
            for c in ordered_clips
        ],
    }
