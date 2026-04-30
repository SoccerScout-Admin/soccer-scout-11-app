"""Web Push notification service.

Handles VAPID-signed push sends via pywebpush. Stores subscriptions in MongoDB.
Designed for fire-and-forget usage from other routes (match processing, clip shares).
"""
from __future__ import annotations
import os
import json
import asyncio
import logging
from typing import Optional
from datetime import datetime, timezone
from pywebpush import webpush, WebPushException
from db import db

logger = logging.getLogger(__name__)

VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY_PATH = os.environ.get("VAPID_PRIVATE_KEY_PATH", "")
VAPID_CONTACT_EMAIL = os.environ.get("VAPID_CONTACT_EMAIL", "mailto:admin@example.com")

_vapid_private_pem: Optional[str] = None


def _load_private_key() -> Optional[str]:
    global _vapid_private_pem
    if _vapid_private_pem is not None:
        return _vapid_private_pem
    if not VAPID_PRIVATE_KEY_PATH or not os.path.exists(VAPID_PRIVATE_KEY_PATH):
        return None
    with open(VAPID_PRIVATE_KEY_PATH, "r") as f:
        _vapid_private_pem = f.read()
    return _vapid_private_pem


def is_configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and _load_private_key())


def _send_sync(subscription_info: dict, payload: dict) -> tuple[bool, str]:
    """Blocking webpush call — always run in a thread."""
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=_load_private_key(),
            vapid_claims={"sub": VAPID_CONTACT_EMAIL},
            ttl=60 * 60 * 24,  # 24h delivery window
        )
        return True, "ok"
    except WebPushException as e:
        status = getattr(e.response, "status_code", 0) if getattr(e, "response", None) else 0
        return False, f"webpush-{status}"
    except Exception as e:
        return False, str(e)[:100]


async def send_to_user(user_id: str, title: str, body: str, url: str = "/") -> dict:
    """Send a push to every subscription the user has. Returns {sent, removed, failed}."""
    if not is_configured():
        logger.warning("push not configured — skipping send to %s", user_id)
        return {"sent": 0, "removed": 0, "failed": 0, "reason": "not_configured"}

    subs = await db.push_subscriptions.find({"user_id": user_id}, {"_id": 0}).to_list(20)
    if not subs:
        return {"sent": 0, "removed": 0, "failed": 0, "reason": "no_subscriptions"}

    sent = failed = removed = 0
    payload = {"title": title, "body": body, "url": url}

    for sub in subs:
        sub_info = {
            "endpoint": sub["endpoint"],
            "keys": sub.get("keys", {}),
        }
        ok, reason = await asyncio.to_thread(_send_sync, sub_info, payload)
        if ok:
            sent += 1
            await db.push_subscriptions.update_one(
                {"endpoint": sub["endpoint"]},
                {"$set": {"last_sent_at": datetime.now(timezone.utc).isoformat()}},
            )
        else:
            # 410 Gone / 404 = subscription expired; remove from DB
            if "410" in reason or "404" in reason:
                await db.push_subscriptions.delete_one({"endpoint": sub["endpoint"]})
                removed += 1
            else:
                failed += 1
            logger.info("push failed user=%s reason=%s", user_id, reason)

    return {"sent": sent, "removed": removed, "failed": failed}
