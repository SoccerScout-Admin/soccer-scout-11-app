"""Recruiter Lens — tracked, share-linked emails to college coaches.

Workflow:
    1. Coach creates a lens link via `POST /api/lens-links` with a
       team + filter set + recipient email. We email the recipient a
       tracked URL `/api/lens-track/{tracking_token}` that 302-redirects
       to the actual public team page with filter query params applied.
    2. When the recipient (or anyone else) hits that tracked URL, we
       insert a click row into `lens_link_clicks` and bump the parent
       lens_link counters before redirecting.
    3. Coach can list their sent links + click counts via
       `GET /api/lens-links?team_id=...`.

Data model:
    lens_links: {
        id, user_id, team_id, team_share_token,
        filters: { birth_year?, class_of?, position? },
        recipient_email, recipient_name?, message?,
        tracking_token (unique short token),
        click_count, last_clicked_at,
        created_at,
    }
    lens_link_clicks: { id, lens_link_id, ip_address?, user_agent?, clicked_at }

Public endpoints (no auth): `/api/lens-track/{token}` — that's it.
Everything else is coach-scoped via JWT.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
import secrets
import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from db import db
from routes.auth import get_current_user
from services.email_queue import send_or_queue

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _public_base() -> str:
    """Best-effort base URL for the recipient's clickable links.

    Priority: PUBLIC_APP_URL (deploy-injected) → falls back to a relative path
    which still works (the email client resolves against the email's HTML).
    """
    return os.environ.get("PUBLIC_APP_URL", "").rstrip("/")


class LensFilters(BaseModel):
    """Subset of filter dimensions that map 1:1 onto SharedTeamView query params."""
    birth_year: Optional[str] = None
    class_of: Optional[str] = None
    position: Optional[str] = None

    def to_query_dict(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v}


class CreateLensLinkBody(BaseModel):
    team_id: str
    filters: LensFilters = Field(default_factory=LensFilters)
    recipient_email: EmailStr
    recipient_name: Optional[str] = Field(default=None, max_length=120)
    message: Optional[str] = Field(default=None, max_length=2000)


def _build_target_url(team_share_token: str, filters: LensFilters) -> str:
    """The final public URL the tracking token redirects to."""
    qs = urlencode(filters.to_query_dict())
    base = _public_base()
    path = f"/shared-team/{team_share_token}"
    if qs:
        path += f"?{qs}"
    return f"{base}{path}" if base else path


def _human_filter_summary(filters: LensFilters) -> str:
    """A human-friendly string for the email subject / body."""
    parts: list[str] = []
    if filters.class_of:
        parts.append(f"Class of {filters.class_of}")
    if filters.birth_year:
        parts.append(f"Born {filters.birth_year}")
    if filters.position:
        parts.append(filters.position + "s")
    return " · ".join(parts) if parts else "Full Squad"


def _email_html(
    coach_name: str,
    recipient_name: Optional[str],
    team_name: str,
    filter_summary: str,
    message: Optional[str],
    tracked_url: str,
) -> str:
    """Lightweight inline-HTML email. No external assets so it renders in any client."""
    greeting = f"Hi {recipient_name}," if recipient_name else "Hi,"
    message_block = (
        f'<p style="margin:18px 0;color:#444;line-height:1.55;">{message}</p>'
        if message else ""
    )
    return f"""\
<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f4f4;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:24px 0;background:#f4f4f4;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;">
        <tr><td style="padding:32px 32px 16px 32px;background:#0F1A2E;color:#fff;">
          <div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#60A5FA;margin-bottom:6px;">Recruiter Lens</div>
          <div style="font-size:24px;font-weight:700;">{team_name}</div>
          <div style="font-size:14px;color:#A3A3A3;margin-top:6px;">{filter_summary}</div>
        </td></tr>
        <tr><td style="padding:28px 32px;">
          <p style="margin:0 0 12px 0;color:#222;font-size:15px;">{greeting}</p>
          <p style="margin:0 0 12px 0;color:#444;line-height:1.55;">
            {coach_name} put together a focused player list and wanted to share it directly with you.
          </p>
          {message_block}
          <div style="margin:24px 0;">
            <a href="{tracked_url}" style="background:#007AFF;color:#fff;text-decoration:none;padding:14px 28px;border-radius:4px;font-weight:600;font-size:14px;letter-spacing:1px;text-transform:uppercase;display:inline-block;">View Player List →</a>
          </div>
          <p style="margin:24px 0 0 0;color:#888;font-size:12px;line-height:1.5;">
            This link opens a filtered view of the team roster on Soccer Scout. No login required.
          </p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""


# ===== Endpoints =====

@router.post("/lens-links")
async def create_lens_link(
    body: CreateLensLinkBody,
    current_user: dict = Depends(get_current_user),
):
    """Coach generates a tracked outreach link + sends the email.

    Returns the created lens_link record so the UI can show the tracked URL.
    """
    team = await db.teams.find_one(
        {"id": body.team_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if not team.get("share_token"):
        # Auto-enable team share so the recipient lands somewhere real.
        share_token = secrets.token_urlsafe(8)[:12]
        await db.teams.update_one(
            {"id": body.team_id}, {"$set": {"share_token": share_token}}
        )
        team["share_token"] = share_token

    tracking_token = secrets.token_urlsafe(10)
    target_url = _build_target_url(team["share_token"], body.filters)

    lens_link = {
        "id": f"ll-{secrets.token_urlsafe(8)}",
        "user_id": current_user["id"],
        "team_id": team["id"],
        "team_share_token": team["share_token"],
        "filters": body.filters.model_dump(),
        "recipient_email": str(body.recipient_email),
        "recipient_name": body.recipient_name,
        "message": body.message,
        "tracking_token": tracking_token,
        "click_count": 0,
        "last_clicked_at": None,
        "created_at": _now_iso(),
    }
    await db.lens_links.insert_one(dict(lens_link))

    # Send the email
    base = _public_base()
    tracked_url = (
        f"{base}/api/lens-track/{tracking_token}" if base
        else f"/api/lens-track/{tracking_token}"
    )
    filter_summary = _human_filter_summary(body.filters)
    subject = f"{current_user.get('name', 'A coach')} sent you a roster: {team['name']} ({filter_summary})"
    html = _email_html(
        coach_name=current_user.get("name", "A coach"),
        recipient_name=body.recipient_name,
        team_name=team["name"],
        filter_summary=filter_summary,
        message=body.message,
        tracked_url=tracked_url,
    )

    email_result = await send_or_queue(
        to_email=str(body.recipient_email),
        subject=subject,
        html=html,
        kind="recruiter_lens",
        metadata={"lens_link_id": lens_link["id"]},
    )

    return {
        "lens_link": lens_link,
        "tracked_url": tracked_url,
        "target_url": target_url,
        "email_status": email_result.get("status"),
    }


@router.get("/lens-links")
async def list_lens_links(
    team_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> List[dict]:
    """List the current coach's lens links, optionally filtered by team."""
    query = {"user_id": current_user["id"]}
    if team_id:
        query["team_id"] = team_id
    rows = await db.lens_links.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    return rows


@router.get("/lens-track/{tracking_token}")
async def lens_track(tracking_token: str, request: Request):
    """Public — logs a click and 302-redirects to the actual filtered page.

    No auth: recipients hit this from their email client. We record the click
    even if it's the coach themselves clicking through to verify the link.
    """
    link = await db.lens_links.find_one(
        {"tracking_token": tracking_token}, {"_id": 0}
    )
    if not link:
        # Don't reveal whether the token exists — just send to home.
        return RedirectResponse(url="/", status_code=302)

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    click_doc = {
        "id": f"lc-{secrets.token_urlsafe(8)}",
        "lens_link_id": link["id"],
        "ip_address": ip,
        "user_agent": (ua or "")[:300],
        "clicked_at": _now_iso(),
    }
    await db.lens_link_clicks.insert_one(dict(click_doc))
    await db.lens_links.update_one(
        {"id": link["id"]},
        {
            "$inc": {"click_count": 1},
            "$set": {"last_clicked_at": click_doc["clicked_at"]},
        },
    )

    # Build redirect URL — same logic as `_build_target_url` but without env
    # base, since the recipient already followed an absolute URL to get here.
    filters = LensFilters(**(link.get("filters") or {}))
    qs = urlencode(filters.to_query_dict())
    path = f"/shared-team/{link['team_share_token']}"
    if qs:
        path += f"?{qs}"
    return RedirectResponse(url=path, status_code=302)


@router.get("/lens-links/{lens_link_id}/clicks")
async def get_lens_link_clicks(
    lens_link_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Drill-down: list individual clicks for a lens link the coach owns."""
    link = await db.lens_links.find_one(
        {"id": lens_link_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not link:
        raise HTTPException(status_code=404, detail="Lens link not found")
    clicks = await db.lens_link_clicks.find(
        {"lens_link_id": lens_link_id}, {"_id": 0}
    ).sort("clicked_at", -1).to_list(200)
    return {"lens_link": link, "clicks": clicks}
