"""
Auto-alert for video-processing pipeline health.

Runs hourly. Pulls the last hour's `processing_events`, computes the
final_failure rate, and Resend-emails the admin if the rate crosses a
threshold AND we haven't already alerted recently.

Why this exists: iter63's auto-retry hides pod-memory regressions from the
user. If pod limits drop or files start arriving even larger, the retry tier
will start failing too — and the only visible symptom will be a slow uptick
in user-reported "AI didn't run" messages. This alert catches it before users
do.

De-dupe: we won't fire the same alert twice within `ALERT_DEDUP_WINDOW_HOURS`
(default 6h) unless the rate is materially worse than the prior alert (>= 10
points higher). This prevents alert fatigue while still re-firing if things
get dramatically worse.

Reads ALERT_RECIPIENT_EMAIL from env. Falls back to SENDER_EMAIL so a single
test address still works. If neither is set, the alert is logged but no
email is sent.
"""
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from db import db
from services.email_queue import send_or_queue

logger = logging.getLogger(__name__)

# Threshold tuned to be loud-but-not-noisy. Most healthy 1-hour windows show
# 100% success or very low volume. A 20% failure rate over >= 3 attempts is
# a real signal worth a wake-up.
FAILURE_RATE_THRESHOLD_PCT = float(os.environ.get("PROCESSING_ALERT_THRESHOLD_PCT", "20"))
MIN_ATTEMPTS_FOR_ALERT = int(os.environ.get("PROCESSING_ALERT_MIN_ATTEMPTS", "3"))
ALERT_DEDUP_WINDOW_HOURS = int(os.environ.get("PROCESSING_ALERT_DEDUP_HOURS", "6"))
ESCALATION_RATE_DELTA_PCT = float(os.environ.get("PROCESSING_ALERT_ESCALATION_PCT", "10"))


def _recipient_email() -> Optional[str]:
    return os.environ.get("ALERT_RECIPIENT_EMAIL") or os.environ.get("SENDER_EMAIL") or None


async def _compute_last_hour_stats() -> dict:
    """Pull events from the last 60 min and return a small dict ready to
    drive the alert decision + email template."""
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cursor = db.processing_events.find(
        {"created_at": {"$gte": since}, "event_type": {"$in": ["final_success", "final_failure"]}},
        {"_id": 0, "event_type": 1, "failure_mode": 1, "source_size_gb": 1, "video_id": 1},
    ).limit(2000)
    events = await cursor.to_list(2000)

    final_success = sum(1 for e in events if e["event_type"] == "final_success")
    final_failure = sum(1 for e in events if e["event_type"] == "final_failure")
    total = final_success + final_failure

    failure_modes: dict = {}
    for e in events:
        if e["event_type"] == "final_failure" and e.get("failure_mode"):
            failure_modes[e["failure_mode"]] = failure_modes.get(e["failure_mode"], 0) + 1

    return {
        "total": total,
        "final_success": final_success,
        "final_failure": final_failure,
        "failure_rate_pct": round(final_failure / total * 100, 1) if total else 0.0,
        "failure_modes": failure_modes,
        "since": since,
    }


async def _last_alert() -> Optional[dict]:
    return await db.processing_alerts.find_one(
        {"_kind": "rate_alert"},
        {"_id": 0},
        sort=[("created_at", -1)],
    )


async def _record_alert(stats: dict, recipient: str) -> None:
    await db.processing_alerts.insert_one({
        "_kind": "rate_alert",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "failure_rate_pct": stats["failure_rate_pct"],
        "total": stats["total"],
        "final_failure": stats["final_failure"],
        "recipient": recipient,
    })


def _format_email_html(stats: dict, public_app_url: str) -> str:
    modes = stats.get("failure_modes") or {}
    modes_html = "".join(
        f"<li><strong>{mode}</strong>: {cnt}</li>" for mode, cnt in sorted(modes.items(), key=lambda kv: -kv[1])
    ) or "<li>(no specific failure mode tagged)</li>"

    return f"""
<!doctype html>
<html><body style="font-family: -apple-system, system-ui, sans-serif; background: #0A0A0A; color: #E5E5E5; padding: 24px;">
  <div style="max-width: 560px; margin: auto; background: #141414; border: 1px solid #2A2A2A; padding: 28px;">
    <p style="text-transform: uppercase; letter-spacing: 0.2em; font-size: 11px; color: #EF4444; margin: 0 0 6px 0;">Pipeline Alert</p>
    <h1 style="font-size: 22px; margin: 0 0 12px 0; color: #fff;">Video processing failure rate spiked</h1>
    <p style="color: #A3A3A3; margin: 0 0 18px 0;">
      Over the last hour, <strong style="color:#fff;">{stats['final_failure']} of {stats['total']}</strong>
      videos failed AI prep — that's <strong style="color:#EF4444;">{stats['failure_rate_pct']}%</strong>.
      Threshold is {FAILURE_RATE_THRESHOLD_PCT}%.
    </p>
    <h3 style="font-size: 13px; color:#A3A3A3; letter-spacing: 0.15em; text-transform: uppercase; margin: 18px 0 8px 0;">Failure modes</h3>
    <ul style="margin: 0 0 18px 0; padding-left: 18px; color: #E5E5E5;">
      {modes_html}
    </ul>
    <h3 style="font-size: 13px; color:#A3A3A3; letter-spacing: 0.15em; text-transform: uppercase; margin: 18px 0 8px 0;">What to check</h3>
    <ol style="margin: 0; padding-left: 18px; color: #E5E5E5;">
      <li>Pod memory in Emergent dashboard — OOM spikes mean the limit needs bumping.</li>
      <li>Recent uploads — a single 10 GB file can produce many failed tier attempts.</li>
      <li>Drill into <a href="{public_app_url}/api/admin/processing-events/recent?event_type=final_failure" style="color: #7DD3FC;">recent failures</a>.</li>
    </ol>
    <p style="color: #666; font-size: 11px; margin-top: 24px;">
      Auto-sent by SoccerScout11 pipeline monitor.
      Won't re-fire for {ALERT_DEDUP_WINDOW_HOURS}h unless the rate climbs another {ESCALATION_RATE_DELTA_PCT} points.
    </p>
  </div>
</body></html>
"""


async def check_and_alert() -> dict:
    """Single hourly check. Safe to call repeatedly — handles its own dedup.

    Returns a small dict with what happened so callers (cron task, manual
    admin trigger) can log it. NEVER raises — pipeline monitoring must
    not itself become a source of crashes.
    """
    try:
        stats = await _compute_last_hour_stats()

        if stats["total"] < MIN_ATTEMPTS_FOR_ALERT:
            return {"action": "skip_low_volume", **stats}

        if stats["failure_rate_pct"] < FAILURE_RATE_THRESHOLD_PCT:
            return {"action": "skip_below_threshold", **stats}

        # Dedup: did we already fire an alert recently?
        recent = await _last_alert()
        if recent:
            try:
                last_ts = datetime.fromisoformat(recent["created_at"])
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                hours_since = (datetime.now(timezone.utc) - last_ts).total_seconds() / 3600
                if hours_since < ALERT_DEDUP_WINDOW_HOURS:
                    prior_rate = recent.get("failure_rate_pct", 0)
                    if stats["failure_rate_pct"] < prior_rate + ESCALATION_RATE_DELTA_PCT:
                        return {"action": "skip_deduped", "hours_since_last": round(hours_since, 1), **stats}
            except Exception as e:
                logger.warning(f"Failed to parse last alert timestamp ({e}) — re-alerting to be safe")

        recipient = _recipient_email()
        if not recipient:
            logger.warning(f"Pipeline alert threshold crossed ({stats['failure_rate_pct']}%) but no recipient configured (ALERT_RECIPIENT_EMAIL or SENDER_EMAIL).")
            return {"action": "skip_no_recipient", **stats}

        public_url = os.environ.get("PUBLIC_APP_URL", "").rstrip("/")
        html = _format_email_html(stats, public_url)
        subject = f"[SoccerScout11] Pipeline failure rate at {stats['failure_rate_pct']}% — check pod limits"

        await send_or_queue(to_email=recipient, subject=subject, html=html)
        await _record_alert(stats, recipient)
        logger.warning(f"Pipeline alert sent to {recipient}: {stats['final_failure']}/{stats['total']} failed ({stats['failure_rate_pct']}%)")
        return {"action": "alert_sent", "recipient": recipient, **stats}
    except Exception as e:
        # Hard guard — alerting must NEVER break the app.
        logger.exception(f"check_and_alert raised non-fatally: {e}")
        return {"action": "error", "error": str(e)}
