"""Weekly Reel Recap email — re-engagement loop for coaches.

For every user who has at least one shared reel with views in the past 7
days, builds a personalised email summarising:
  - Total reel views this week (vs prior 7 days delta)
  - Their top-3 reels by view count + view counts
  - A direct CTA back to the Reel Library + their dashboard

Schedule: every Monday 10:00 UTC (1h after the scout digest so they don't
hit Resend rate limits in lockstep).

Send path mirrors `scout_digest.send_weekly_digest` — uses
`services.email_queue.send_or_queue` so Resend deferrals don't drop emails.
"""
from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timedelta, timezone

from db import db
from services.email_queue import send_or_queue

logger = logging.getLogger(__name__)


def _base_url() -> str:
    return (os.environ.get("PUBLIC_APP_URL") or "https://soccerscout11.com").rstrip("/")


def _format_duration(s: float) -> str:
    if not s or s <= 0:
        return "—"
    s = int(s)
    m, ss = divmod(s, 60)
    return f"{m}:{ss:02d}" if m > 0 else f"{ss}s"


async def _views_for_reel(reel_id: str, since_iso: str, until_iso: str | None = None) -> int:
    query = {"reel_id": reel_id, "viewed_at": {"$gt": since_iso}}
    if until_iso:
        query["viewed_at"]["$lte"] = until_iso
    return await db.highlight_reel_views.count_documents(query)


def _build_recap_html(coach_name: str, total_7d: int, delta: int, items: list) -> str:
    """items: [{ reel, match, views_7d }] sorted by views_7d desc."""
    base = _base_url()
    safe_name = html.escape((coach_name or "Coach").split(" ")[0])

    if delta > 0:
        delta_chip = (
            f'<span style="background:#10B981;color:#000;padding:2px 8px;'
            f'font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;">'
            f'+{delta} vs last wk</span>'
        )
    elif delta < 0:
        delta_chip = (
            f'<span style="background:#EF4444;color:#fff;padding:2px 8px;'
            f'font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;">'
            f'{delta} vs last wk</span>'
        )
    else:
        delta_chip = ""

    rows = []
    for idx, it in enumerate(items, 1):
        reel = it["reel"]
        match = it["match"] or {}
        share_url = f"{base}/reel/{reel.get('share_token','')}"
        title = f"{match.get('team_home','')} vs {match.get('team_away','')}".strip(" vs") or "Reel"
        flame = "🔥 " if idx == 1 else ""
        rows.append(f"""
<tr><td style="padding:16px 0;border-top:1px solid rgba(255,255,255,0.06);">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td style="font-size:13px;color:#888;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;padding-bottom:4px;">{flame}#{idx}</td>
      <td align="right" style="font-size:24px;font-weight:700;color:#007AFF;font-family:Bebas Neue,Impact,sans-serif;">{it['views_7d']} <span style="font-size:11px;color:#888;letter-spacing:1.2px;text-transform:uppercase;">views</span></td>
    </tr>
    <tr><td colspan="2" style="font-size:18px;font-weight:700;color:#fff;">
      <a href="{html.escape(share_url, quote=True)}" style="color:#fff;text-decoration:none;">{html.escape(title)}</a>
    </td></tr>
    <tr><td colspan="2" style="font-size:12px;color:#888;padding-top:2px;">
      {reel.get('total_clips',0)} clips · {_format_duration(reel.get('duration_seconds',0))} reel
      {f"· {html.escape(match.get('competition',''))}" if match.get('competition') else ""}
    </td></tr>
  </table>
</td></tr>
""")
    rows_html = "".join(rows)

    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;color:#EAEAEA;">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:40px 16px;">
  <table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#141414;border:1px solid rgba(255,255,255,0.1);">
    <tr><td style="padding:32px 32px 16px 32px;">
      <div style="font-family:Bebas Neue,Impact,sans-serif;font-size:30px;letter-spacing:2px;color:#007AFF;">REEL RECAP</div>
      <div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#888;margin-top:4px;">Weekly views report · {datetime.now(timezone.utc).strftime('%b %d, %Y')}</div>
    </td></tr>
    <tr><td style="padding:0 32px 8px 32px;">
      <h1 style="margin:0 0 8px 0;font-size:22px;font-weight:700;color:#ffffff;">Hi {safe_name},</h1>
      <p style="margin:0 0 12px 0;font-size:14px;line-height:1.6;color:#CFCFCF;">
        Your highlight reels picked up
        <strong style="color:#10B981;font-family:Bebas Neue,Impact,sans-serif;font-size:22px;vertical-align:-2px;">{total_7d}</strong>
        new views this week. {delta_chip}
      </p>
    </td></tr>
    <tr><td style="padding:0 32px 24px 32px;">
      <table width="100%" cellpadding="0" cellspacing="0">{rows_html}</table>
    </td></tr>
    <tr><td style="padding:0 32px 32px 32px;">
      <div style="border-top:1px solid rgba(255,255,255,0.06);padding-top:20px;">
        <a href="{base}/reels" style="display:inline-block;background:#007AFF;color:#ffffff;padding:14px 24px;text-decoration:none;font-weight:700;font-size:13px;letter-spacing:1.5px;text-transform:uppercase;margin-right:8px;">See Trending Reels</a>
        <a href="{base}/dashboard" style="display:inline-block;background:transparent;border:1px solid #444;color:#ffffff;padding:13px 22px;text-decoration:none;font-weight:700;font-size:13px;letter-spacing:1.5px;text-transform:uppercase;">My Dashboard</a>
      </div>
    </td></tr>
    <tr><td style="padding:18px 32px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:#666;line-height:1.5;">
      Soccer Scout 11 · You receive Reel Recap because you have shared at least one public reel. To stop, revoke share tokens from your dashboard.
    </td></tr>
  </table>
</td></tr></table>
</body></html>"""


async def send_weekly_reel_recap(triggered_by: str = "manual") -> dict:
    """Send the Reel Recap email to every user with shared reel views this week.

    Returns {users_total, sent, queued, skipped, errors}.

    Skip rules:
      - Users with 0 shared reels — nothing to recap
      - Users with 0 views in the past 7 days — silent recap is spammy, skip
    """
    counts = {"users_total": 0, "sent": 0, "queued": 0, "skipped": 0, "errors": 0}
    now = datetime.now(timezone.utc)
    cutoff_7d = (now - timedelta(days=7)).isoformat()
    cutoff_14d = (now - timedelta(days=14)).isoformat()

    # Group reel ids by owner across all `ready + shared` reels
    cursor = db.highlight_reels.find(
        {"status": "ready", "share_token": {"$ne": None}},
        {"_id": 0, "id": 1, "user_id": 1, "match_id": 1, "share_token": 1,
         "total_clips": 1, "duration_seconds": 1},
    )
    by_user: dict[str, list] = {}
    async for r in cursor:
        by_user.setdefault(r["user_id"], []).append(r)

    if not by_user:
        return counts

    counts["users_total"] = len(by_user)

    # Cache match docs (multiple reels can share the same match)
    matches_cache: dict = {}

    for user_id, reels in by_user.items():
        # Aggregate weekly + prior-week views across user's reels
        ids = [r["id"] for r in reels]
        weekly_views = await db.highlight_reel_views.count_documents(
            {"reel_id": {"$in": ids}, "viewed_at": {"$gt": cutoff_7d}},
        )
        if weekly_views == 0 and triggered_by == "apscheduler":
            counts["skipped"] += 1
            continue

        prior_views = await db.highlight_reel_views.count_documents({
            "reel_id": {"$in": ids},
            "viewed_at": {"$gt": cutoff_14d, "$lte": cutoff_7d},
        })
        delta = weekly_views - prior_views

        # Top-3 reels by weekly views
        pipeline = [
            {"$match": {"reel_id": {"$in": ids}, "viewed_at": {"$gt": cutoff_7d}}},
            {"$group": {"_id": "$reel_id", "view_count": {"$sum": 1}}},
            {"$sort": {"view_count": -1}},
            {"$limit": 3},
        ]
        top_rows = await db.highlight_reel_views.aggregate(pipeline).to_list(3)

        reel_lookup = {r["id"]: r for r in reels}
        items = []
        for row in top_rows:
            reel = reel_lookup.get(row["_id"])
            if not reel:
                continue
            mid = reel["match_id"]
            if mid not in matches_cache:
                matches_cache[mid] = await db.matches.find_one(
                    {"id": mid},
                    {"_id": 0, "team_home": 1, "team_away": 1, "competition": 1},
                )
            items.append({
                "reel": reel,
                "match": matches_cache[mid],
                "views_7d": row["view_count"],
            })
        if not items:
            counts["skipped"] += 1
            continue

        owner = await db.users.find_one(
            {"id": user_id}, {"_id": 0, "name": 1, "email": 1},
        )
        if not owner or not owner.get("email"):
            counts["skipped"] += 1
            continue

        try:
            html_body = _build_recap_html(
                owner.get("name", "Coach"), weekly_views, delta, items,
            )
            res = await send_or_queue(
                to_email=owner["email"],
                subject=f"Your reels got {weekly_views} new views this week",
                html=html_body,
                kind="reel_recap",
                metadata={"user_id": user_id, "triggered_by": triggered_by},
            )
            if res.get("status") == "sent":
                counts["sent"] += 1
            else:
                counts["queued"] += 1
        except Exception as exc:
            logger.error("[reel_recap] error sending to %s: %s", owner.get("email"), exc)
            counts["errors"] += 1

    logger.info("[reel_recap] triggered_by=%s result=%s", triggered_by, counts)
    return counts
