"""Scout Listings — public board of projected roster needs for upcoming seasons.

Who can post:
    Anyone registered can sign up with role=`scout`. Their listings go live
    immediately but carry a `verified=false` flag until admin approval, at
    which point the public UI shows a verified ✓ badge.

Who can view:
    The listings feed and detail pages are public (no auth), but contact_email
    and website_url are redacted for anonymous viewers to discourage scraping
    and reward coaches for signing up.

Filters:
    - positions (comma-separated: "GK,CB,CM") — matches any
    - grad_years (comma-separated: "2026,2027") — matches any
    - level (exact match: "NCAA D1")
    - region (substring match, case-insensitive)
    - q (search query — matches school_name OR description, case-insensitive)
    - verified_only (default True — set False to include pending)
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl
from starlette.concurrency import run_in_threadpool

from db import APP_NAME, db
from routes.auth import get_current_user
from services.scout_digest import (
    listing_insights, my_listings_with_insights, record_view, send_weekly_digest,
)
from services.storage import get_object_sync, put_object_sync

router = APIRouter()


ALLOWED_POSITIONS = ["GK", "CB", "FB", "CM", "DM", "AM", "LW", "RW", "ST"]
ALLOWED_LEVELS = [
    "NCAA D1", "NCAA D2", "NCAA D3", "NAIA", "JUCO",
    "Pro Academy", "MLS Next", "ECNL", "Other",
]

SCOUT_ROLES = {"scout", "college_coach"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_contact(listing: dict) -> dict:
    """Strip contact fields from a listing for anonymous viewers."""
    redacted = dict(listing)
    redacted.pop("contact_email", None)
    redacted.pop("website_url", None)
    redacted["_contact_gated"] = True
    return redacted


def _require_scout_role(user: dict):
    role = (user.get("role") or "").lower()
    if role in SCOUT_ROLES or role in ("admin", "owner"):
        return
    raise HTTPException(
        status_code=403,
        detail="Only scouts or college coaches can create listings. Update your role in settings or contact an admin.",
    )


def _require_admin(user: dict):
    if (user.get("role") or "").lower() not in ("admin", "owner"):
        raise HTTPException(status_code=403, detail="Admin access required")


# ---------- Pydantic models ----------

class ScoutListingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    school_name: str = Field(min_length=2, max_length=120)
    website_url: Optional[HttpUrl] = None
    positions: List[str] = Field(default_factory=list)
    grad_years: List[int] = Field(default_factory=list)
    level: str
    region: str = Field(min_length=1, max_length=120)
    gpa_requirement: Optional[str] = Field(default=None, max_length=120)
    recruiting_timeline: Optional[str] = Field(default=None, max_length=240)
    contact_email: EmailStr
    description: str = Field(min_length=10, max_length=2000)


class ScoutListingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    school_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    website_url: Optional[HttpUrl] = None
    positions: Optional[List[str]] = None
    grad_years: Optional[List[int]] = None
    level: Optional[str] = None
    region: Optional[str] = Field(default=None, min_length=1, max_length=120)
    gpa_requirement: Optional[str] = Field(default=None, max_length=120)
    recruiting_timeline: Optional[str] = Field(default=None, max_length=240)
    contact_email: Optional[EmailStr] = None
    description: Optional[str] = Field(default=None, min_length=10, max_length=2000)


def _validate_controlled(body_positions: List[str], body_level: str, body_grad_years: List[int]):
    bad_pos = [p for p in body_positions if p not in ALLOWED_POSITIONS]
    if bad_pos:
        raise HTTPException(status_code=400, detail=f"Invalid positions: {bad_pos}. Allowed: {ALLOWED_POSITIONS}")
    if body_level not in ALLOWED_LEVELS:
        raise HTTPException(status_code=400, detail=f"Invalid level. Allowed: {ALLOWED_LEVELS}")
    current_year = datetime.now(timezone.utc).year
    for y in body_grad_years:
        if y < current_year - 1 or y > current_year + 8:
            raise HTTPException(status_code=400, detail=f"Graduation year {y} out of reasonable range.")


# ---------- CREATE ----------

@router.post("/scout-listings")
async def create_scout_listing(
    body: ScoutListingCreate,
    current_user: dict = Depends(get_current_user),
):
    _require_scout_role(current_user)
    _validate_controlled(body.positions, body.level, body.grad_years)

    listing_id = str(uuid.uuid4())
    doc = {
        "id": listing_id,
        "user_id": current_user["id"],
        "author_name": current_user.get("name", ""),
        "school_name": body.school_name.strip(),
        "school_logo_url": None,
        "school_logo_path": None,
        "website_url": str(body.website_url) if body.website_url else None,
        "positions": body.positions,
        "grad_years": sorted(set(body.grad_years)),
        "level": body.level,
        "region": body.region.strip(),
        "gpa_requirement": (body.gpa_requirement or "").strip() or None,
        "recruiting_timeline": (body.recruiting_timeline or "").strip() or None,
        "contact_email": body.contact_email.lower(),
        "description": body.description.strip(),
        "verified": False,
        "verified_at": None,
        "verified_by": None,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    await db.scout_listings.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


# ---------- LIST (public with redaction) ----------

@router.get("/scout-listings")
async def list_scout_listings(
    positions: Optional[str] = Query(default=None, description="Comma-separated position codes"),
    grad_years: Optional[str] = Query(default=None, description="Comma-separated years"),
    level: Optional[str] = None,
    region: Optional[str] = None,
    q: Optional[str] = Query(default=None, description="Search by school name or description"),
    verified_only: bool = True,
    limit: int = Query(default=50, ge=1, le=100),
):
    """Public listings feed. No auth required.

    Contact fields (website_url / contact_email) are NEVER returned on the list
    endpoint — viewers have to open the detail page (where auth is checked) to
    see them. This reduces scraping risk on the bulk endpoint.
    """
    mongo_filter: dict = {}
    if verified_only:
        mongo_filter["verified"] = True
    if positions:
        pos_list = [p.strip().upper() for p in positions.split(",") if p.strip()]
        mongo_filter["positions"] = {"$in": pos_list}
    if grad_years:
        try:
            year_list = [int(y.strip()) for y in grad_years.split(",") if y.strip()]
            if year_list:
                mongo_filter["grad_years"] = {"$in": year_list}
        except ValueError:
            raise HTTPException(status_code=400, detail="grad_years must be comma-separated integers")
    if level:
        mongo_filter["level"] = level
    if region:
        mongo_filter["region"] = {"$regex": re.escape(region), "$options": "i"}
    if q:
        q_pattern = {"$regex": re.escape(q), "$options": "i"}
        mongo_filter["$or"] = [{"school_name": q_pattern}, {"description": q_pattern}]

    listings = await db.scout_listings.find(
        mongo_filter,
        {
            "_id": 0, "contact_email": 0, "website_url": 0,
            "school_logo_path": 0, "verified_by": 0,
        },
    ).sort("created_at", -1).to_list(limit)

    for listing in listings:
        listing["_contact_gated"] = True
    return listings


@router.get("/scout-listings/my")
async def my_scout_listings(current_user: dict = Depends(get_current_user)):
    """Listings owned by the current user, with view + click insights."""
    return await my_listings_with_insights(current_user["id"])


# ---------- DETAIL (public, contact redacted for anon) ----------

async def _optional_user(authorization: Optional[str]) -> Optional[dict]:
    """Decode Authorization header if present; return None if missing or bad."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        import jwt as _jwt
        from db import JWT_SECRET
        token = authorization.split(" ")[1]
        payload = _jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
        return user
    except Exception:
        return None


@router.get("/scout-listings/{listing_id}")
async def get_scout_listing(
    listing_id: str,
    authorization: Optional[str] = Header(default=None),
    user_agent: Optional[str] = Header(default=None),
    x_forwarded_for: Optional[str] = Header(default=None),
):
    listing = await db.scout_listings.find_one({"id": listing_id}, {"_id": 0, "school_logo_path": 0})
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    viewer = await _optional_user(authorization)
    viewer_id = viewer["id"] if viewer else None
    # Only the owner viewing their own listing should NOT count as a view.
    if not viewer or viewer_id != listing.get("user_id"):
        anon_fingerprint = None
        if not viewer_id:
            anon_fingerprint = f"{x_forwarded_for or 'noip'}|{user_agent or 'noua'}"
        try:
            await record_view(listing_id, viewer_user_id=viewer_id, anon_fingerprint=anon_fingerprint)
        except Exception:
            # View tracking is best-effort — never block a listing fetch on it
            pass

    if not viewer:
        return _redact_contact(listing)
    return listing


@router.post("/scout-listings/{listing_id}/contact-click")
async def record_contact_click(
    listing_id: str,
    authorization: Optional[str] = Header(default=None),
    user_agent: Optional[str] = Header(default=None),
    x_forwarded_for: Optional[str] = Header(default=None),
):
    """Frontend pings this when a viewer clicks the website link or contact email."""
    if not await db.scout_listings.find_one({"id": listing_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="Listing not found")
    viewer = await _optional_user(authorization)
    viewer_id = viewer["id"] if viewer else None
    anon_fp = None if viewer_id else f"{x_forwarded_for or 'noip'}|{user_agent or 'noua'}"
    await record_view(listing_id, viewer_user_id=viewer_id, anon_fingerprint=anon_fp, event="contact_click")
    return {"status": "ok"}


@router.get("/scout-listings/{listing_id}/insights")
async def get_listing_insights(
    listing_id: str, current_user: dict = Depends(get_current_user)
):
    """Owner-only insights — view + click counts across rolling windows."""
    listing = await db.scout_listings.find_one(
        {"id": listing_id, "user_id": current_user["id"]}, {"_id": 0, "id": 1}
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return await listing_insights(listing_id)


# ---------- UPDATE ----------

@router.patch("/scout-listings/{listing_id}")
async def update_scout_listing(
    listing_id: str,
    body: ScoutListingUpdate,
    current_user: dict = Depends(get_current_user),
):
    listing = await db.scout_listings.find_one(
        {"id": listing_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    updates = body.model_dump(exclude_unset=True)
    if "website_url" in updates and updates["website_url"] is not None:
        updates["website_url"] = str(updates["website_url"])
    if "contact_email" in updates and updates["contact_email"] is not None:
        updates["contact_email"] = updates["contact_email"].lower()
    if any(k in updates for k in ("positions", "level", "grad_years")):
        positions = updates.get("positions", listing.get("positions", []))
        level = updates.get("level", listing.get("level"))
        grad_years = updates.get("grad_years", listing.get("grad_years", []))
        _validate_controlled(positions, level, grad_years)

    # Any edit resets verification so admin re-approves.
    updates["verified"] = False
    updates["verified_at"] = None
    updates["verified_by"] = None
    updates["updated_at"] = _now_iso()

    await db.scout_listings.update_one({"id": listing_id}, {"$set": updates})
    doc = await db.scout_listings.find_one({"id": listing_id}, {"_id": 0})
    return doc


# ---------- DELETE ----------

@router.delete("/scout-listings/{listing_id}")
async def delete_scout_listing(
    listing_id: str,
    current_user: dict = Depends(get_current_user),
):
    listing = await db.scout_listings.find_one(
        {"id": listing_id, "user_id": current_user["id"]}, {"_id": 0, "id": 1}
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    await db.scout_listings.delete_one({"id": listing_id})
    return {"status": "deleted", "id": listing_id}


# ---------- LOGO UPLOAD ----------

@router.post("/scout-listings/{listing_id}/logo")
async def upload_scout_listing_logo(
    listing_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    listing = await db.scout_listings.find_one(
        {"id": listing_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large (max 5MB)")

    ext = (file.filename or "logo.png").split(".")[-1][:6]
    storage_path = f"{APP_NAME}/scout-listings/{current_user['id']}/{listing_id}.{ext}"
    await run_in_threadpool(put_object_sync, storage_path, data, file.content_type)

    logo_url = f"/api/scout-listings/{listing_id}/logo/view"
    await db.scout_listings.update_one(
        {"id": listing_id},
        {"$set": {"school_logo_url": logo_url, "school_logo_path": storage_path}},
    )
    return {"url": logo_url}


@router.get("/scout-listings/{listing_id}/logo/view")
async def view_scout_listing_logo(listing_id: str):
    listing = await db.scout_listings.find_one(
        {"id": listing_id}, {"_id": 0, "school_logo_path": 1}
    )
    if not listing or not listing.get("school_logo_path"):
        raise HTTPException(status_code=404, detail="No logo")
    try:
        from fastapi.responses import Response
        data, content_type = await run_in_threadpool(get_object_sync, listing["school_logo_path"])
        return Response(content=data, media_type=content_type)
    except Exception:
        raise HTTPException(status_code=404, detail="Logo not found")


# ---------- ADMIN: verification queue ----------

@router.get("/admin/scout-listings")
async def admin_list_scout_listings(
    status: str = Query(default="pending", pattern="^(pending|verified|all)$"),
    current_user: dict = Depends(get_current_user),
):
    _require_admin(current_user)
    mongo_filter: dict = {}
    if status == "pending":
        mongo_filter = {"verified": {"$ne": True}}
    elif status == "verified":
        mongo_filter = {"verified": True}
    listings = await db.scout_listings.find(
        mongo_filter, {"_id": 0}
    ).sort("created_at", -1).to_list(500)
    return listings


@router.post("/admin/scout-listings/{listing_id}/verify")
async def admin_verify_scout_listing(
    listing_id: str, current_user: dict = Depends(get_current_user)
):
    _require_admin(current_user)
    listing = await db.scout_listings.find_one({"id": listing_id}, {"_id": 0, "id": 1})
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    await db.scout_listings.update_one(
        {"id": listing_id},
        {"$set": {
            "verified": True,
            "verified_at": _now_iso(),
            "verified_by": current_user["id"],
        }},
    )
    return {"status": "verified"}


@router.post("/admin/scout-listings/{listing_id}/unverify")
async def admin_unverify_scout_listing(
    listing_id: str, current_user: dict = Depends(get_current_user)
):
    _require_admin(current_user)
    listing = await db.scout_listings.find_one({"id": listing_id}, {"_id": 0, "id": 1})
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    await db.scout_listings.update_one(
        {"id": listing_id},
        {"$set": {"verified": False, "verified_at": None, "verified_by": None}},
    )
    return {"status": "unverified"}


@router.post("/admin/scout-listings/send-weekly-digest")
async def admin_send_scout_digest(current_user: dict = Depends(get_current_user)):
    """Admin-only: manually trigger the weekly scout digest for testing."""
    _require_admin(current_user)
    return await send_weekly_digest(triggered_by="manual")
