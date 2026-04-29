"""Coach Annotation Templates — quick-pick phrases coaches reuse across matches.

Templates are scoped per-user and per annotation_type (note / tactical / key_moment).
The /use endpoint increments usage_count so the most-used templates float to the top
of the chip row in the annotation form.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, constr
from db import db
from routes.auth import get_current_user

router = APIRouter()

ANNOTATION_TYPES = {"note", "tactical", "key_moment"}

# First-time seeds — coach-tested phrases from the most common feedback patterns
DEFAULT_TEMPLATES = [
    ("note", "Good decision-making under pressure"),
    ("note", "Off-ball positioning needs work"),
    ("note", "Excellent first touch"),
    ("tactical", "Pressing trigger — won the ball high"),
    ("tactical", "Weak-side coverage broken down"),
    ("tactical", "Transition from defense to attack too slow"),
    ("tactical", "Compact defensive shape"),
    ("key_moment", "Goal — well-worked team move"),
    ("key_moment", "Defensive error — must review with player"),
    ("key_moment", "Game-changing moment"),
]


class TemplateCreate(BaseModel):
    text: constr(strip_whitespace=True, min_length=1, max_length=200)
    annotation_type: str = Field(...)


def _validate_type(annotation_type: str) -> str:
    if annotation_type not in ANNOTATION_TYPES:
        raise HTTPException(status_code=400, detail=f"annotation_type must be one of {sorted(ANNOTATION_TYPES)}")
    return annotation_type


async def _ensure_seeded(user_id: str):
    """First-time seed of default templates so coaches see useful phrases on day 1."""
    existing = await db.annotation_templates.count_documents({"user_id": user_id})
    if existing > 0:
        return
    docs = []
    now = datetime.now(timezone.utc).isoformat()
    for atype, text in DEFAULT_TEMPLATES:
        docs.append({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "annotation_type": atype,
            "text": text,
            "usage_count": 0,
            "is_default": True,
            "created_at": now,
        })
    await db.annotation_templates.insert_many(docs)


@router.get("/annotation-templates")
async def list_templates(
    annotation_type: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
) -> List[dict]:
    """List the user's templates, sorted by usage_count desc + created_at asc.
    Optional `?annotation_type=note|tactical|key_moment` filter.
    """
    await _ensure_seeded(current_user["id"])
    q: dict = {"user_id": current_user["id"]}
    if annotation_type:
        _validate_type(annotation_type)
        q["annotation_type"] = annotation_type
    cursor = db.annotation_templates.find(q, {"_id": 0, "user_id": 0}).sort([("usage_count", -1), ("created_at", 1)])
    return await cursor.to_list(50)


@router.post("/annotation-templates")
async def create_template(input: TemplateCreate, current_user: dict = Depends(get_current_user)):
    _validate_type(input.annotation_type)
    # Prevent exact-duplicate templates per user/type
    existing = await db.annotation_templates.find_one(
        {"user_id": current_user["id"], "annotation_type": input.annotation_type, "text": input.text},
        {"_id": 0, "id": 1},
    )
    if existing:
        return {"id": existing["id"], "duplicate": True}
    doc = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "annotation_type": input.annotation_type,
        "text": input.text,
        "usage_count": 0,
        "is_default": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.annotation_templates.insert_one(doc)
    doc.pop("_id", None)
    doc.pop("user_id", None)
    return doc


@router.delete("/annotation-templates/{template_id}")
async def delete_template(template_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.annotation_templates.delete_one(
        {"id": template_id, "user_id": current_user["id"]}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"status": "deleted"}


@router.post("/annotation-templates/{template_id}/use")
async def increment_template_usage(template_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.annotation_templates.update_one(
        {"id": template_id, "user_id": current_user["id"]},
        {"$inc": {"usage_count": 1}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"status": "ok"}
