"""Scout listings — view tracking + weekly digest email.

What this service does:
1. **Track views**: every public/authed visit to a listing detail page is recorded
   in `scout_listing_views` with a 24h debounce per (listing_id, viewer_key).
2. **Listing insights**: owners can fetch 7-day / 30-day rollups for their listings.
3. **Weekly digest**: every Monday a Resend email is sent to each scout summarising
   their listings' view + click stats from the past 7 days. Listings with 0 views
   in the past week still get a "still pending" / "consider editing" nudge.

The digest is dispatched through `services/email_queue.send_or_queue` so Resend
quota deferrals don't drop the email.
"""
from __future__ import annotations

import hashlib
import html
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from db import db
from services.email_queue import send_or_queue

logger = logging.getLogger(__name__)

VIEW_DEDUPE_WINDOW = timedelta(hours=24)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _viewer_key(viewer_user_id: Optional[str], anon_fingerprint: Optional[str]) -> str:
    """Stable identifier per viewer — user_id if logged in, else hashed IP+UA."""
    if viewer_user_id:
        return f"u:{viewer_user_id}"
    if anon_fingerprint:
        return f"a:{hashlib.sha256(anon_fingerprint.encode('utf-8')).hexdigest()[:16]}"
    return "a:unknown"


async def record_view(
    listing_id: str,
    viewer_user_id: Optional[str] = None,
    anon_fingerprint: Optional[str] = None,
    event: str = "view",
) -> bool:
    """Record a listing view if no recent view exists from the same viewer.

    Returns True when a new view was recorded, False if dedup'd.
    `event` can be "view" or "contact_click" so we can distinguish hot interest.
    """
    key = _viewer_key(viewer_user_id, anon_fingerprint)
    cutoff = (datetime.now(timezone.utc) - VIEW_DEDUPE_WINDOW).isoformat()
    recent = await db.scout_listing_views.find_one({
        "listing_id": listing_id,
        "viewer_key": key,
        "event": event,
        "viewed_at": {"$gt": cutoff},
    })
    if recent:
        return False
    await db.scout_listing_views.insert_one({
        "listing_id": listing_id,
        "viewer_key": key,
        "viewer_user_id": viewer_user_id,
        "event": event,
        "viewed_at": _now_iso(),
    })
    return True


# ===== Highlight Reel view tracking (mirrors record_view above) =====

async def record_reel_view(
    reel_id: str,
    viewer_user_id: Optional[str] = None,
    anon_fingerprint: Optional[str] = None,
) -> bool:
    """Record a unique view for a highlight reel, with 24h debounce per viewer."""
    key = _viewer_key(viewer_user_id, anon_fingerprint)
    cutoff = (datetime.now(timezone.utc) - VIEW_DEDUPE_WINDOW).isoformat()
    recent = await db.highlight_reel_views.find_one({
        "reel_id": reel_id,
        "viewer_key": key,
        "viewed_at": {"$gt": cutoff},
    })
    if recent:
        return False
    await db.highlight_reel_views.insert_one({
        "reel_id": reel_id,
        "viewer_key": key,
        "viewer_user_id": viewer_user_id,
        "viewed_at": _now_iso(),
    })
    return True


async def trending_reel_ids(window_days: int = 7, limit: int = 12) -> list:
    """Return reel ids sorted by unique-view count over the last `window_days`."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    pipeline = [
        {"$match": {"viewed_at": {"$gt": cutoff}}},
        {"$group": {"_id": "$reel_id", "view_count": {"$sum": 1}}},
        {"$sort": {"view_count": -1}},
        {"$limit": int(limit)},
    ]
    rows = await db.highlight_reel_views.aggregate(pipeline).to_list(int(limit))
    return [{"reel_id": r["_id"], "view_count": r["view_count"]} for r in rows]


async def reel_view_count(reel_id: str, window_days: Optional[int] = None) -> int:
    """Distinct view count for a single reel, optionally bounded by a window."""
    query = {"reel_id": reel_id}
    if window_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        query["viewed_at"] = {"$gt": cutoff}
    return await db.highlight_reel_views.count_documents(query)



async def listing_insights(listing_id: str) -> dict:
    """Return view + click counts for a listing across rolling windows."""
    now = datetime.now(timezone.utc)
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    cutoff_30d = (now - timedelta(days=30)).isoformat()

    # Total views (all time)
    total = await db.scout_listing_views.count_documents({
        "listing_id": listing_id, "event": "view",
    })
    last_7 = await db.scout_listing_views.count_documents({
        "listing_id": listing_id, "event": "view", "viewed_at": {"$gt": cutoff_7d},
    })
    last_30 = await db.scout_listing_views.count_documents({
        "listing_id": listing_id, "event": "view", "viewed_at": {"$gt": cutoff_30d},
    })

    # Unique authed viewers in 7d
    pipeline = [
        {"$match": {
            "listing_id": listing_id,
            "event": "view",
            "viewer_user_id": {"$ne": None},
            "viewed_at": {"$gt": cutoff_7d},
        }},
        {"$group": {"_id": "$viewer_user_id"}},
        {"$count": "n"},
    ]
    cursor = db.scout_listing_views.aggregate(pipeline)
    unique_authed = 0
    async for row in cursor:
        unique_authed = row.get("n", 0)

    contact_clicks_7d = await db.scout_listing_views.count_documents({
        "listing_id": listing_id, "event": "contact_click", "viewed_at": {"$gt": cutoff_7d},
    })

    return {
        "views_total": total,
        "views_7d": last_7,
        "views_30d": last_30,
        "unique_coaches_7d": unique_authed,
        "contact_clicks_7d": contact_clicks_7d,
    }


async def my_listings_with_insights(user_id: str) -> list:
    listings = await db.scout_listings.find(
        {"user_id": user_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)

    for listing in listings:
        listing["insights"] = await listing_insights(listing["id"])
    return listings


# ---------- Weekly digest ----------

def _public_app_url() -> str:
    return os.environ.get("PUBLIC_APP_URL", "").rstrip("/")


def _build_digest_html(scout_name: str, items: list) -> str:
    """Email body listing the scout's listings with the past 7d stats."""
    base = _public_app_url()
    safe_name = html.escape(scout_name or "Coach")

    rows = []
    for item in items:
        listing = item["listing"]
        ins = item["insights"]
        link = f"{base}/scouts/{listing['id']}" if base else f"/scouts/{listing['id']}"
        verified_chip = (
            '<span style="display:inline-block;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;background:rgba(16,185,129,0.15);color:#10B981;padding:2px 8px;margin-left:6px;">Verified</span>'
            if listing.get("verified")
            else '<span style="display:inline-block;font-size:10px;letter-spacing:1.5px;text-transform:uppercase;background:rgba(251,191,36,0.15);color:#FBBF24;padding:2px 8px;margin-left:6px;">Pending</span>'
        )
        positions = ", ".join(listing.get("positions") or []) or "—"
        rows.append(f"""
<tr><td style="padding:18px 0;border-top:1px solid rgba(255,255,255,0.06);">
  <div style="font-size:18px;font-weight:700;color:#ffffff;">
    <a href="{html.escape(link, quote=True)}" style="color:#ffffff;text-decoration:none;">{html.escape(listing['school_name'])}</a>
    {verified_chip}
  </div>
  <div style="font-size:12px;color:#888;margin-top:2px;">{html.escape(listing.get('level',''))} · {html.escape(listing.get('region',''))} · Positions: {html.escape(positions)}</div>
  <table style="margin-top:10px;width:100%;" cellpadding="0" cellspacing="0">
    <tr>
      <td style="padding:6px 14px 6px 0;font-size:24px;font-weight:700;color:#10B981;">{ins['views_7d']}</td>
      <td style="padding:6px 14px 6px 0;font-size:11px;color:#888;letter-spacing:1.2px;text-transform:uppercase;vertical-align:bottom;">Views<br/>past 7d</td>
      <td style="padding:6px 14px 6px 0;font-size:24px;font-weight:700;color:#007AFF;">{ins['unique_coaches_7d']}</td>
      <td style="padding:6px 14px 6px 0;font-size:11px;color:#888;letter-spacing:1.2px;text-transform:uppercase;vertical-align:bottom;">Unique<br/>coaches</td>
      <td style="padding:6px 14px 6px 0;font-size:24px;font-weight:700;color:#FBBF24;">{ins['contact_clicks_7d']}</td>
      <td style="padding:6px 14px 6px 0;font-size:11px;color:#888;letter-spacing:1.2px;text-transform:uppercase;vertical-align:bottom;">Contact<br/>clicks</td>
    </tr>
  </table>
</td></tr>
""")

    rows_html = "".join(rows) if rows else """
<tr><td style="padding:24px 0;text-align:center;color:#888;font-size:14px;">
  You don't have any active listings yet.
  <br/><br/>
  <a href="{base}/scouts/new" style="color:#10B981;font-weight:700;text-decoration:none;">Post your first listing →</a>
</td></tr>
""".replace("{base}", base or "")

    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;color:#EAEAEA;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:40px 16px;">
  <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#141414;border:1px solid rgba(255,255,255,0.1);">
    <tr><td style="padding:32px 32px 16px 32px;">
      <div style="font-family:Bebas Neue,Impact,sans-serif;font-size:30px;letter-spacing:2px;color:#10B981;">SCOUT BOARD WEEKLY</div>
      <div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#888;margin-top:4px;">Recruiting digest · {datetime.now(timezone.utc).strftime('%b %d, %Y')}</div>
    </td></tr>
    <tr><td style="padding:0 32px 8px 32px;">
      <h1 style="margin:0 0 8px 0;font-size:22px;font-weight:700;color:#ffffff;">Hi {safe_name},</h1>
      <p style="margin:0 0 16px 0;font-size:14px;line-height:1.6;color:#CFCFCF;">Here's how your recruiting listings performed in the past 7 days.</p>
    </td></tr>
    <tr><td style="padding:0 32px 24px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0">{rows_html}</table>
    </td></tr>
    <tr><td style="padding:0 32px 32px 32px;">
      <div style="margin-top:8px;border-top:1px solid rgba(255,255,255,0.06);padding-top:20px;">
        <a href="{html.escape(base or '/', quote=True)}/scouts" style="display:inline-block;background:#10B981;color:#ffffff;padding:14px 24px;text-decoration:none;font-weight:700;font-size:13px;letter-spacing:1.5px;text-transform:uppercase;">Open Scout Board</a>
      </div>
    </td></tr>
    <tr><td style="padding:18px 32px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:#666;line-height:1.5;">
      Soccer Scout 11 · You receive this digest because you have a registered scout / college coach account. To stop, edit your account settings.
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


async def send_weekly_digest(triggered_by: str = "manual") -> dict:
    """Send the weekly scout digest to every scout-role user.

    Returns {scouts_total, sent, queued, skipped, errors}.
    """
    counts = {"scouts_total": 0, "sent": 0, "queued": 0, "skipped": 0, "errors": 0}

    cursor = db.users.find(
        {"role": {"$in": ["scout", "college_coach"]}},
        {"_id": 0, "id": 1, "email": 1, "name": 1},
    )
    async for user in cursor:
        counts["scouts_total"] += 1
        listings = await db.scout_listings.find(
            {"user_id": user["id"]}, {"_id": 0}
        ).sort("created_at", -1).to_list(20)

        # Skip scouts with zero listings AND zero recent views — nothing to say
        items = []
        for listing in listings:
            ins = await listing_insights(listing["id"])
            items.append({"listing": listing, "insights": ins})
        any_recent = any(it["insights"]["views_7d"] > 0 for it in items)
        if not items and triggered_by == "apscheduler":
            counts["skipped"] += 1
            continue
        if items and not any_recent and triggered_by == "apscheduler":
            # Only nudge once a month — skip silent weeks
            counts["skipped"] += 1
            continue

        try:
            html_body = _build_digest_html(user.get("name", "Coach"), items)
            res = await send_or_queue(
                to_email=user["email"],
                subject="Your Scout Board weekly digest",
                html=html_body,
                kind="scout_digest",
                metadata={"user_id": user["id"], "triggered_by": triggered_by},
            )
            if res.get("status") == "sent":
                counts["sent"] += 1
            else:
                counts["queued"] += 1
        except Exception as e:
            logger.error("[scout_digest] error sending to %s: %s", user.get("email"), e)
            counts["errors"] += 1

    logger.info("[scout_digest] triggered_by=%s result=%s", triggered_by, counts)
    return counts
