"""Annotations CRUD."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from datetime import datetime, timezone
import uuid
from db import db
from routes.auth import get_current_user

router = APIRouter()


class Annotation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    video_id: str
    user_id: str
    timestamp: float
    annotation_type: str
    content: str
    position: Optional[dict] = None
    source: Optional[str] = None
    transcript: Optional[str] = None
    classification_confidence: Optional[float] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AnnotationCreate(BaseModel):
    video_id: str
    timestamp: float
    annotation_type: str
    content: str
    position: Optional[dict] = None
    player_id: Optional[str] = None


@router.post("/annotations", response_model=Annotation)
async def create_annotation(
    input: AnnotationCreate, current_user: dict = Depends(get_current_user)
):
    annotation_obj = Annotation(user_id=current_user["id"], **input.model_dump())
    await db.annotations.insert_one(annotation_obj.model_dump())
    return annotation_obj


@router.get("/annotations/video/{video_id}", response_model=List[Annotation])
async def get_annotations(
    video_id: str, current_user: dict = Depends(get_current_user)
):
    return await db.annotations.find(
        {"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(1000)


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(
    annotation_id: str, current_user: dict = Depends(get_current_user)
):
    result = await db.annotations.delete_one(
        {"id": annotation_id, "user_id": current_user["id"]}
    )
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"message": "Annotation deleted"}
