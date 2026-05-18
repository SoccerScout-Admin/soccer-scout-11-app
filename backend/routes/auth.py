"""Authentication routes and dependency"""
import os
import logging
from fastapi import APIRouter, HTTPException, Header, Request
from typing import Optional
import uuid
import jwt
import bcrypt
from datetime import datetime, timezone
from db import db, JWT_SECRET
from models import RegisterRequest, LoginRequest

router = APIRouter()
logger = logging.getLogger(__name__)


# Cookie name must match the one set by server.py's _set_auth_cookie.
ACCESS_TOKEN_COOKIE = "access_token"


async def _maybe_autopromote_admin(user: dict) -> dict:
    """Mirror of server.py::_maybe_autopromote_admin. The two copies MUST
    stay in sync until we consolidate get_current_user into a single module.
    See server.py docstring for full behavior contract."""
    raw = os.environ.get("ADMIN_AUTOPROMOTE_EMAIL", "").strip()
    if not raw:
        return user
    current_role = (user.get("role") or "").lower()
    if current_role in ("admin", "owner"):
        return user
    user_email = (user.get("email") or "").strip().lower()
    if not user_email:
        return user
    allowed = {e.strip().lower() for e in raw.split(",") if e.strip()}
    if user_email not in allowed:
        return user
    try:
        await db.users.update_one(
            {"id": user["id"]}, {"$set": {"role": "admin"}}
        )
        logger.warning(
            f"ADMIN_AUTOPROMOTE_EMAIL match — promoted {user_email} "
            f"from role={current_role!r} to role='admin' (user_id={user['id']})"
        )
        user["role"] = "admin"
    except Exception as e:
        logger.error(f"Admin auto-promote failed for {user_email}: {e}")
    return user


async def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Authenticate the caller. Reads the httpOnly access_token cookie first
    (XSS-proof, the iter52 migration target); falls back to the legacy
    Authorization Bearer header so users with existing localStorage tokens
    stay logged in until their next login refreshes the cookie.

    Mirrors server.py:get_current_user — there are TWO copies of this dep in
    the codebase (server.py + this file), imported by different routes. Both
    MUST stay in sync until we consolidate.
    """
    token = None
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if cookie_token:
        token = cookie_token
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        # iter76: auto-promote owner emails on every authenticated request.
        user = await _maybe_autopromote_admin(user)
        return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/auth/register")
async def register(req: RegisterRequest):
    existing = await db.users.find_one({"email": req.email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt()).decode()
    user = {
        "id": str(uuid.uuid4()),
        "email": req.email,
        "password": hashed,
        "name": req.name,
        "role": req.role,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user)
    token = jwt.encode({"user_id": user["id"]}, JWT_SECRET, algorithm="HS256")
    return {"token": token, "user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}}


@router.post("/auth/login")
async def login(req: LoginRequest):
    user = await db.users.find_one({"email": req.email}, {"_id": 0})
    if not user or not bcrypt.checkpw(req.password.encode(), user["password"].encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = jwt.encode({"user_id": user["id"]}, JWT_SECRET, algorithm="HS256")
    return {"token": token, "user": {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}}
