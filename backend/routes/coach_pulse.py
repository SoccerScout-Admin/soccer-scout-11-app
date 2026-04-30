"""Coach Pulse — weekly digest email.

Endpoints:
  GET  /api/coach-pulse/subscription          — current user's subscription state
  POST /api/coach-pulse/subscribe             — opt-in to weekly digest
  POST /api/coach-pulse/unsubscribe           — authenticated opt-out
  GET  /api/coach-pulse/unsubscribe/{token}   — public token-based opt-out (email link)
  GET  /api/coach-pulse/preview               — render HTML preview for the current user
  POST /api/coach-pulse/send-test             — send the digest only to the calling user
  POST /api/coach-pulse/send-weekly           — admin: blast to ALL active subscribers (idempotent per-user-per-week)
"""
from __future__ import annotations
import os
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import HTMLResponse, PlainTextResponse
import resend
from db import db
from routes.auth import get_current_user
from services.coach_pulse_email import render_coach_pulse_email

logger = logging.getLogger(__name__)
router = APIRouter()

resend.api_key = os.environ.get("RESEND_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
PUBLIC_BASE_URL = os.environ.get("REACT_APP_BACKEND_URL_PUBLIC") or ""


# ---------- helpers ----------

def _week_label(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("Week of %b %d, %Y")


def _week_start(dt: Optional[datetime] = None) -> datetime:
    """Monday 00:00 UTC of the current week."""
    dt = dt or datetime.now(timezone.utc)
    return (dt - timedelta(days=dt.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


async def _get_or_create_subscription(user_id: str) -> dict:
    sub = await db.coach_pulse_subscriptions.find_one({"user_id": user_id}, {"_id": 0})
    if sub:
        return sub
    sub = {
        "user_id": user_id,
        "is_active": False,
        "unsubscribe_token": secrets.token_urlsafe(32),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_sent_at": None,
    }
    await db.coach_pulse_subscriptions.insert_one(dict(sub))
    return sub


async def _personal_stats(user_id: str, since: datetime) -> dict:
    since_iso = since.isoformat()
    matches = await db.matches.count_documents({"user_id": user_id, "created_at": {"$gte": since_iso}})
    clips = await db.clips.count_documents({"user_id": user_id, "created_at": {"$gte": since_iso}})
    markers = await db.markers.count_documents({"user_id": user_id, "created_at": {"$gte": since_iso}})
    annotations = await db.annotations.count_documents({"user_id": user_id, "created_at": {"$gte": since_iso}})
    return {"matches": matches, "clips": clips, "markers": markers, "annotations": annotations}


async def _network_payload() -> tuple[bool, dict]:
    """Recompute a snapshot via the same logic as /api/coach-network/benchmarks."""
    # Light import to reuse the route's helper if present; otherwise compute inline
    from routes.coach_network import compute_benchmarks  # type: ignore
    data = await compute_benchmarks()
    return bool(data.get("ready")), data


async def _build_email_for(user: dict, network: dict, network_ready: bool) -> tuple[str, str, str]:
    """Returns (subject, html, unsubscribe_url) for one user."""
    sub = await _get_or_create_subscription(user["id"])
    week_start = _week_start()
    personal = await _personal_stats(user["id"], week_start)
    base = PUBLIC_BASE_URL.rstrip("/") or "https://video-scout-11.preview.emergentagent.com"
    unsubscribe_url = f"{base}/api/coach-pulse/unsubscribe/{sub['unsubscribe_token']}"
    subject, html = render_coach_pulse_email(
        coach_name=user.get("name", "Coach"),
        week_label=_week_label(),
        network_ready=network_ready,
        network=network,
        personal=personal,
        unsubscribe_url=unsubscribe_url,
    )
    return subject, html, unsubscribe_url


async def _send_via_resend(to_email: str, subject: str, html: str) -> str:
    """Route through the email queue so quota-exceeded failures get retried
    automatically instead of lost. Returns empty string if the email was
    queued (still a successful, user-visible outcome)."""
    from services.email_queue import send_or_queue
    if not resend.api_key:
        raise HTTPException(status_code=503, detail="Resend not configured (RESEND_API_KEY missing)")
    result = await send_or_queue(to_email, subject, html, kind="coach_pulse")
    if result["status"] == "sent":
        return result.get("email_id", "")
    if result["status"] == "quota_deferred":
        logger.warning("Coach Pulse email queued for %s (quota exhausted)", to_email)
        return ""  # Signal success — the queue will retry
    # permanent failure
    raise HTTPException(status_code=502, detail=f"Email send failed: {result.get('error')}")


# ---------- subscription endpoints ----------

@router.get("/coach-pulse/subscription")
async def get_subscription(current_user: dict = Depends(get_current_user)):
    sub = await _get_or_create_subscription(current_user["id"])
    return {
        "is_active": sub.get("is_active", False),
        "last_sent_at": sub.get("last_sent_at"),
        "email": current_user.get("email"),
    }


@router.post("/coach-pulse/subscribe")
async def subscribe(current_user: dict = Depends(get_current_user)):
    await _get_or_create_subscription(current_user["id"])
    await db.coach_pulse_subscriptions.update_one(
        {"user_id": current_user["id"]},
        {"$set": {"is_active": True, "subscribed_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"is_active": True}


@router.post("/coach-pulse/unsubscribe")
async def unsubscribe(current_user: dict = Depends(get_current_user)):
    await db.coach_pulse_subscriptions.update_one(
        {"user_id": current_user["id"]},
        {"$set": {"is_active": False, "unsubscribed_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"is_active": False}


@router.get("/coach-pulse/unsubscribe/{token}", response_class=HTMLResponse)
async def public_unsubscribe(token: str):
    """Public link for the email footer — no auth required."""
    result = await db.coach_pulse_subscriptions.update_one(
        {"unsubscribe_token": token},
        {"$set": {"is_active": False, "unsubscribed_at": datetime.now(timezone.utc).isoformat()}},
    )
    body = (
        "<h2>You're unsubscribed</h2><p>You will no longer receive Coach Pulse emails. "
        "You can re-subscribe any time from your dashboard.</p>"
        if result.matched_count
        else "<h2>Link expired</h2><p>This unsubscribe link is invalid or has expired.</p>"
    )
    return HTMLResponse(
        f'<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:520px;margin:80px auto;padding:24px;">{body}</body></html>'
    )


# ---------- preview / send ----------

@router.get("/coach-pulse/preview", response_class=HTMLResponse)
async def preview_email(current_user: dict = Depends(get_current_user)):
    network_ready, network = await _network_payload()
    _, html, _ = await _build_email_for(current_user, network, network_ready)
    return HTMLResponse(html)


@router.get("/coach-pulse/admin-preview/{user_id}", response_class=HTMLResponse)
async def admin_preview_email(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Admin-only: preview the weekly digest as it would be rendered for any
    given user. Powers the 'Preview Digest' button on the admin page so the
    owner can verify this Monday's blast before it fires at 08:00 UTC.
    """
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")
    target = await db.users.find_one(
        {"id": user_id}, {"_id": 0, "id": 1, "email": 1, "name": 1}
    )
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    network_ready, network = await _network_payload()
    _, html, _ = await _build_email_for(target, network, network_ready)
    return HTMLResponse(html)


@router.post("/coach-pulse/send-test")
async def send_test(current_user: dict = Depends(get_current_user)):
    if not current_user.get("email"):
        raise HTTPException(status_code=400, detail="No email on user account")
    network_ready, network = await _network_payload()
    subject, html, _ = await _build_email_for(current_user, network, network_ready)
    email_id = await _send_via_resend(current_user["email"], f"[Test] {subject}", html)
    await db.coach_pulse_logs.insert_one({
        "user_id": current_user["id"],
        "kind": "test",
        "email_id": email_id,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"status": "sent", "email_id": email_id, "to": current_user["email"]}


@router.post("/coach-pulse/send-weekly")
async def send_weekly(current_user: dict = Depends(get_current_user)):
    """Idempotent per-week blast to all active subscribers. Admin/owner only."""
    role = (current_user.get("role") or "").lower()
    if role not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Only admin/owner can trigger the weekly blast")
    return await run_weekly_blast(triggered_by=f"manual:{current_user.get('email')}")


async def run_weekly_blast(triggered_by: str = "scheduled") -> dict:
    """Core weekly-blast logic — callable from either the HTTP endpoint or the APScheduler job.
    Idempotent: skips users who already received the pulse this ISO week.
    """
    logger.info("Coach Pulse weekly blast starting (trigger=%s)", triggered_by)
    network_ready, network = await _network_payload()
    week_start = _week_start().isoformat()
    cursor = db.coach_pulse_subscriptions.find({"is_active": True}, {"_id": 0})
    sent, skipped = 0, 0
    async for sub in cursor:
        if sub.get("last_sent_at") and sub["last_sent_at"] >= week_start:
            skipped += 1
            continue
        user = await db.users.find_one({"id": sub["user_id"]}, {"_id": 0, "email": 1, "name": 1, "id": 1})
        if not user or not user.get("email"):
            skipped += 1
            continue
        try:
            subject, html, _ = await _build_email_for(user, network, network_ready)
            email_id = await _send_via_resend(user["email"], subject, html)
            now = datetime.now(timezone.utc).isoformat()
            await db.coach_pulse_subscriptions.update_one(
                {"user_id": user["id"]},
                {"$set": {"last_sent_at": now}},
            )
            await db.coach_pulse_logs.insert_one({
                "user_id": user["id"],
                "kind": "weekly",
                "email_id": email_id,
                "sent_at": now,
                "triggered_by": triggered_by,
            })
            sent += 1
        except Exception as e:
            logger.error("Failed to send weekly to %s: %s", user.get("email"), e)
            skipped += 1
    logger.info("Coach Pulse weekly blast done — sent=%d, skipped=%d", sent, skipped)
    return {"sent": sent, "skipped": skipped, "trigger": triggered_by}
