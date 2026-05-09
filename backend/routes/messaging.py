"""In-app messaging — conversation threads between coaches and scouts.

Design:
- A `message_threads` doc holds (id, participant_ids: [a, b], topic, last_message_at,
  unread_counts: {user_id: n}). Two participants only for v1 (1:1 threads).
- A `messages` doc holds (id, thread_id, sender_id, body, created_at, read_by: [user_ids]).
- Threads are auto-created from "Express Interest" on a scout listing, and can also
  be opened directly between any two registered users via POST /messages/open.

Endpoints:
- POST   /api/scout-listings/{id}/express-interest
- GET    /api/messages/threads             — list my threads, sorted by last_message_at desc
- POST   /api/messages/threads/open        — find-or-create a 1:1 thread with another user
- GET    /api/messages/threads/{id}        — full thread + 100 most recent messages
- POST   /api/messages/threads/{id}/reply  — append a message + bump last_message_at
- POST   /api/messages/threads/{id}/read   — mark unread=0 for the caller
- GET    /api/messages/unread-count        — for header bell badge

All endpoints require authentication. Message bodies are HTML-escaped on render
client-side; we store raw text and trim to 5KB to prevent abuse.
"""
from __future__ import annotations

import html
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from db import db
from routes.auth import get_current_user
from services.email_queue import send_or_queue

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_BODY = 5000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_app_url() -> str:
    return os.environ.get("PUBLIC_APP_URL", "").rstrip("/")


# ---------- models ----------

class OpenThreadRequest(BaseModel):
    other_user_id: str = Field(min_length=1, max_length=128)
    topic: Optional[str] = Field(default=None, max_length=240)
    initial_message: Optional[str] = Field(default=None, max_length=MAX_BODY)


class ReplyRequest(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_BODY)


class ExpressInterestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=10, max_length=MAX_BODY)
    player_dossier_share_token: Optional[str] = Field(default=None, max_length=80)


# ---------- helpers ----------

async def _hydrate_participants(thread: dict) -> dict:
    pids: List[str] = thread.get("participant_ids", []) or []
    users = await db.users.find(
        {"id": {"$in": pids}}, {"_id": 0, "id": 1, "name": 1, "role": 1}
    ).to_list(10)
    by_id = {u["id"]: u for u in users}
    thread["participants"] = [by_id.get(pid, {"id": pid, "name": "Deleted user"}) for pid in pids]
    return thread


async def _list_threads(user_id: str) -> List[dict]:
    threads = await db.message_threads.find(
        {"participant_ids": user_id}, {"_id": 0}
    ).sort("last_message_at", -1).to_list(100)
    for t in threads:
        await _hydrate_participants(t)
        t["my_unread"] = (t.get("unread_counts") or {}).get(user_id, 0)
    return threads


async def _find_or_create_thread(user_a: str, user_b: str, topic: Optional[str] = None) -> dict:
    """1:1 thread keyed by sorted participant pair so duplicates are impossible."""
    if user_a == user_b:
        raise HTTPException(status_code=400, detail="Cannot start a thread with yourself.")
    pair = sorted([user_a, user_b])
    existing = await db.message_threads.find_one({
        "participant_pair": pair,
    }, {"_id": 0})
    if existing:
        return existing

    thread = {
        "id": str(uuid.uuid4()),
        "participant_ids": pair,
        "participant_pair": pair,
        "topic": (topic or "").strip() or None,
        "created_at": _now_iso(),
        "last_message_at": _now_iso(),
        "last_message_preview": "",
        "unread_counts": {pair[0]: 0, pair[1]: 0},
    }
    await db.message_threads.insert_one(dict(thread))
    thread.pop("_id", None)
    return thread


async def _append_message(
    thread_id: str, sender_id: str, recipient_id: str, body: str
) -> dict:
    msg = {
        "id": str(uuid.uuid4()),
        "thread_id": thread_id,
        "sender_id": sender_id,
        "body": body,
        "created_at": _now_iso(),
        "read_by": [sender_id],
    }
    await db.messages.insert_one(dict(msg))

    preview = (body or "").strip().replace("\n", " ")
    if len(preview) > 120:
        preview = preview[:117] + "…"
    await db.message_threads.update_one(
        {"id": thread_id},
        {
            "$set": {
                "last_message_at": msg["created_at"],
                "last_message_preview": preview,
            },
            "$inc": {f"unread_counts.{recipient_id}": 1},
        },
    )
    msg.pop("_id", None)
    return msg


# ---------- thread endpoints ----------

@router.get("/messages/threads")
async def list_my_threads(current_user: dict = Depends(get_current_user)):
    return await _list_threads(current_user["id"])


@router.get("/messages/unread-count")
async def my_unread_count(current_user: dict = Depends(get_current_user)):
    """Aggregate unread across all my threads — drives the header badge."""
    pipeline = [
        {"$match": {"participant_ids": current_user["id"]}},
        {"$project": {"u": {"$ifNull": [f"$unread_counts.{current_user['id']}", 0]}}},
        {"$group": {"_id": None, "total": {"$sum": "$u"}}},
    ]
    cursor = db.message_threads.aggregate(pipeline)
    total = 0
    async for row in cursor:
        total = row.get("total", 0)
    return {"unread": total}


@router.post("/messages/threads/open")
async def open_thread(body: OpenThreadRequest, current_user: dict = Depends(get_current_user)):
    other = await db.users.find_one({"id": body.other_user_id}, {"_id": 0, "id": 1})
    if not other:
        raise HTTPException(status_code=404, detail="Recipient not found")
    thread = await _find_or_create_thread(current_user["id"], body.other_user_id, body.topic)

    if body.initial_message and body.initial_message.strip():
        await _append_message(
            thread["id"], current_user["id"], body.other_user_id,
            body.initial_message.strip(),
        )

    thread = await db.message_threads.find_one({"id": thread["id"]}, {"_id": 0})
    await _hydrate_participants(thread)
    return thread


@router.get("/messages/threads/{thread_id}")
async def get_thread(thread_id: str, current_user: dict = Depends(get_current_user)):
    thread = await db.message_threads.find_one(
        {"id": thread_id, "participant_ids": current_user["id"]}, {"_id": 0}
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    await _hydrate_participants(thread)

    messages = await db.messages.find(
        {"thread_id": thread_id}, {"_id": 0}
    ).sort("created_at", 1).to_list(100)

    thread["messages"] = messages
    return thread


@router.post("/messages/threads/{thread_id}/reply")
async def reply_to_thread(
    thread_id: str,
    body: ReplyRequest,
    current_user: dict = Depends(get_current_user),
):
    thread = await db.message_threads.find_one(
        {"id": thread_id, "participant_ids": current_user["id"]},
        {"_id": 0, "participant_ids": 1},
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    other = next(
        (pid for pid in thread["participant_ids"] if pid != current_user["id"]),
        None,
    )
    if not other:
        raise HTTPException(status_code=400, detail="Thread is missing recipient.")
    msg = await _append_message(thread_id, current_user["id"], other, body.body.strip())
    return msg


@router.post("/messages/threads/{thread_id}/read")
async def mark_thread_read(thread_id: str, current_user: dict = Depends(get_current_user)):
    thread = await db.message_threads.find_one(
        {"id": thread_id, "participant_ids": current_user["id"]},
        {"_id": 0, "id": 1},
    )
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    await db.message_threads.update_one(
        {"id": thread_id},
        {"$set": {f"unread_counts.{current_user['id']}": 0}},
    )
    return {"status": "ok"}


# ---------- express interest ----------

async def _resolve_dossier_url(
    share_token: Optional[str], owner_user_id: str
) -> Optional[str]:
    """Verify the dossier belongs to the caller, then build the public URL.

    Returns None if no token was supplied. Raises 404 for bogus / cross-user
    tokens — kept identical to the previous error message so callers don't
    break.
    """
    if not share_token:
        return None
    player = await db.players.find_one(
        {"share_token": share_token, "user_id": owner_user_id},
        {"_id": 0, "id": 1, "name": 1},
    )
    if not player:
        raise HTTPException(
            status_code=404,
            detail="Player dossier not found or not yours to share.",
        )
    base = _public_app_url()
    return f"{base}/player/{share_token}" if base else f"/player/{share_token}"


def _build_interest_email_html(
    school_name: str,
    coach_name: str,
    raw_message: str,
    inbox_url: str,
    dossier_url: Optional[str],
) -> str:
    """Render the scout-notification email body."""
    safe_name = html.escape(coach_name or "A coach")
    safe_school = html.escape(school_name)
    safe_message = html.escape(raw_message).replace("\n", "<br/>")
    safe_dossier = html.escape(dossier_url, quote=True) if dossier_url else None
    safe_inbox = html.escape(inbox_url, quote=True)
    dossier_block = (
        f'<p style="margin:18px 0 0 0;font-size:13px;color:#10B981;">'
        f'<a href="{safe_dossier}" style="color:#10B981;text-decoration:none;">📎 View player dossier →</a></p>'
    ) if safe_dossier else ""
    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;color:#EAEAEA;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:40px 16px;">
  <table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#141414;border:1px solid rgba(255,255,255,0.1);">
    <tr><td style="padding:32px 32px 8px 32px;">
      <div style="font-family:Bebas Neue,Impact,sans-serif;font-size:30px;letter-spacing:2px;color:#10B981;">NEW INTEREST</div>
      <div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#888;margin-top:4px;">Scout Board · {safe_school}</div>
    </td></tr>
    <tr><td style="padding:8px 32px 8px 32px;">
      <p style="margin:0 0 12px 0;font-size:15px;line-height:1.6;color:#CFCFCF;"><strong style="color:#fff;">{safe_name}</strong> sent you a message about your listing.</p>
      <div style="margin:18px 0;padding:18px;background:#0A0A0A;border-left:3px solid #10B981;font-size:14px;line-height:1.7;color:#EAEAEA;">{safe_message}</div>
      {dossier_block}
    </td></tr>
    <tr><td style="padding:24px 32px;">
      <a href="{safe_inbox}" style="display:inline-block;background:#10B981;color:#ffffff;padding:14px 28px;text-decoration:none;font-weight:700;font-size:13px;letter-spacing:1.5px;text-transform:uppercase;">Reply in App →</a>
    </td></tr>
    <tr><td style="padding:18px 32px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:#666;line-height:1.5;">
      Soccer Scout 11 · You receive this because you posted a recruiting listing.
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


async def _record_contact_click_view(listing_id: str, user_id: str) -> None:
    """Counts toward the listing's contact_clicks_7d metric and weekly digest."""
    await db.scout_listing_views.insert_one({
        "listing_id": listing_id,
        "viewer_key": f"u:{user_id}",
        "viewer_user_id": user_id,
        "event": "contact_click",
        "viewed_at": _now_iso(),
    })


@router.post("/scout-listings/{listing_id}/express-interest")
async def express_interest(
    listing_id: str,
    body: ExpressInterestRequest,
    current_user: dict = Depends(get_current_user),
):
    """Coach reaches out to a scout's listing.

    Side-effects:
      1. Open (or reuse) an in-app message thread between coach and scout.
      2. Append the coach's message (with optional dossier link) to the thread.
      3. Email the scout a pre-formatted notification with the thread link
         and (optionally) the player dossier share URL.
      4. Record a `contact_click` view for the digest metric.
    """
    listing = await db.scout_listings.find_one(
        {"id": listing_id}, {"_id": 0, "id": 1, "user_id": 1, "school_name": 1},
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing["user_id"] == current_user["id"]:
        raise HTTPException(status_code=400, detail="You can't send interest to your own listing.")

    scout = await db.users.find_one(
        {"id": listing["user_id"]}, {"_id": 0, "id": 1, "name": 1, "email": 1},
    )
    if not scout:
        raise HTTPException(status_code=404, detail="Listing owner not found")

    dossier_url = await _resolve_dossier_url(body.player_dossier_share_token, current_user["id"])
    full_message = body.message.strip()
    if dossier_url:
        full_message += f"\n\n— View player dossier: {dossier_url}"

    thread = await _find_or_create_thread(
        current_user["id"], listing["user_id"], f"Interest: {listing['school_name']}",
    )
    await _append_message(thread["id"], current_user["id"], listing["user_id"], full_message)

    base = _public_app_url()
    inbox_url = f"{base}/messages/{thread['id']}" if base else f"/messages/{thread['id']}"
    email_html = _build_interest_email_html(
        listing["school_name"], current_user.get("name", "A coach"),
        body.message.strip(), inbox_url, dossier_url,
    )
    try:
        await send_or_queue(
            to_email=scout["email"],
            subject=f"{current_user.get('name','A coach')} is interested in {listing['school_name']}",
            html=email_html,
            kind="scout_interest",
            metadata={
                "listing_id": listing_id,
                "from_user_id": current_user["id"],
                "thread_id": thread["id"],
            },
        )
    except Exception as e:
        logger.warning("[express_interest] email send failed: %s", e)

    await _record_contact_click_view(listing_id, current_user["id"])

    return {
        "status": "sent",
        "thread_id": thread["id"],
        "scout_name": scout.get("name"),
    }
