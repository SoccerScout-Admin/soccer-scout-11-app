"""Push notification endpoints — VAPID public key + subscription CRUD + test send."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from db import db
from routes.auth import get_current_user
from services.push_notifications import send_to_user, is_configured

router = APIRouter()

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeInput(BaseModel):
    endpoint: str = Field(..., min_length=10, max_length=500)
    keys: PushKeys


class UnsubscribeInput(BaseModel):
    endpoint: str = Field(..., min_length=10, max_length=500)


@router.get("/push/vapid-key")
async def get_vapid_public_key():
    """Public endpoint — frontend needs this to call pushManager.subscribe()."""
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="Push not configured")
    return {"public_key": VAPID_PUBLIC_KEY, "configured": is_configured()}


@router.post("/push/subscribe")
async def subscribe(input: SubscribeInput, current_user: dict = Depends(get_current_user)):
    """Upsert a push subscription for the current user. Endpoint is the unique key."""
    now = datetime.now(timezone.utc).isoformat()
    await db.push_subscriptions.update_one(
        {"endpoint": input.endpoint},
        {
            "$set": {
                "user_id": current_user["id"],
                "endpoint": input.endpoint,
                "keys": {"p256dh": input.keys.p256dh, "auth": input.keys.auth},
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now, "last_sent_at": None},
        },
        upsert=True,
    )
    return {"subscribed": True}


@router.post("/push/unsubscribe")
async def unsubscribe(input: UnsubscribeInput, current_user: dict = Depends(get_current_user)):
    result = await db.push_subscriptions.delete_one(
        {"endpoint": input.endpoint, "user_id": current_user["id"]}
    )
    return {"deleted": result.deleted_count}


@router.get("/push/subscriptions")
async def list_subscriptions(current_user: dict = Depends(get_current_user)):
    """Returns the count — the frontend just needs to know if any subscription exists."""
    count = await db.push_subscriptions.count_documents({"user_id": current_user["id"]})
    return {"count": count, "configured": is_configured()}


@router.post("/push/send-test")
async def send_test(current_user: dict = Depends(get_current_user)):
    """Send a ping to all of the current user's registered devices."""
    result = await send_to_user(
        user_id=current_user["id"],
        title="Soccer Scout 11 — test push",
        body="Push notifications are working. You'll be notified when AI analysis finishes.",
        url="/",
    )
    return result
