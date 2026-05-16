"""Admin endpoints — list users, promote/demote roles.

Only users with role `admin` or `owner` can access these endpoints. The single
admin bootstrap flow (e.g. the first user being promoted via mongosh) remains
unchanged; once there's one admin, they can promote others from the UI.

`/admin/bootstrap` is an escape-hatch for fresh environments — it lets an
authenticated user self-elevate to `admin` if they know the
`ADMIN_BOOTSTRAP_SECRET` from the server's env. Constant-time compare, audit
logged, no-op if the caller is already admin.
"""
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from db import db
from routes.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

VALID_ROLES = {"coach", "analyst", "admin", "owner", "scout", "college_coach"}


def _require_admin(user: dict):
    role = (user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")


class RoleUpdate(BaseModel):
    role: str


class BootstrapRequest(BaseModel):
    secret: str


@router.post("/admin/bootstrap")
async def bootstrap_admin(
    body: BootstrapRequest,
    current_user: dict = Depends(get_current_user),
):
    """Self-promote the authenticated caller to `admin` if `secret` matches
    the server's `ADMIN_BOOTSTRAP_SECRET` env var.

    Designed for fresh environments where no admin exists yet. Silent no-op
    if the caller is already admin/owner. Always logs the attempt (success or
    failure) at WARNING level for audit trails.
    """
    expected = os.environ.get("ADMIN_BOOTSTRAP_SECRET", "")
    if not expected:
        logger.warning("[admin-bootstrap] rejected — ADMIN_BOOTSTRAP_SECRET is not configured")
        raise HTTPException(status_code=503, detail="Admin bootstrap is not configured on this server.")

    # Constant-time compare to prevent timing attacks on the secret.
    if not hmac.compare_digest(body.secret.encode("utf-8"), expected.encode("utf-8")):
        logger.warning("[admin-bootstrap] rejected for user=%s — bad secret", current_user.get("email"))
        raise HTTPException(status_code=403, detail="Invalid bootstrap secret.")

    current_role = (current_user.get("role") or "").lower()
    if current_role in ("admin", "owner"):
        logger.info("[admin-bootstrap] no-op for user=%s (already %s)", current_user.get("email"), current_role)
        return {"status": "already_admin", "role": current_role}

    await db.users.update_one({"id": current_user["id"]}, {"$set": {"role": "admin"}})
    logger.warning("[admin-bootstrap] GRANTED admin to user=%s (id=%s)", current_user.get("email"), current_user.get("id"))
    return {"status": "promoted", "role": "admin"}


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



@router.get("/admin/processing-events/stats")
async def processing_events_stats(
    days: int = 30,
    current_user: dict = Depends(get_current_user),
):
    """Aggregated view of the video-processing pipeline's health.

    Returns counts grouped by event_type + failure_mode + tier, plus a few
    derived rates that matter operationally:
      - retry_save_rate: % of tier-0 failures that recovered at tier 1
      - oom_rate: % of pipeline runs that hit OOM at any tier
      - final_success_rate: % of started videos that fully succeeded

    Use this to decide whether to bump pod memory limits, change default
    tier-0 scale settings, or warn users earlier when uploads are too large.
    """
    _require_admin(current_user)
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()

    cursor = db.processing_events.find(
        {"created_at": {"$gte": since}},
        {"_id": 0},
    ).sort("created_at", -1).limit(5000)
    events = await cursor.to_list(5000)

    by_event_type = {}
    by_failure_mode = {}
    by_tier = {}
    tier0_oom_count = 0
    tier1_success_after_tier0_failure = 0
    final_success = 0
    final_failure = 0
    tier_attempts_per_video = {}  # video_id → max tier_idx seen

    for ev in events:
        et = ev.get("event_type", "unknown")
        by_event_type[et] = by_event_type.get(et, 0) + 1
        if ev.get("failure_mode"):
            by_failure_mode[ev["failure_mode"]] = by_failure_mode.get(ev["failure_mode"], 0) + 1
        if ev.get("tier_label"):
            key = f"tier{ev.get('tier_idx')}: {ev['tier_label']}"
            by_tier[key] = by_tier.get(key, 0) + 1

        if et == "tier_failed" and ev.get("tier_idx") == 0 and ev.get("failure_mode") == "oom":
            tier0_oom_count += 1
        if et == "tier_succeeded" and ev.get("tier_idx", 0) > 0:
            tier1_success_after_tier0_failure += 1
        if et == "final_success":
            final_success += 1
        if et == "final_failure":
            final_failure += 1

        vid = ev.get("video_id")
        if vid and ev.get("tier_idx") is not None:
            tier_attempts_per_video[vid] = max(tier_attempts_per_video.get(vid, 0), ev["tier_idx"])

    total_finals = final_success + final_failure
    final_success_rate = round(final_success / total_finals * 100, 1) if total_finals else None
    retry_save_rate = (
        round(tier1_success_after_tier0_failure / tier0_oom_count * 100, 1)
        if tier0_oom_count else None
    )

    return {
        "window_days": days,
        "since": since,
        "total_events": len(events),
        "by_event_type": by_event_type,
        "by_failure_mode": by_failure_mode,
        "by_tier": by_tier,
        "summary": {
            "final_success": final_success,
            "final_failure": final_failure,
            "final_success_rate_pct": final_success_rate,
            "tier0_oom_count": tier0_oom_count,
            "tier1_recoveries": tier1_success_after_tier0_failure,
            "retry_save_rate_pct": retry_save_rate,
            "unique_videos": len(tier_attempts_per_video),
        },
    }


@router.get("/admin/processing-events/recent")
async def processing_events_recent(
    limit: int = 50,
    event_type: Optional[str] = None,
    failure_mode: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """Recent event tail for debugging. Filter by event_type or failure_mode."""
    _require_admin(current_user)
    q: dict = {}
    if event_type:
        q["event_type"] = event_type
    if failure_mode:
        q["failure_mode"] = failure_mode
    cursor = db.processing_events.find(q, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 500)))
    return await cursor.to_list(500)



@router.post("/admin/processing-alerts/check")
async def trigger_processing_alert_check(
    current_user: dict = Depends(get_current_user),
):
    """Manually run the hourly pipeline-health check. Used to:
      - Verify Resend wiring + alert email looks right in production
      - Force an immediate re-eval after fixing a regression (e.g., you just
        bumped pod memory — does the next hour clear?)
    The same de-dup logic applies, so calling this twice in 5 minutes won't
    spam your inbox unless the rate has materially worsened."""
    _require_admin(current_user)
    from services.processing_alerts import check_and_alert
    return await check_and_alert()
