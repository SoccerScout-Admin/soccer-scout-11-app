"""Admin endpoints — list users, promote/demote roles.

Only users with role `admin` or `owner` can access these endpoints. The single
admin bootstrap flow (e.g. the first user being promoted via mongosh) remains
unchanged; once there's one admin, they can promote others from the UI.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from db import db
from routes.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_ROLES = {"coach", "analyst", "admin", "owner"}


def _require_admin(user: dict):
    role = (user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")


class RoleUpdate(BaseModel):
    role: str


@router.get("/admin/users")
async def list_users(
    q: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """List all users with basic info. Optional `q` filter by email or name substring (case-insensitive)."""
    _require_admin(current_user)
    query: dict = {}
    if q:
        import re
        pattern = {"$regex": re.escape(q), "$options": "i"}
        query = {"$or": [{"email": pattern}, {"name": pattern}]}
    users = await db.users.find(query, {"_id": 0, "password": 0}).sort("created_at", -1).to_list(500)
    # Enrich with counts
    for u in users:
        u["matches_count"] = await db.matches.count_documents({"user_id": u["id"]})
        u["clips_count"] = await db.clips.count_documents({"user_id": u["id"]})
    return users


@router.post("/admin/users/{user_id}/role")
async def update_role(
    user_id: str,
    body: RoleUpdate,
    current_user: dict = Depends(get_current_user),
):
    """Promote/demote a user's role. Only admin/owner can call. Owner-role cannot be demoted
    except by another owner (guards against lockout)."""
    _require_admin(current_user)
    new_role = (body.role or "").lower()
    if new_role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {sorted(VALID_ROLES)}")

    target = await db.users.find_one({"id": user_id}, {"_id": 0, "role": 1, "email": 1})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target_role = (target.get("role") or "").lower()
    actor_role = (current_user.get("role") or "").lower()

    if target_role == "owner" and actor_role != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can change another owner's role")
    if new_role == "owner" and actor_role != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can grant owner role")

    # Self-demotion guard: don't let an admin demote themselves if they're the last admin
    if user_id == current_user["id"] and new_role not in ("admin", "owner"):
        others = await db.users.count_documents({
            "role": {"$in": ["admin", "owner"]},
            "id": {"$ne": user_id},
        })
        if others == 0:
            raise HTTPException(status_code=400, detail="Cannot demote the last admin — promote someone else first")

    await db.users.update_one(
        {"id": user_id},
        {"$set": {"role": new_role, "role_updated_at": datetime.now(timezone.utc).isoformat(), "role_updated_by": current_user["id"]}},
    )
    logger.info("User %s role changed: %s → %s (by %s)", target.get("email"), target_role, new_role, current_user.get("email"))
    return {"user_id": user_id, "role": new_role}


# ===== Email Queue (quota-exhaustion fallback) =====


@router.get("/admin/email-queue")
async def get_email_queue(
    status: Optional[str] = None,
    limit: int = 50,
    current_user: dict = Depends(get_current_user),
):
    """Admin view of the email queue — shows depth + recent entries."""
    _require_admin(current_user)
    from services.email_queue import get_queue_depth, list_queue
    depth = await get_queue_depth()
    items = await list_queue(limit=max(1, min(limit, 200)), status=status)
    return {"depth": depth, "items": items}


@router.post("/admin/email-queue/process")
async def trigger_queue_process(current_user: dict = Depends(get_current_user)):
    """Manually fire the retry pass. Useful when quota resets unexpectedly."""
    _require_admin(current_user)
    from services.email_queue import process_queue
    return await process_queue(limit=200)


@router.post("/admin/email-queue/{queue_id}/retry")
async def retry_queue_item(queue_id: str, current_user: dict = Depends(get_current_user)):
    """Retry one queued email right now."""
    _require_admin(current_user)
    from services.email_queue import retry_now
    result = await retry_now(queue_id)
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Queue item not found")
    return result


# ===== Game of the Week =====


@router.post("/admin/game-of-the-week/set")
async def set_game_of_the_week(
    payload: dict,
    current_user: dict = Depends(get_current_user),
):
    """Admin-only. Promote one shared match recap to every coach's dashboard for 7 days.

    Expects body: {"share_token": "<token from POST /matches/{id}/share-recap>"}.
    The pick is stored in the single-doc `featured` collection so lookups are O(1).
    Previous pick is replaced; featured_at resets the 7-day clock.
    """
    _require_admin(current_user)
    share_token = (payload or {}).get("share_token")
    if not share_token:
        raise HTTPException(status_code=400, detail="share_token is required")

    match = await db.matches.find_one(
        {"manual_result.recap_share_token": share_token},
        {"_id": 0, "id": 1, "team_home": 1, "team_away": 1, "manual_result": 1, "insights": 1, "competition": 1, "date": 1},
    )
    if not match:
        raise HTTPException(status_code=404, detail="No shared recap found for that token")

    featured_at = datetime.now(timezone.utc).isoformat()
    doc = {
        "_kind": "game_of_the_week",  # singleton discriminator
        "share_token": share_token,
        "match_id": match["id"],
        "team_home": match["team_home"],
        "team_away": match["team_away"],
        "home_score": (match.get("manual_result") or {}).get("home_score", 0),
        "away_score": (match.get("manual_result") or {}).get("away_score", 0),
        "outcome": (match.get("manual_result") or {}).get("outcome", "D"),
        "competition": match.get("competition") or "",
        "date": match.get("date"),
        "summary": (match.get("insights") or {}).get("summary", "")[:300],
        "featured_at": featured_at,
        "featured_by": current_user["id"],
        "featured_by_name": current_user.get("name", ""),
    }
    await db.featured.update_one({"_kind": "game_of_the_week"}, {"$set": doc}, upsert=True)
    return {"status": "featured", "share_token": share_token, "featured_at": featured_at}


@router.delete("/admin/game-of-the-week")
async def clear_game_of_the_week(current_user: dict = Depends(get_current_user)):
    """Admin-only. Remove the current Game of the Week before its 7-day window ends."""
    _require_admin(current_user)
    await db.featured.delete_one({"_kind": "game_of_the_week"})
    return {"status": "cleared"}


@router.get("/game-of-the-week")
async def get_game_of_the_week():
    """Public endpoint — returns the current Game of the Week (or null if expired/unset).

    Auto-expires 7 days after `featured_at`. No auth required so the Dashboard
    banner loads without a JWT round-trip.
    """
    doc = await db.featured.find_one({"_kind": "game_of_the_week"}, {"_id": 0, "featured_by": 0})
    if not doc:
        return {"active": False}
    featured_at = doc.get("featured_at")
    try:
        dt = datetime.fromisoformat(featured_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - dt).days
    except Exception:
        age_days = 0
    if age_days >= 7:
        # Lazily expire — clean up on read so no cron job needed
        await db.featured.delete_one({"_kind": "game_of_the_week"})
        return {"active": False}
    days_remaining = 7 - age_days
    return {"active": True, "days_remaining": days_remaining, **doc}
