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
