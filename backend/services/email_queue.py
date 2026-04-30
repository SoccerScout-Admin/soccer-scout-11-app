"""Email queue with quota-exhaustion fallback.

When the Resend API key hits its free-tier quota, a naive send raises and the
email is lost forever. This module wraps every send through a MongoDB-backed
queue:

- `send_or_queue(...)` tries Resend immediately; on a quota-style error it
  persists the email to `email_queue` collection with status `quota_deferred`
  and a `next_retry_at` in the future. On any other error it persists as
  `failed` (attempts bumped).

- `process_queue(now)` (called by APScheduler every 30 min) retries
  `quota_deferred` and `failed` emails whose `next_retry_at` is due. Sent
  emails get `status="sent"` with `email_id` and `sent_at` set.

- `get_queue_depth()` / `list_queue(limit)` / `retry_now(email_id)` expose
  queue visibility to the admin UI.

A "quota" error is detected by a regex match on the exception string — Resend
returns HTTP 422 with messages containing "daily_quota", "monthly_quota", or
"rate_limit_exceeded" when the free tier is exhausted.
"""
from __future__ import annotations

import os
import re
import asyncio
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional

from db import db

logger = logging.getLogger(__name__)

_QUOTA_PATTERNS = re.compile(
    r"(daily_quota|monthly_quota|rate_limit|quota.?exceeded|429|too_many_requests)",
    re.IGNORECASE,
)

# Backoff schedule (hours) — index by attempt number (capped at last)
_BACKOFF_HOURS = [1, 4, 12, 24, 72]


def _resend_api_key() -> str:
    return os.environ.get("RESEND_API_KEY", "")


def _sender_email() -> str:
    return os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_quota_error(exc: Exception) -> bool:
    return bool(_QUOTA_PATTERNS.search(str(exc)))


def _next_retry(attempts: int, quota: bool) -> datetime:
    """Quota errors wait longer (daily quota resets at midnight UTC).
    Other failures follow the normal backoff schedule."""
    if quota:
        # Schedule for next hour at x:05 — Resend daily quota resets at UTC midnight,
        # so by probing hourly we'll catch recovery within ~60 min of the reset.
        hours = 1
    else:
        idx = min(attempts, len(_BACKOFF_HOURS) - 1)
        hours = _BACKOFF_HOURS[idx]
    return datetime.now(timezone.utc) + timedelta(hours=hours)


async def _resend_send(to_email: str, subject: str, html: str) -> str:
    """Raw Resend send. Returns email_id on success, raises on error."""
    import resend

    api_key = _resend_api_key()
    if not api_key:
        raise RuntimeError("RESEND_API_KEY not configured")
    resend.api_key = api_key
    params = {
        "from": _sender_email(),
        "to": [to_email],
        "subject": subject,
        "html": html,
    }
    resp = await asyncio.to_thread(resend.Emails.send, params)
    return (resp or {}).get("id", "")


async def send_or_queue(
    to_email: str,
    subject: str,
    html: str,
    kind: str = "generic",
    metadata: Optional[dict] = None,
) -> dict:
    """Try to send via Resend. On quota/transient errors, persist to the queue.

    Returns dict with:
      - status: "sent" | "quota_deferred" | "failed"
      - email_id: str (on sent)
      - queue_id: str (on queue)
      - error: str (on failure)
    """
    queue_id = f"eq-{secrets.token_urlsafe(12)}"
    base_doc = {
        "id": queue_id,
        "to_email": to_email,
        "subject": subject,
        "html": html,
        "kind": kind,
        "metadata": metadata or {},
        "created_at": _now_iso(),
        "attempts": 0,
        "last_error": None,
    }

    if not _resend_api_key():
        base_doc.update({"status": "failed", "last_error": "RESEND_API_KEY missing"})
        await db.email_queue.insert_one(dict(base_doc))
        return {"status": "failed", "queue_id": queue_id, "error": "RESEND_API_KEY missing"}

    try:
        email_id = await _resend_send(to_email, subject, html)
        base_doc.update({
            "status": "sent",
            "attempts": 1,
            "email_id": email_id,
            "sent_at": _now_iso(),
        })
        await db.email_queue.insert_one(dict(base_doc))
        return {"status": "sent", "queue_id": queue_id, "email_id": email_id}
    except Exception as e:
        quota = _is_quota_error(e)
        next_retry_at = _next_retry(attempts=1, quota=quota)
        base_doc.update({
            "status": "quota_deferred" if quota else "failed",
            "attempts": 1,
            "last_error": str(e)[:500],
            "next_retry_at": next_retry_at.isoformat(),
        })
        await db.email_queue.insert_one(dict(base_doc))
        logger.warning(
            "[email_queue] send failed (%s) — queued id=%s for retry at %s",
            "quota" if quota else "transient",
            queue_id,
            next_retry_at.isoformat(),
        )
        return {
            "status": base_doc["status"],
            "queue_id": queue_id,
            "error": str(e),
        }


async def _retry_one(doc: dict) -> dict:
    """Retry a single queued email. Mutates `email_queue` collection in place."""
    try:
        email_id = await _resend_send(doc["to_email"], doc["subject"], doc["html"])
        await db.email_queue.update_one(
            {"id": doc["id"]},
            {"$set": {
                "status": "sent",
                "email_id": email_id,
                "sent_at": _now_iso(),
                "last_error": None,
            },
             "$inc": {"attempts": 1}},
        )
        return {"id": doc["id"], "status": "sent"}
    except Exception as e:
        quota = _is_quota_error(e)
        attempts = doc.get("attempts", 0) + 1
        # Give up after 5 attempts for non-quota errors. Quota retries indefinitely.
        give_up = not quota and attempts >= 5
        new_status = "failed_permanent" if give_up else ("quota_deferred" if quota else "failed")
        await db.email_queue.update_one(
            {"id": doc["id"]},
            {"$set": {
                "status": new_status,
                "last_error": str(e)[:500],
                "next_retry_at": _next_retry(attempts, quota).isoformat() if not give_up else None,
            },
             "$inc": {"attempts": 1}},
        )
        return {"id": doc["id"], "status": new_status, "error": str(e)[:200]}


async def process_queue(limit: int = 100) -> dict:
    """Retry all due emails. Called by APScheduler every 30 min."""
    now_iso = _now_iso()
    cursor = db.email_queue.find(
        {
            "status": {"$in": ["quota_deferred", "failed"]},
            "next_retry_at": {"$lte": now_iso},
        },
        {"_id": 0},
    ).limit(limit)
    docs = await cursor.to_list(length=limit)

    if not docs:
        return {"processed": 0, "sent": 0, "failed": 0}

    sent = 0
    failed = 0
    for doc in docs:
        result = await _retry_one(doc)
        if result["status"] == "sent":
            sent += 1
        else:
            failed += 1

    logger.info("[email_queue] processed %d — sent=%d, failed=%d", len(docs), sent, failed)
    return {"processed": len(docs), "sent": sent, "failed": failed}


async def get_queue_depth() -> dict:
    """Return counts by status — powers admin dashboard."""
    pipeline = [{"$group": {"_id": "$status", "count": {"$sum": 1}}}]
    result = {}
    async for doc in db.email_queue.aggregate(pipeline):
        result[doc["_id"]] = doc["count"]
    return {
        "sent": result.get("sent", 0),
        "quota_deferred": result.get("quota_deferred", 0),
        "failed": result.get("failed", 0),
        "failed_permanent": result.get("failed_permanent", 0),
        "total": sum(result.values()),
    }


async def list_queue(limit: int = 50, status: Optional[str] = None) -> list[dict]:
    """Return recent queued emails (newest first) for admin UI."""
    query = {}
    if status:
        query["status"] = status
    cursor = db.email_queue.find(query, {"_id": 0, "html": 0}).sort("created_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


async def retry_now(queue_id: str) -> dict:
    """Admin-triggered immediate retry of a specific queued email."""
    doc = await db.email_queue.find_one({"id": queue_id}, {"_id": 0})
    if not doc:
        return {"status": "not_found"}
    if doc.get("status") == "sent":
        return {"status": "already_sent"}
    return await _retry_one(doc)
