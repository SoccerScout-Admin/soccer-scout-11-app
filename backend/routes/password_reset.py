"""Forgot-password + reset-password flow.

Design:
- User requests reset → we ALWAYS return `{"status": "sent"}` regardless of
  whether the email is registered (prevents account enumeration).
- We generate a high-entropy token via `secrets.token_urlsafe(32)` and store
  ONLY the sha256 hash in MongoDB. The plaintext token goes into the email.
- Token is single-use: `used_at` timestamp flips on first successful reset.
- Token expires after 60 min. A MongoDB TTL index cleans up expired/used docs.
- Reset endpoint re-hashes the new password with bcrypt (same as registration).

Email is dispatched through `services/email_queue.send_or_queue` so Resend
quota deferrals don't lose the reset link.
"""
from __future__ import annotations

import hashlib
import html
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field

from db import db
from services.email_queue import send_or_queue

router = APIRouter()


TOKEN_TTL_MINUTES = 60
_MIN_PASSWORD_LEN = 8


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_app_url() -> str:
    """Frontend base URL used in the reset link."""
    return os.environ.get("PUBLIC_APP_URL", "").rstrip("/")


def _build_email_html(reset_url: str, name: str) -> str:
    safe_name = html.escape(name or "Coach")
    safe_url = html.escape(reset_url, quote=True)
    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0A0A0A;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;color:#EAEAEA;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background:#0A0A0A;">
    <tr><td align="center" style="padding:40px 16px;">
      <table width="560" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px;background:#141414;border:1px solid rgba(255,255,255,0.1);">
        <tr><td style="padding:32px 32px 8px 32px;">
          <div style="font-family:Bebas Neue,Impact,sans-serif;font-size:28px;letter-spacing:2px;color:#007AFF;">SOCCER SCOUT 11</div>
          <div style="font-size:11px;letter-spacing:3px;text-transform:uppercase;color:#888;margin-top:4px;">Password Reset</div>
        </td></tr>
        <tr><td style="padding:16px 32px;">
          <h1 style="margin:0 0 16px 0;font-size:22px;font-weight:700;color:#ffffff;">Reset your password</h1>
          <p style="margin:0 0 16px 0;font-size:15px;line-height:1.6;color:#CFCFCF;">Hi {safe_name}, we received a request to reset your Soccer Scout 11 password. Click the button below to choose a new one. This link expires in {TOKEN_TTL_MINUTES} minutes and can only be used once.</p>
          <div style="margin:28px 0;">
            <a href="{safe_url}" style="display:inline-block;background:#007AFF;color:#ffffff;text-decoration:none;padding:14px 28px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;font-size:13px;">Reset Password</a>
          </div>
          <p style="margin:0 0 8px 0;font-size:13px;color:#888;">Or copy-paste this URL into your browser:</p>
          <p style="margin:0 0 20px 0;font-size:12px;color:#007AFF;word-break:break-all;">{safe_url}</p>
          <p style="margin:24px 0 0 0;font-size:12px;color:#777;line-height:1.5;">If you didn't request this, you can safely ignore this email — your password won't change.</p>
        </td></tr>
        <tr><td style="padding:24px 32px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px;color:#666;">
          Soccer Scout 11 · AI Match Analysis for Coaches
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=8, max_length=200)
    new_password: str = Field(min_length=_MIN_PASSWORD_LEN, max_length=128)


@router.post("/auth/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """Always returns a generic 200 response — even when the email is unknown —
    to prevent account enumeration. Internally, if the email is registered,
    we create a single-use token and email the reset link.
    """
    email = body.email.strip().lower()

    user = await db.users.find_one({"email": email}, {"_id": 0, "id": 1, "name": 1})
    if user:
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=TOKEN_TTL_MINUTES)

        # Store only the hash. The plaintext goes in the email only.
        await db.password_reset_tokens.insert_one({
            "id": f"pr-{secrets.token_urlsafe(8)}",
            "user_id": user["id"],
            "email": email,
            "token_hash": token_hash,
            "created_at": now,
            "expires_at": expires_at,
            "used_at": None,
        })

        base = _public_app_url()
        reset_url = f"{base}/reset-password?token={raw_token}" if base else f"/reset-password?token={raw_token}"
        try:
            await send_or_queue(
                to_email=email,
                subject="Reset your Soccer Scout 11 password",
                html=_build_email_html(reset_url, user.get("name", "Coach")),
                kind="password_reset",
                metadata={"user_id": user["id"]},
            )
        except Exception:
            # Never surface mail errors to the client — we still return 200 to
            # keep the response identical regardless of email availability.
            pass

    return {"status": "sent"}


@router.post("/auth/reset-password")
async def reset_password(body: ResetPasswordRequest):
    """Consume a reset token and set a new password.

    Returns 400 for expired/missing/already-used tokens. On success marks the
    token as used and updates the user's bcrypt password hash.
    """
    # Password policy: min 8 chars (Pydantic-enforced), must contain at least
    # one letter and one digit. Keeps the rule simple but stops "12345678".
    if not re.search(r"[A-Za-z]", body.new_password) or not re.search(r"\d", body.new_password):
        raise HTTPException(
            status_code=400,
            detail="Password must contain at least one letter and one digit.",
        )

    token_hash = _hash_token(body.token)
    now = datetime.now(timezone.utc)

    record = await db.password_reset_tokens.find_one({"token_hash": token_hash}, {"_id": 0})
    if not record:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")

    if record.get("used_at"):
        raise HTTPException(status_code=400, detail="This reset link has already been used.")

    expires_at: Optional[datetime] = record.get("expires_at")
    if expires_at and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and now > expires_at:
        raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new one.")

    user = await db.users.find_one({"id": record["user_id"]}, {"_id": 0, "id": 1, "email": 1})
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link.")

    hashed = bcrypt.hashpw(body.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    await db.users.update_one({"id": user["id"]}, {"$set": {"password": hashed}})
    await db.password_reset_tokens.update_one(
        {"token_hash": token_hash},
        {"$set": {"used_at": now}},
    )

    return {"status": "reset", "email": user["email"]}
