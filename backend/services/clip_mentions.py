"""Clip-reel @-mention notifications.

When a coach creates a shared clip collection and mentions other coaches
(either via @-handles in the description or by explicitly passing
`mentioned_coach_ids`), each mentioned coach receives a Resend email with a
one-click link to the public reel.

The mention record is persisted to `clip_mentions` so we can:
- Prevent duplicate emails on repeated updates
- Show each coach a "mentions inbox" in the Coach Network UI (future)
- Audit/reverse
"""
import logging
import os
from datetime import datetime, timezone
from db import db

logger = logging.getLogger(__name__)


def _resend_api_key() -> str:
    return os.environ.get("RESEND_API_KEY", "")


def _sender_email() -> str:
    return os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")


def _public_base_url() -> str:
    # Prefer the env-configured public URL; fall back to the hardcoded preview host.
    return os.environ.get("PUBLIC_APP_URL", "").rstrip("/")


def _render_mention_email(
    mentioner_name: str,
    collection_title: str,
    description: str,
    reel_url: str,
    clip_count: int,
) -> tuple[str, str]:
    """Return (subject, html) for the mention notification email."""
    subject = f"{mentioner_name} mentioned you on a clip reel"
    safe_desc = (description or "").replace("<", "&lt;").replace(">", "&gt;")[:600]
    html = f"""
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#0A0A0A;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="100%" style="background:#0A0A0A;">
  <tr><td align="center" style="padding:24px;">
    <table role="presentation" cellspacing="0" cellpadding="0" border="0" width="600" style="background:#141414;border:1px solid rgba(255,255,255,0.1);">
      <tr><td style="padding:32px 28px 20px;">
        <div style="color:#A855F7;font-size:11px;font-weight:bold;letter-spacing:0.25em;text-transform:uppercase;">@ Mention</div>
        <h1 style="color:#fff;font-size:28px;margin:6px 0 0;font-weight:800;">{mentioner_name} tagged you on a clip reel</h1>
      </td></tr>
      <tr><td style="padding:4px 28px 20px;">
        <p style="color:#E5E5E5;font-size:15px;line-height:1.6;margin:0;">
          <strong style="color:#fff;">{collection_title}</strong>
          <span style="color:#888;"> — {clip_count} clip{'s' if clip_count != 1 else ''}</span>
        </p>
        {f'<p style="color:#CCC;font-size:14px;line-height:1.6;margin:14px 0 0;font-style:italic;">&ldquo;{safe_desc}&rdquo;</p>' if safe_desc else ''}
      </td></tr>
      <tr><td style="padding:12px 28px 32px;">
        <a href="{reel_url}" style="display:inline-block;padding:14px 28px;background:#007AFF;color:#fff;text-decoration:none;font-weight:bold;letter-spacing:0.1em;text-transform:uppercase;font-size:13px;">
          Watch the reel &rarr;
        </a>
      </td></tr>
      <tr><td style="padding:20px 28px;border-top:1px solid rgba(255,255,255,0.08);">
        <p style="color:#666;font-size:11px;line-height:1.5;margin:0;">
          You received this because {mentioner_name} mentioned you on a Soccer Scout 11 reel.
          Replies aren't monitored — reply to {mentioner_name} directly.
        </p>
      </td></tr>
    </table>
    <p style="color:#444;font-size:10px;letter-spacing:0.1em;text-transform:uppercase;margin:16px 0 0;">
      Powered by Soccer Scout 11
    </p>
  </td></tr>
</table>
</body></html>""".strip()
    return subject, html


async def _send_via_resend(to_email: str, subject: str, html: str) -> str:
    """Route through the email queue so quota-exhausted emails get queued for
    automatic retry instead of silently dropped."""
    from services.email_queue import send_or_queue
    result = await send_or_queue(to_email, subject, html, kind="clip_mention")
    if result["status"] == "sent":
        return result.get("email_id", "")
    if result["status"] == "quota_deferred":
        logger.info("[mentions] email queued for %s — quota deferred", to_email)
        return f"queued:{result.get('queue_id', '')}"
    # permanent failure — re-raise so the caller can log and skip
    raise RuntimeError(result.get("error") or "email send failed")


async def notify_coach_mentions(
    mentioner: dict,
    collection: dict,
    mentioned_coach_ids: list[str],
    request_host: str = "",
):
    """Persist mention records and fire email notifications. Best-effort:
    failures are logged but don't raise. Deduplicates against recent mentions
    for the same (mentioner, collection, coach) tuple so edits don't spam.
    """
    if not mentioned_coach_ids:
        return {"sent": 0, "skipped": 0}
    if not _resend_api_key():
        logger.info("[mentions] RESEND_API_KEY not configured — skipping emails")
        return {"sent": 0, "skipped": len(mentioned_coach_ids)}

    # Build reel URL. Prefer PUBLIC_APP_URL from env, else fall back to the
    # request's forwarded host.
    base = _public_base_url()
    if not base and request_host:
        base = f"https://{request_host}"
    if not base:
        logger.warning("[mentions] No public base URL available — skipping emails")
        return {"sent": 0, "skipped": len(mentioned_coach_ids)}

    reel_url = f"{base}/clips/{collection['share_token']}"

    sent = 0
    skipped = 0
    for coach_id in mentioned_coach_ids:
        coach = await db.users.find_one({"id": coach_id}, {"_id": 0, "id": 1, "email": 1, "name": 1})
        if not coach or not coach.get("email"):
            skipped += 1
            continue

        # Dedupe: skip if we've already emailed this coach about this collection
        existing = await db.clip_mentions.find_one(
            {"collection_id": collection["id"], "mentioned_user_id": coach_id, "email_sent": True},
            {"_id": 0, "id": 1},
        )
        if existing:
            skipped += 1
            continue

        # Persist the mention record BEFORE send so a partial crash doesn't duplicate emails
        mention = {
            "id": f"m-{collection['id']}-{coach_id}",
            "collection_id": collection["id"],
            "mentioner_user_id": mentioner["id"],
            "mentioned_user_id": coach_id,
            "mentioner_name": mentioner.get("name") or mentioner.get("email") or "A coach",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "email_sent": False,
        }
        await db.clip_mentions.replace_one(
            {"id": mention["id"]}, mention, upsert=True,
        )

        try:
            subject, html = _render_mention_email(
                mentioner_name=mention["mentioner_name"],
                collection_title=collection.get("title") or "Clip Reel",
                description=collection.get("description") or "",
                reel_url=reel_url,
                clip_count=len(collection.get("clip_ids") or []),
            )
            email_id = await _send_via_resend(coach["email"], subject, html)
            await db.clip_mentions.update_one(
                {"id": mention["id"]},
                {"$set": {"email_sent": True, "email_id": email_id}},
            )
            sent += 1
        except Exception as e:
            logger.warning("[mentions] failed to email %s: %s", coach.get("email"), e)
            skipped += 1

    logger.info("[mentions] collection=%s sent=%d skipped=%d", collection["id"], sent, skipped)
    return {"sent": sent, "skipped": skipped}
