"""Authentication routes and dependency"""
from fastapi import APIRouter, HTTPException, Header, Request
from typing import Optional
import uuid
import jwt
import bcrypt
from datetime import datetime, timezone
from db import db, JWT_SECRET
from models import RegisterRequest, LoginRequest

router = APIRouter()


# Cookie name must match the one set by server.py's _set_auth_cookie.
ACCESS_TOKEN_COOKIE = "access_token"


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
