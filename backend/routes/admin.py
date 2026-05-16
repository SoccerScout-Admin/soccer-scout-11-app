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
from datetime import datetime, timedelta, timezone
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



def _bucket_groupings(ev: dict, buckets: dict) -> None:
    """Increment the grouped-counter dicts (by_event_type, by_failure_mode,
    by_tier). Pure dict mutation, no derived logic."""
    et = ev.get("event_type", "unknown")
    buckets["by_event_type"][et] = buckets["by_event_type"].get(et, 0) + 1

    fm = ev.get("failure_mode")
    if fm:
        buckets["by_failure_mode"][fm] = buckets["by_failure_mode"].get(fm, 0) + 1

    tl = ev.get("tier_label")
    if tl:
        key = f"tier{ev.get('tier_idx')}: {tl}"
        buckets["by_tier"][key] = buckets["by_tier"].get(key, 0) + 1


def _bucket_outcome_counters(ev: dict, buckets: dict) -> None:
    """Bump the named outcome counters (tier0_oom, tier1_recoveries, final_*).
    Mutually exclusive elif chain keeps CC manageable."""
    et = ev.get("event_type", "unknown")
    fm = ev.get("failure_mode")

    if et == "tier_failed" and ev.get("tier_idx") == 0 and fm == "oom":
        buckets["tier0_oom_count"] += 1
    elif et == "tier_succeeded" and ev.get("tier_idx", 0) > 0:
        buckets["tier1_recoveries"] += 1
    elif et == "final_success":
        buckets["final_success"] += 1
    elif et == "final_failure":
        buckets["final_failure"] += 1

    vid = ev.get("video_id")
    if vid and ev.get("tier_idx") is not None:
        prior = buckets["tier_attempts_per_video"].get(vid, 0)
        buckets["tier_attempts_per_video"][vid] = max(prior, ev["tier_idx"])


def _bucket_event(ev: dict, buckets: dict) -> None:
    """Dispatch one event into all of the aggregator buckets.

    Extracted from processing_events_stats() to keep its cyclomatic
    complexity under the 10-rule limit. Splits further into _groupings
    and _outcome_counters because the combined branch count was 12 — over
    the same threshold."""
    _bucket_groupings(ev, buckets)
    _bucket_outcome_counters(ev, buckets)


def _derive_rates(b: dict) -> dict:
    """Compute the % rates from the raw counters in `b`. Pure function, no I/O."""
    total_finals = b["final_success"] + b["final_failure"]
    final_success_rate = round(b["final_success"] / total_finals * 100, 1) if total_finals else None
    retry_save_rate = (
        round(b["tier1_recoveries"] / b["tier0_oom_count"] * 100, 1)
        if b["tier0_oom_count"] else None
    )
    return {
        "final_success": b["final_success"],
        "final_failure": b["final_failure"],
        "final_success_rate_pct": final_success_rate,
        "tier0_oom_count": b["tier0_oom_count"],
        "tier1_recoveries": b["tier1_recoveries"],
        "retry_save_rate_pct": retry_save_rate,
        "unique_videos": len(b["tier_attempts_per_video"]),
    }


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

    Refactored iter66 — extracted _bucket_event() and _derive_rates() to
    keep this function under the 50-line / CC-10 / 15-locals limits.
    """
    _require_admin(current_user)
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()

    cursor = db.processing_events.find(
        {"created_at": {"$gte": since}}, {"_id": 0},
    ).sort("created_at", -1).limit(5000)
    events = await cursor.to_list(5000)

    buckets = {
        "by_event_type": {},
        "by_failure_mode": {},
        "by_tier": {},
        "tier0_oom_count": 0,
        "tier1_recoveries": 0,
        "final_success": 0,
        "final_failure": 0,
        "tier_attempts_per_video": {},
    }
    for ev in events:
        _bucket_event(ev, buckets)

    return {
        "window_days": days,
        "since": since,
        "total_events": len(events),
        "by_event_type": buckets["by_event_type"],
        "by_failure_mode": buckets["by_failure_mode"],
        "by_tier": buckets["by_tier"],
        "summary": _derive_rates(buckets),
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


async def _enrich_failed_event(ev: dict) -> dict:
    """Join a final_failure event with the source video / match / coach so the
    admin sees enough triage context in one row (no second-click required).

    Defensive: any of these documents may have been hard-deleted between the
    failure and the admin opening the dashboard. Missing joins degrade to
    None values rather than dropping the row — the admin still wants to know
    a 4.2GB upload died, even if the video doc is gone.
    """
    video = await db.videos.find_one(
        {"id": ev["video_id"]},
        {"_id": 0, "id": 1, "filename": 1, "match_id": 1, "user_id": 1},
    ) or {}

    match = None
    if video.get("match_id"):
        match = await db.matches.find_one(
            {"id": video["match_id"]},
            {"_id": 0, "id": 1, "team_home": 1, "team_away": 1, "date": 1},
        )

    coach = None
    if video.get("user_id") or ev.get("user_id"):
        uid = video.get("user_id") or ev.get("user_id")
        coach = await db.users.find_one(
            {"id": uid}, {"_id": 0, "id": 1, "email": 1, "name": 1},
        )

    match_label = None
    if match and (match.get("team_home") or match.get("team_away")):
        match_label = f"{match.get('team_home') or '—'} vs {match.get('team_away') or '—'}"

    # Surface whether we've already emailed this coach about this specific
    # failed video — admins will see a "Sent ✓" badge in the UI instead of
    # accidentally double-emailing a user who's already mid-fix.
    sent_record = await db.compression_help_sent.find_one(
        {"video_id": ev["video_id"]},
        {"_id": 0, "sent_at": 1, "to_email": 1},
    )

    return {
        "video_id": ev["video_id"],
        "filename": video.get("filename") or "(deleted)",
        "size_gb": ev.get("source_size_gb"),
        "failure_mode": ev.get("failure_mode") or "unknown",
        "tier_label": ev.get("tier_label"),
        "tier_idx": ev.get("tier_idx"),
        "duration_seconds": ev.get("duration_seconds"),
        "error_message": ev.get("error_message"),
        "failed_at": ev.get("created_at"),
        "match_id": video.get("match_id"),
        "match_label": match_label,
        "match_date": match.get("date") if match else None,
        "coach_email": coach.get("email") if coach else None,
        "coach_name": coach.get("name") if coach else None,
        "compression_email_sent_at": sent_record.get("sent_at") if sent_record else None,
    }


@router.get("/admin/processing-events/top-failed")
async def processing_events_top_failed(
    hours: int = 24,
    limit: int = 5,
    current_user: dict = Depends(get_current_user),
):
    """Top-N largest videos that hit `final_failure` in the last `hours`.

    Quick-triage panel for the Admin Processing Events Dashboard. Sorted by
    `source_size_gb` DESC because the biggest failures are the highest-leverage
    ones to investigate first — they're either pushing us against the pod
    memory ceiling (justifies bumping) or hitting a user-facing size limit
    (justifies a clearer upload warning).

    Deduped by `video_id` — only the worst event per video is returned, so
    one video that retried 3 times doesn't crowd out 4 other failing videos.
    Joined with `videos` / `matches` / `users` so the admin can DM the coach
    immediately without a second lookup.
    """
    _require_admin(current_user)
    hours = max(1, min(hours, 168))  # cap at 1 week
    limit = max(1, min(limit, 20))
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    cursor = db.processing_events.find(
        {"event_type": "final_failure", "created_at": {"$gte": since}},
        {"_id": 0},
    ).sort("source_size_gb", -1).limit(200)
    events = await cursor.to_list(200)

    seen: set[str] = set()
    top: list[dict] = []
    for ev in events:
        vid = ev.get("video_id")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        top.append(ev)
        if len(top) >= limit:
            break

    enriched = [await _enrich_failed_event(ev) for ev in top]
    return {"window_hours": hours, "count": len(enriched), "videos": enriched}


class CompressionHelpRequest(BaseModel):
    video_id: str


def _compression_help_html(coach_name: Optional[str], filename: str, size_gb: Optional[float], failure_mode: str) -> str:
    """HTML body for the compression-help email. Keep it short, friendly, and
    actionable — the goal is to convert "video failed" into "video succeeded
    in their next attempt" with as little friction as possible.

    Style mirrors existing Soccer Scout transactional emails (dark header,
    light card body, single primary instruction)."""
    greeting = f"Hi {coach_name}," if coach_name else "Hi there,"
    size_label = f"{size_gb} GB" if size_gb is not None else "your last upload"
    return f"""\
<!DOCTYPE html>
<html><body style="margin:0;padding:0;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;background:#0A0A0A;color:#E5E5E5;">
  <div style="max-width:560px;margin:0 auto;padding:24px;">
    <div style="background:#141414;border:1px solid #2A2A2A;border-radius:8px;overflow:hidden;">
      <div style="background:#007AFF;padding:20px 24px;">
        <div style="color:#fff;font-size:11px;letter-spacing:0.2em;text-transform:uppercase;font-weight:700;">Soccer Scout · Upload Support</div>
        <div style="color:#fff;font-size:20px;font-weight:700;margin-top:6px;">Your upload didn't quite make it through</div>
      </div>
      <div style="padding:24px;color:#E5E5E5;line-height:1.55;font-size:14px;">
        <p>{greeting}</p>
        <p>Your match film <strong style="color:#fff;">{filename}</strong> ({size_label}) hit a processing failure ({failure_mode}) — even after our auto-retry at a lower resolution. That's a sign the source file is just too heavy for our encoding pod to chew through.</p>
        <p style="margin-top:18px;font-weight:700;color:#fff;">Quickest fix: re-compress with HandBrake (free) and try again</p>
        <ol style="padding-left:18px;margin:8px 0;">
          <li>Download <a href="https://handbrake.fr/downloads.php" style="color:#7DD3FC;">HandBrake</a> for Mac / Windows / Linux</li>
          <li>Open your match film in it</li>
          <li>Pick the preset: <strong style="color:#FBBF24;">Fast 720p30</strong></li>
          <li>Under "Video", set <strong style="color:#FBBF24;">Constant Quality (CQ) = 28</strong></li>
          <li>Save the new file and re-upload to the same match (the original is already deleted — nothing to clean up)</li>
        </ol>
        <p style="margin-top:18px;">This should get the file under ~1.5 GB without any visible quality loss for tactical analysis. AI analysis runs at 360p anyway, so you're not losing anything we'd actually use.</p>
        <p style="margin-top:18px;color:#A3A3A3;font-size:13px;">If that still doesn't work, reply to this email and I'll personally take a look. — Soccer Scout team</p>
      </div>
    </div>
    <p style="font-size:11px;color:#666;text-align:center;margin-top:16px;">You're receiving this because a Soccer Scout admin manually flagged your upload for follow-up help. We don't send this automatically.</p>
  </div>
</body></html>"""


@router.post("/admin/processing-events/email-compression-help")
async def email_compression_help(
    body: CompressionHelpRequest,
    current_user: dict = Depends(get_current_user),
):
    """Send a Resend email to the coach whose video hit `final_failure`, with
    HandBrake compression instructions tailored to the iter63 retry-tier
    error message ("Fast 720p30 / CQ 28").

    De-duped by `(video_id)` in `compression_help_sent` — clicking the same
    row twice will NOT re-email the coach (you'll get a 200 with
    `status: "already_sent"`). The admin can see the prior send timestamp in
    the Top Failed Videos panel.

    Failure handling: if Resend is unavailable or the coach has no email on
    record, returns a 200 with `status: "skipped"` and a `reason` field. The
    admin sees the reason in the toast — no exception thrown."""
    _require_admin(current_user)

    # Find the failure event for context
    ev = await db.processing_events.find_one(
        {"video_id": body.video_id, "event_type": "final_failure"},
        {"_id": 0},
    )
    if not ev:
        raise HTTPException(status_code=404, detail="No final_failure event for that video")

    # De-dup check
    prior = await db.compression_help_sent.find_one(
        {"video_id": body.video_id}, {"_id": 0, "sent_at": 1, "to_email": 1},
    )
    if prior:
        return {
            "status": "already_sent",
            "sent_at": prior.get("sent_at"),
            "to_email": prior.get("to_email"),
        }

    video = await db.videos.find_one(
        {"id": body.video_id},
        {"_id": 0, "filename": 1, "user_id": 1},
    ) or {}
    uid = video.get("user_id") or ev.get("user_id")
    if not uid:
        return {"status": "skipped", "reason": "no user_id on video or event"}

    coach = await db.users.find_one(
        {"id": uid}, {"_id": 0, "email": 1, "name": 1},
    )
    if not coach or not coach.get("email"):
        return {"status": "skipped", "reason": "coach has no email on record"}

    filename = video.get("filename") or "your match film"
    html = _compression_help_html(
        coach_name=coach.get("name"),
        filename=filename,
        size_gb=ev.get("source_size_gb"),
        failure_mode=ev.get("failure_mode") or "unknown",
    )
    subject = "Your Soccer Scout upload didn't process — quick fix inside"

    from services.email_queue import send_or_queue
    result = await send_or_queue(
        to_email=coach["email"],
        subject=subject,
        html=html,
        kind="compression_help",
        metadata={
            "video_id": body.video_id,
            "failure_mode": ev.get("failure_mode"),
            "size_gb": ev.get("source_size_gb"),
            "sent_by_admin_id": current_user["id"],
        },
    )

    if result.get("status") in ("sent", "quota_deferred"):
        await db.compression_help_sent.insert_one({
            "id": f"ch-{body.video_id}",
            "video_id": body.video_id,
            "to_email": coach["email"],
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "sent_by_admin_id": current_user["id"],
            "delivery_status": result.get("status"),
            "email_id": result.get("email_id"),
            "queue_id": result.get("queue_id"),
        })
        return {
            "status": result.get("status"),
            "to_email": coach["email"],
            "email_id": result.get("email_id"),
        }
    return {"status": "skipped", "reason": result.get("error") or "send failed"}


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
