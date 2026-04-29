"""Folder CRUD + folder sharing (public folder + match detail).

NOTE: Public video streaming for shared folders (`/shared/{token}/video/{id}`)
remains in server.py because it needs `read_chunk_data` from the chunked-upload
pipeline.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from datetime import datetime, timezone
import uuid
from db import db
from routes.auth import get_current_user

router = APIRouter()


class Folder(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    name: str
    parent_id: Optional[str] = None
    is_private: bool = False
    share_token: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FolderCreate(BaseModel):
    name: str
    parent_id: Optional[str] = None
    is_private: bool = False


class FolderUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[str] = None
    is_private: Optional[bool] = None


# ===== CRUD =====

@router.post("/folders")
async def create_folder(input: FolderCreate, current_user: dict = Depends(get_current_user)):
    if input.parent_id:
        parent = await db.folders.find_one(
            {"id": input.parent_id, "user_id": current_user["id"]}, {"_id": 0}
        )
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found")
    folder = Folder(user_id=current_user["id"], **input.model_dump())
    await db.folders.insert_one(folder.model_dump())
    return folder.model_dump()


@router.get("/folders")
async def get_folders(current_user: dict = Depends(get_current_user)):
    return await db.folders.find({"user_id": current_user["id"]}, {"_id": 0}).to_list(500)


@router.patch("/folders/{folder_id}")
async def update_folder(
    folder_id: str, input: FolderUpdate, current_user: dict = Depends(get_current_user)
):
    folder = await db.folders.find_one(
        {"id": folder_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    updates = {k: v for k, v in input.model_dump().items() if v is not None}
    if updates:
        await db.folders.update_one({"id": folder_id}, {"$set": updates})
    return {"status": "updated"}


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, current_user: dict = Depends(get_current_user)):
    folder = await db.folders.find_one(
        {"id": folder_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    # Move children up to grandparent
    await db.folders.update_many(
        {"parent_id": folder_id, "user_id": current_user["id"]},
        {"$set": {"parent_id": folder.get("parent_id")}},
    )
    await db.matches.update_many(
        {"folder_id": folder_id, "user_id": current_user["id"]},
        {"$set": {"folder_id": folder.get("parent_id")}},
    )
    await db.folders.delete_one({"id": folder_id})
    return {"status": "deleted"}


# ===== Sharing =====

@router.post("/folders/{folder_id}/share")
async def toggle_folder_share(
    folder_id: str, current_user: dict = Depends(get_current_user)
):
    """Generate or revoke a share token for a public folder."""
    folder = await db.folders.find_one(
        {"id": folder_id, "user_id": current_user["id"]}, {"_id": 0}
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    if folder.get("is_private"):
        raise HTTPException(
            status_code=400,
            detail="Cannot share a private folder. Set it to public first.",
        )

    if folder.get("share_token"):
        await db.folders.update_one({"id": folder_id}, {"$set": {"share_token": None}})
        return {"status": "unshared", "share_token": None}
    token = str(uuid.uuid4())[:12]
    await db.folders.update_one({"id": folder_id}, {"$set": {"share_token": token}})
    return {"status": "shared", "share_token": token}


@router.get("/shared/{share_token}")
async def get_shared_folder(share_token: str):
    """Public: view a shared folder and its matches."""
    folder = await db.folders.find_one(
        {"share_token": share_token, "is_private": False}, {"_id": 0}
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Shared folder not found or link expired")

    matches = await db.matches.find(
        {"folder_id": folder["id"], "user_id": folder["user_id"]}, {"_id": 0}
    ).to_list(500)

    for match in matches:
        if match.get("video_id"):
            video = await db.videos.find_one(
                {"id": match["video_id"]},
                {"_id": 0, "processing_status": 1, "processing_progress": 1},
            )
            if video:
                match["processing_status"] = video.get("processing_status", "none")

    owner = await db.users.find_one(
        {"id": folder["user_id"]}, {"_id": 0, "name": 1, "role": 1}
    )

    return {
        "folder": {"id": folder["id"], "name": folder["name"]},
        "owner": {
            "name": owner.get("name", "Coach") if owner else "Coach",
            "role": owner.get("role", "") if owner else "",
        },
        "matches": matches,
    }


@router.get("/shared/{share_token}/match/{match_id}")
async def get_shared_match_detail(share_token: str, match_id: str):
    """Public: view a specific match's analyses, clips, annotations, and roster."""
    folder = await db.folders.find_one(
        {"share_token": share_token, "is_private": False}, {"_id": 0}
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Shared folder not found or link expired")

    match = await db.matches.find_one(
        {"id": match_id, "folder_id": folder["id"], "user_id": folder["user_id"]},
        {"_id": 0},
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found in this shared folder")

    result: dict = {"match": match, "folder_name": folder["name"]}

    if match.get("video_id"):
        video = await db.videos.find_one(
            {"id": match["video_id"]},
            {"_id": 0, "id": 1, "processing_status": 1, "original_filename": 1, "size": 1},
        )
        result["video"] = video

        result["analyses"] = await db.analyses.find(
            {
                "video_id": match["video_id"],
                "user_id": folder["user_id"],
                "status": "completed",
            },
            {"_id": 0},
        ).to_list(10)

        result["clips"] = await db.clips.find(
            {"video_id": match["video_id"], "user_id": folder["user_id"]}, {"_id": 0}
        ).to_list(100)

        result["annotations"] = await db.annotations.find(
            {"video_id": match["video_id"], "user_id": folder["user_id"]}, {"_id": 0}
        ).to_list(500)

    result["players"] = await db.players.find(
        {"match_id": match_id, "user_id": folder["user_id"]}, {"_id": 0}
    ).to_list(100)

    return result
