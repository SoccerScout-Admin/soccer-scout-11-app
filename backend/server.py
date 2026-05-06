from fastapi import FastAPI, APIRouter, HTTPException, Header, UploadFile, File, Depends, Request, Query
from fastapi.responses import Response, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from motor.motor_asyncio import AsyncIOMotorClient
import os
import re
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import jwt
import bcrypt
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
import tempfile
import asyncio
import time
import subprocess
from bson import Binary

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "soccer-analysis"
storage_key = None
JWT_SECRET = os.environ.get("JWT_SECRET")
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB per chunk
from runtime import SERVER_BOOT_ID, SERVER_BOOT_TIME  # single source of truth

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== Import modular routes =====
from routes.teams import router as teams_router
from routes.og import router as og_router
from routes.players import router as players_router
from routes.player_profile import router as player_profile_router
from routes.folders import router as folders_router
from routes.matches import router as matches_router
from routes.annotations import router as annotations_router
from routes.analysis import router as analysis_router
from routes.insights import router as insights_router
from routes.season_trends import router as season_trends_router
from routes.player_trends import router as player_trends_router
from routes.coach_network import router as coach_network_router
from routes.videos import router as videos_router
from routes.annotation_templates import router as annotation_templates_router
from routes.coach_pulse import router as coach_pulse_router
from routes.push_notifications import router as push_notifications_router
from routes.voice_annotations import router as voice_annotations_router
from routes.spoken_summary import router as spoken_summary_router
from routes.admin import router as admin_router
from routes.scouting_packets import router as scouting_packets_router
from routes.password_reset import router as password_reset_router
from routes.scout_listings import router as scout_listings_router
from routes.messaging import router as messaging_router

# ===== Storage: Delegated to services/storage.py =====
# All storage primitives (create_storage_session, init_storage, put_object_sync,
# get_object_sync, store_chunk, read_chunk_data, circuit breaker) live in
# services/storage.py. server.py imports and re-exports them so existing call
# sites (upload/download endpoints, video streaming, clip extraction) work.
from services.storage import (
    create_storage_session,  # noqa: F401
    init_storage,
    reset_storage,  # noqa: F401
    put_object_sync,
    put_object_with_retry,  # noqa: F401
    get_object_sync,
    delete_object_sync,  # noqa: F401
    store_chunk,
    read_chunk_data,
    storage_breaker,  # noqa: F401
    _write_file,  # noqa: F401
    _read_file,  # noqa: F401
)

CHUNK_STORAGE_DIR = "/var/video_chunks"
os.makedirs(CHUNK_STORAGE_DIR, exist_ok=True)


# Legacy wrappers (still referenced by non-chunked upload paths)
def put_object(path, data, content_type):
    return put_object_sync(path, data, content_type)


def get_object(path):
    return get_object_sync(path)


# ===== Models =====

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "analyst"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class AuthResponse(BaseModel):
    token: str
    user: dict

class Match(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    team_home: str
    team_away: str
    date: str
    competition: str = ""
    folder_id: Optional[str] = None
    video_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class MatchCreate(BaseModel):
    team_home: str
    team_away: str
    date: str
    competition: str = ""
    folder_id: Optional[str] = None

class Video(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    match_id: str
    user_id: str
    storage_path: str
    original_filename: str
    content_type: str
    size: int
    duration: Optional[int] = None
    is_deleted: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class Analysis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    video_id: str
    match_id: str
    user_id: str
    analysis_type: str
    content: str
    status: str = "completed"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class AnalysisRequest(BaseModel):
    video_id: str
    analysis_type: str

class Annotation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    video_id: str
    user_id: str
    timestamp: float
    annotation_type: str
    content: str
    position: Optional[dict] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class AnnotationCreate(BaseModel):
    video_id: str
    timestamp: float
    annotation_type: str
    content: str
    position: Optional[dict] = None
    player_id: Optional[str] = None

class Clip(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    video_id: str
    match_id: str
    user_id: str
    title: str
    start_time: float
    end_time: float
    clip_type: str = "highlight"
    description: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class ClipCreate(BaseModel):
    video_id: str
    title: str
    start_time: float
    end_time: float
    clip_type: str = "highlight"
    description: str = ""
    player_ids: List[str] = []

class ChunkedUploadInit(BaseModel):
    match_id: str
    filename: str
    file_size: int
    content_type: str = "video/mp4"

# ===== Folder Models =====

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

# ===== Player/Roster Models =====

class Player(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    match_id: Optional[str] = None
    team_id: Optional[str] = None
    name: str
    number: Optional[int] = None
    position: str = ""
    team: str = ""
    profile_pic_url: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class PlayerCreate(BaseModel):
    match_id: Optional[str] = None
    team_id: Optional[str] = None
    name: str
    number: Optional[int] = None
    position: str = ""
    team: str = ""

class PlayerBulkImport(BaseModel):
    match_id: Optional[str] = None
    team_id: Optional[str] = None
    csv_data: str
    team: str = ""

# ===== Auth =====

def create_token(user_id: str, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=7)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
    token = authorization.split(" ")[1]
    payload = verify_token(token)
    user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

async def get_user_from_token_param(token: str) -> dict:
    """Authenticate via query parameter token (for <video src> tags)"""
    payload = verify_token(token)
    user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# ===== Auth Endpoints =====

@api_router.post("/auth/register", response_model=AuthResponse)
async def register(input: RegisterRequest):
    existing = await db.users.find_one({"email": input.email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    hashed = bcrypt.hashpw(input.password.encode('utf-8'), bcrypt.gensalt(rounds=12))
    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "email": input.email,
        "password": hashed.decode('utf-8'),
        "name": input.name,
        "role": input.role,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    token = create_token(user_id, input.email)
    logger.info(f"New user registered: {input.email}")
    return AuthResponse(token=token, user={"id": user_id, "email": input.email, "name": input.name, "role": input.role})

@api_router.post("/auth/login", response_model=AuthResponse)
async def login(input: LoginRequest):
    user = await db.users.find_one({"email": input.email}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    try:
        if not bcrypt.checkpw(input.password.encode('utf-8'), user["password"].encode('utf-8')):
            raise HTTPException(status_code=401, detail="Invalid email or password")
    except Exception as e:
        logger.error(f"Bcrypt error during login for {input.email}: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(user["id"], user["email"])
    return AuthResponse(token=token, user={"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]})

@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {"id": current_user["id"], "email": current_user["email"], "name": current_user["name"], "role": current_user["role"]}

# ===== Health =====

@api_router.get("/health")
async def health_check():
    try:
        await db.command('ping')
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    return {"status": "healthy", "service": "soccer-scout-api", "database": db_status, "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/health")
async def root_health_check():
    return {"status": "healthy", "service": "soccer-scout-api", "timestamp": datetime.now(timezone.utc).isoformat()}

# ===== Heartbeat =====

@api_router.get("/heartbeat")
async def heartbeat():
    """Returns server boot ID — if it changes, the server restarted"""
    return {
        "boot_id": SERVER_BOOT_ID,
        "boot_time": SERVER_BOOT_TIME,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# ===== Debug =====

@api_router.get("/debug/match/{match_id}")
async def debug_match(match_id: str, current_user: dict = Depends(get_current_user)):
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    return {"match_exists": match is not None, "match_id": match_id, "user_id": current_user["id"], "match": match}

# ===== Matches =====
# Match CRUD has moved to routes/matches.py and is mounted via matches_router.
# Only video-related match operations stay below (deleted-videos restore is in matches.py).

# ===== Folders =====
# Folder CRUD + sharing moved to routes/folders.py.
# The public video stream endpoint stays here because it depends on
# `read_chunk_data` from the chunked-upload pipeline.

@api_router.get("/shared/{share_token}/video/{video_id}")
async def stream_shared_video(share_token: str, video_id: str, request: Request):
    """Public endpoint: stream a video from a shared folder (no auth)"""
    folder = await db.folders.find_one({"share_token": share_token, "is_private": False}, {"_id": 0})
    if not folder:
        raise HTTPException(status_code=404, detail="Invalid share link")
    
    video = await db.videos.find_one({"id": video_id, "user_id": folder["user_id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Verify match is in shared folder
    match = await db.matches.find_one({"id": video["match_id"], "folder_id": folder["id"]}, {"_id": 0, "id": 1})
    if not match:
        raise HTTPException(status_code=403, detail="Video not in shared folder")
    
    # Reuse same streaming logic as authenticated endpoint
    total_size = video.get("size", 0)
    content_type = video.get("content_type", "video/mp4")
    
    if video.get("is_chunked"):
        chunk_paths = video.get("chunk_paths", {})
        chunk_backends = video.get("chunk_backends", {})
        total_chunks = video.get("total_chunks", len(chunk_paths))
        
        async def generate_full():
            for i in range(total_chunks):
                path = chunk_paths.get(str(i))
                if not path:
                    continue
                backend = chunk_backends.get(str(i), "storage")
                chunk_info = {"backend": backend, "path": path}
                try:
                    data = await read_chunk_data(video_id, i, chunk_info)
                    yield data
                    del data
                except Exception as e:
                    logger.error(f"Shared stream chunk {i} error: {e}")
                    break
        
        return StreamingResponse(
            generate_full(), media_type=content_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(total_size)}
        )
    else:
        data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
        return Response(content=data, media_type=content_type, headers={"Content-Length": str(len(data))})

# ===== Players / Rosters =====
# Player CRUD has been extracted to routes/players.py and is mounted below
# (search for `players_router`). The duplicate definitions used to live here.

# ===== Standard Video Upload (for files < 1GB) =====

@api_router.post("/videos/upload")
async def upload_video(file: UploadFile = File(...), match_id: str = "", current_user: dict = Depends(get_current_user)):
    if not match_id:
        raise HTTPException(status_code=400, detail="match_id is required")
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    ext = file.filename.split(".")[-1] if "." in file.filename else "mp4"
    video_id = str(uuid.uuid4())
    path = f"{APP_NAME}/videos/{current_user['id']}/{video_id}.{ext}"

    try:
        chunk_size = 5 * 1024 * 1024
        file_data = bytearray()
        while chunk := await file.read(chunk_size):
            file_data.extend(chunk)
        total_size = len(file_data)
        logger.info(f"Uploading {total_size/(1024*1024):.1f}MB to storage...")
        result = await run_in_threadpool(put_object_sync, path, bytes(file_data), file.content_type or "video/mp4")

        video_doc = {
            "id": video_id,
            "match_id": match_id,
            "user_id": current_user["id"],
            "storage_path": result["path"],
            "original_filename": file.filename,
            "content_type": file.content_type or "video/mp4",
            "size": result["size"],
            "is_deleted": False,
            "is_chunked": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.videos.insert_one(video_doc)
        await db.matches.update_one({"id": match_id}, {"$set": {"video_id": video_id}})
        return {"video_id": video_id, "path": result["path"], "size": result["size"]}
    except Exception as e:
        logger.error(f"Video upload failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

# ===== Chunked Upload (for files > 1GB) =====

@api_router.post("/videos/upload/init")
async def init_chunked_upload(input: ChunkedUploadInit, current_user: dict = Depends(get_current_user)):
    match = await db.matches.find_one({"id": input.match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    # Check for existing resumable session
    existing = await db.chunked_uploads.find_one({
        "user_id": current_user["id"],
        "match_id": input.match_id,
        "filename": input.filename,
        "file_size": input.file_size,
        "status": {"$in": ["initialized", "in_progress", "failed"]}
    }, {"_id": 0})

    if existing:
        upload_id = existing["upload_id"]
        video_id = existing["video_id"]
        chunk_paths = existing.get("chunk_paths", {})
        uploaded_chunks = sorted([int(idx) for idx in chunk_paths.keys()])
        stored_chunk_size = existing.get("chunk_size", CHUNK_SIZE)
        if uploaded_chunks:
            logger.info(f"Resuming upload: {upload_id}, {len(uploaded_chunks)} chunks already uploaded")
            return {
                "upload_id": upload_id,
                "video_id": video_id,
                "chunk_size": stored_chunk_size,
                "resume": True,
                "chunks_received": len(uploaded_chunks),
                "uploaded_chunks": uploaded_chunks
            }

    upload_id = str(uuid.uuid4())
    video_id = str(uuid.uuid4())

    upload_doc = {
        "upload_id": upload_id,
        "video_id": video_id,
        "match_id": input.match_id,
        "user_id": current_user["id"],
        "filename": input.filename,
        "file_size": input.file_size,
        "content_type": input.content_type,
        "chunk_size": CHUNK_SIZE,
        "chunks_received": 0,
        "chunk_paths": {},
        "status": "initialized",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_chunk_at": datetime.now(timezone.utc).isoformat()
    }
    await db.chunked_uploads.insert_one(upload_doc)
    logger.info(f"New chunked upload: {upload_id}, video: {video_id}, size: {input.file_size}")
    return {"upload_id": upload_id, "video_id": video_id, "chunk_size": CHUNK_SIZE, "resume": False}

@api_router.get("/videos/upload/status/{upload_id}")
async def get_upload_status(upload_id: str, current_user: dict = Depends(get_current_user)):
    upload = await db.chunked_uploads.find_one({"upload_id": upload_id, "user_id": current_user["id"]}, {"_id": 0})
    if not upload:
        raise HTTPException(status_code=404, detail="Upload session not found")
    chunk_paths = upload.get("chunk_paths", {})
    uploaded_chunks = sorted([int(idx) for idx in chunk_paths.keys()])
    return {
        "upload_id": upload_id,
        "video_id": upload.get("video_id"),
        "filename": upload.get("filename"),
        "file_size": upload.get("file_size"),
        "chunks_received": len(uploaded_chunks),
        "status": upload.get("status"),
        "uploaded_chunks": uploaded_chunks,
        "created_at": upload.get("created_at"),
        "last_chunk_at": upload.get("last_chunk_at")
    }

@api_router.post("/videos/upload/chunk")
async def upload_chunk(
    upload_id: str = "",
    chunk_index: int = 0,
    total_chunks: int = 0,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """Upload a single chunk directly to object storage (non-blocking, with retry)"""
    upload = await db.chunked_uploads.find_one({"upload_id": upload_id, "user_id": current_user["id"]}, {"_id": 0})
    if not upload:
        raise HTTPException(status_code=404, detail="Upload session not found")

    # Check if chunk already uploaded
    existing_chunks = upload.get("chunk_paths", {})
    if str(chunk_index) in existing_chunks:
        logger.info(f"Chunk {chunk_index+1}/{total_chunks} already uploaded, skipping")
        if chunk_index + 1 >= total_chunks:
            return await finalize_chunked_upload(upload_id, total_chunks, current_user)
        return {"status": "chunk_skipped", "chunk_index": chunk_index, "chunks_received": len(existing_chunks), "total_chunks": total_chunks}

    try:
        chunk_data = await file.read()
        chunk_size_bytes = len(chunk_data)

        video_id = upload["video_id"]

        logger.info(f"Storing chunk {chunk_index+1}/{total_chunks} ({chunk_size_bytes} bytes)...")
        # Use store_chunk which tries Object Storage first, falls back to MongoDB
        store_result = await store_chunk(video_id, upload["user_id"], chunk_index, chunk_data)
        # Free memory immediately
        del chunk_data

        # Track chunk in database with backend info
        await db.chunked_uploads.update_one(
            {"upload_id": upload_id},
            {
                "$inc": {"chunks_received": 1},
                "$set": {
                    f"chunk_paths.{chunk_index}": store_result["path"],
                    f"chunk_backends.{chunk_index}": store_result["backend"],
                    f"chunk_sizes.{chunk_index}": chunk_size_bytes,
                    "status": "in_progress",
                    "last_chunk_at": datetime.now(timezone.utc).isoformat()
                }
            }
        )

        logger.info(f"Chunk {chunk_index+1}/{total_chunks} stored ({store_result['backend']})")

        # If all chunks received, finalize
        if chunk_index + 1 >= total_chunks:
            logger.info(f"All {total_chunks} chunks uploaded, finalizing...")
            return await finalize_chunked_upload(upload_id, total_chunks, current_user)

        return {"status": "chunk_received", "chunk_index": chunk_index, "chunks_received": chunk_index + 1, "total_chunks": total_chunks}

    except Exception as e:
        logger.error(f"Chunk {chunk_index} upload failed for {upload_id}: {str(e)}")
        # Don't mark as "failed" so resume is still possible
        raise HTTPException(status_code=500, detail=f"Chunk upload failed: {str(e)}")

@api_router.post("/videos/upload/finalize")
async def finalize_upload_endpoint(upload_id: str = Query(...), current_user: dict = Depends(get_current_user)):
    """Explicit finalize endpoint (called if auto-finalize on last chunk didn't complete)"""
    upload = await db.chunked_uploads.find_one({"upload_id": upload_id, "user_id": current_user["id"]}, {"_id": 0})
    if not upload:
        raise HTTPException(status_code=404, detail="Upload session not found")
    total_chunks_expected = len(upload.get("chunk_paths", {}))
    return await finalize_chunked_upload(upload_id, total_chunks_expected, current_user)

async def finalize_chunked_upload(upload_id: str, total_chunks: int, current_user: dict):
    """
    Finalize upload: NO reassembly - just mark complete and save chunk manifest.
    The video is served by streaming chunks on-demand from storage.
    This avoids loading 10GB+ into memory.
    """
    upload = await db.chunked_uploads.find_one({"upload_id": upload_id}, {"_id": 0})
    if not upload:
        raise HTTPException(status_code=404, detail="Upload session not found")

    chunk_paths = upload.get("chunk_paths", {})
    chunk_sizes = upload.get("chunk_sizes", {})
    actual_chunks = len(chunk_paths)

    logger.info(f"Finalizing upload {upload_id}: {actual_chunks} chunks, no reassembly needed")

    # Calculate total size from chunk sizes
    total_size = sum(chunk_sizes.get(str(i), 0) for i in range(total_chunks))
    if total_size == 0:
        total_size = upload.get("file_size", 0)

    video_doc = {
        "id": upload["video_id"],
        "match_id": upload["match_id"],
        "user_id": upload["user_id"],
        "storage_path": f"chunked:{upload_id}",
        "chunk_paths": chunk_paths,
        "chunk_backends": upload.get("chunk_backends", {}),
        "chunk_sizes": chunk_sizes,
        "total_chunks": actual_chunks,
        "chunk_size": upload.get("chunk_size", CHUNK_SIZE),
        "original_filename": upload["filename"],
        "content_type": upload["content_type"],
        "size": total_size,
        "is_chunked": True,
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.videos.insert_one(video_doc)
    await db.matches.update_one({"id": upload["match_id"]}, {"$set": {"video_id": upload["video_id"]}})
    await db.chunked_uploads.update_one(
        {"upload_id": upload_id},
        {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}}
    )

    logger.info(f"Upload finalized: video {upload['video_id']}, {total_size/(1024*1024*1024):.2f}GB, {actual_chunks} chunks")

    # Auto-start processing (Hudl/Veo-like)
    await db.videos.update_one(
        {"id": upload["video_id"]},
        {"$set": {"processing_status": "queued", "processing_started_at": datetime.now(timezone.utc).isoformat()}}
    )
    asyncio.create_task(run_auto_processing(upload["video_id"], upload["user_id"]))
    logger.info(f"Auto-processing queued for video {upload['video_id']}")

    return {"status": "completed", "video_id": upload["video_id"], "size": total_size, "processing": "queued"}

# ===== Video Serving (streaming with Range support) =====

@api_router.get("/videos/{video_id}")
async def get_video(video_id: str, request: Request, token: str = None, authorization: str = Header(None)):
    """Serve video with streaming and HTTP Range support. Auth via header or ?token= query param."""
    # Authenticate
    if token:
        user = await get_user_from_token_param(token)
    elif authorization and authorization.startswith("Bearer "):
        payload = verify_token(authorization.split(" ")[1])
        user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
    else:
        raise HTTPException(status_code=401, detail="Not authenticated")

    video = await db.videos.find_one({"id": video_id, "user_id": user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    range_header = request.headers.get("range")

    if video.get("is_chunked"):
        return await stream_chunked_video(video, range_header)
    else:
        return await serve_single_video(video, range_header)

async def serve_single_video(video: dict, range_header: str = None):
    """Serve a non-chunked video (single file in storage)"""
    data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
    total_size = len(data)
    content_type = video.get("content_type", "video/mp4")

    if range_header:
        m = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else total_size - 1
            end = min(end, total_size - 1)
            length = end - start + 1
            return Response(
                content=data[start:end+1],
                status_code=206,
                media_type=content_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                }
            )

    return Response(content=data, media_type=content_type, headers={
        "Accept-Ranges": "bytes",
        "Content-Length": str(total_size),
    })

async def stream_chunked_video(video: dict, range_header: str = None):
    """Stream a chunked video from object storage or MongoDB with Range support"""
    chunk_paths = video.get("chunk_paths", {})
    chunk_backends = video.get("chunk_backends", {})
    chunk_sizes = video.get("chunk_sizes", {})
    total_chunks = video.get("total_chunks", len(chunk_paths))
    nominal_chunk_size = video.get("chunk_size", CHUNK_SIZE)
    total_size = video.get("size", 0)
    content_type = video.get("content_type", "video/mp4")
    video_id = video.get("id", "")

    # Build a byte offset map for each chunk
    chunk_offsets = []  # [(start_byte, end_byte, chunk_index, chunk_info)]
    current_offset = 0
    for i in range(total_chunks):
        path = chunk_paths.get(str(i))
        if not path:
            continue
        csize = chunk_sizes.get(str(i), nominal_chunk_size)
        backend = chunk_backends.get(str(i), "storage")
        chunk_info = {"backend": backend, "path": path}
        chunk_offsets.append((current_offset, current_offset + csize - 1, i, chunk_info))
        current_offset += csize

    if total_size == 0:
        total_size = current_offset

    if range_header:
        m = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else total_size - 1
            end = min(end, total_size - 1)
            length = end - start + 1

            async def generate_range():
                bytes_sent = 0
                for (chunk_start, chunk_end, chunk_idx, chunk_info) in chunk_offsets:
                    if chunk_end < start:
                        continue
                    if chunk_start > end:
                        break

                    try:
                        data = await read_chunk_data(video_id, chunk_idx, chunk_info)
                    except (FileNotFoundError, Exception) as e:
                        logger.warning(f"Stream: chunk {chunk_idx} unavailable ({e}), stopping range stream")
                        break

                    slice_start = max(0, start - chunk_start)
                    slice_end = min(len(data), end - chunk_start + 1)
                    chunk_slice = data[slice_start:slice_end]
                    del data

                    yield chunk_slice
                    bytes_sent += len(chunk_slice)
                    if bytes_sent >= length:
                        break

            return StreamingResponse(
                generate_range(),
                status_code=206,
                media_type=content_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{total_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(length),
                }
            )

    # Full stream (no range)
    async def generate_full():
        for i in range(total_chunks):
            path = chunk_paths.get(str(i))
            if path:
                backend = chunk_backends.get(str(i), "storage")
                chunk_info = {"backend": backend, "path": path}
                try:
                    data = await read_chunk_data(video_id, i, chunk_info)
                    yield data
                    del data
                except (FileNotFoundError, Exception) as e:
                    logger.warning(f"Stream: chunk {i} unavailable ({e}), stopping full stream")
                    break

    return StreamingResponse(
        generate_full(),
        media_type=content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(total_size),
        }
    )

# ===== Video Metadata =====

@api_router.delete("/videos/{video_id}")
async def delete_video(video_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a video so the coach can re-upload to the same match.

    Soft-deletes the video record (is_deleted=true), unlinks it from the match,
    deletes associated clips/analyses/timeline_markers, removes any incomplete
    chunked-upload session, and best-effort cleans the chunks from storage and
    local disk so the next upload starts fresh.
    """
    video = await db.videos.find_one(
        {"id": video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0}
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # 1) Mark deleted (preserve audit trail)
    await db.videos.update_one(
        {"id": video_id},
        {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc).isoformat()}},
    )

    # 2) Unlink from match if this was the match's active video
    await db.matches.update_one(
        {"id": video["match_id"], "video_id": video_id},
        {"$unset": {"video_id": "", "duration": "", "processing_status": ""}},
    )

    # 3) Cascade-delete derived data
    await db.clips.delete_many({"video_id": video_id, "user_id": current_user["id"]})
    await db.analyses.delete_many({"video_id": video_id, "user_id": current_user["id"]})
    await db.markers.delete_many({"video_id": video_id, "user_id": current_user["id"]})

    # 4) Best-effort: clean storage chunks (object storage + on-disk fallback)
    if video.get("is_chunked"):
        chunk_paths = video.get("chunk_paths", {}) or {}
        chunk_backends = video.get("chunk_backends", {}) or {}
        for idx_str, path in chunk_paths.items():
            backend = chunk_backends.get(idx_str, "storage")
            try:
                if backend == "filesystem":
                    if path and os.path.exists(path):
                        os.remove(path)
                else:
                    await run_in_threadpool(delete_object_sync, path)
            except Exception:
                pass
        # Drop the orphaned upload session record so the next init is fresh
        upload_id = video.get("storage_path", "").replace("chunked:", "")
        if upload_id:
            await db.chunked_uploads.delete_many({"upload_id": upload_id})
        # Also wipe the per-video chunk dir if any
        try:
            video_dir = os.path.join(CHUNK_STORAGE_DIR, video_id)
            if os.path.isdir(video_dir):
                import shutil
                shutil.rmtree(video_dir, ignore_errors=True)
        except Exception:
            pass
    elif video.get("storage_path"):
        try:
            await run_in_threadpool(delete_object_sync, video["storage_path"])
        except Exception:
            pass

    return {"status": "deleted", "video_id": video_id, "match_id": video["match_id"]}


@api_router.post("/videos/{video_id}/restore")
async def restore_video(video_id: str, current_user: dict = Depends(get_current_user)):
    """Undo a recent video deletion (24h grace window). Re-attaches the video to its match.

    NOTE: Cascade-deleted clips/analyses/markers cannot be restored — they were hard-deleted.
    """
    video = await db.videos.find_one(
        {"id": video_id, "user_id": current_user["id"], "is_deleted": True}, {"_id": 0}
    )
    if not video:
        raise HTTPException(status_code=404, detail="Deleted video not found")
    deleted_at = video.get("deleted_at")
    if not deleted_at:
        raise HTTPException(status_code=400, detail="Video has no deletion timestamp")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    try:
        deleted_dt = datetime.fromisoformat(deleted_at.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid deletion timestamp")
    if deleted_dt < cutoff:
        raise HTTPException(status_code=410, detail="Restore window has expired (24h)")

    # If the match already has a different active video, refuse to clobber it
    match = await db.matches.find_one(
        {"id": video["match_id"], "user_id": current_user["id"]}, {"_id": 0, "video_id": 1}
    )
    if match and match.get("video_id") and match["video_id"] != video_id:
        raise HTTPException(
            status_code=409,
            detail="Match already has another active video. Replace that one first.",
        )

    await db.videos.update_one(
        {"id": video_id},
        {"$set": {"is_deleted": False}, "$unset": {"deleted_at": ""}},
    )
    await db.matches.update_one(
        {"id": video["match_id"]},
        {"$set": {"video_id": video_id, "duration": video.get("duration")}},
    )
    return {"status": "restored", "video_id": video_id}


# ===== Auto-Processing (Hudl/Veo-like) =====
# Core pipeline now lives in services/processing.py. Keep thin wrappers here
# so existing call sites (finalize_chunked_upload, reprocess, generate_analysis,
# generate_trimmed_analysis, resume_interrupted_processing) don't need to change.

def build_roster_context(roster: list) -> str:
    from services.processing import build_roster_context as _f
    return _f(roster)


def build_analysis_prompts(match: dict, roster_context: str, segment_preamble: str) -> dict:
    from services.processing import build_analysis_prompts as _f
    return _f(match, roster_context, segment_preamble)


async def parse_and_store_markers(response: str, video_id: str, match_id: str, user_id: str):
    from services.processing import parse_and_store_markers as _f
    return await _f(response, video_id, match_id, user_id, auto_create_clips_from_markers)


async def run_single_analysis(video_id: str, user_id: str, match_id: str, analysis_type: str, video_file_path: str, prompt: str):
    from services.processing import run_single_analysis as _f
    return await _f(
        video_id, user_id, match_id, analysis_type, video_file_path, prompt,
        auto_create_clips_from_markers,
    )


async def run_auto_processing(video_id: str, user_id: str, only_types: list = None):
    from services.processing import run_auto_processing as _f
    return await _f(video_id, user_id, only_types, auto_create_clips_from_markers)


async def prepare_video_sample(video: dict, trim_start: float = None, trim_end: float = None) -> str:
    from services.processing import prepare_video_sample as _f
    return await _f(video, trim_start, trim_end)


async def prepare_video_segments_720p(video: dict) -> tuple:
    from services.processing import prepare_video_segments_720p as _f
    return await _f(video)


# ===== AI Analysis Endpoints =====

@api_router.post("/videos/{video_id}/reprocess")
async def reprocess_video(video_id: str, current_user: dict = Depends(get_current_user)):
    """Manually trigger reprocessing — only runs analysis types not yet completed"""
    video = await db.videos.find_one({"id": video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Find which types are already completed
    completed = set()
    analyses = await db.analyses.find(
        {"video_id": video_id, "user_id": current_user["id"], "status": "completed"},
        {"_id": 0, "analysis_type": 1}
    ).to_list(10)
    for a in analyses:
        completed.add(a["analysis_type"])
    
    # Delete only failed analyses (keep completed ones)
    await db.analyses.delete_many({"video_id": video_id, "user_id": current_user["id"], "status": "failed"})
    
    remaining = [t for t in ["tactical", "player_performance", "highlights", "timeline_markers"] if t not in completed]
    
    if not remaining:
        return {"status": "already_complete", "completed_types": list(completed)}
    
    await db.videos.update_one(
        {"id": video_id},
        {"$set": {"processing_status": "queued", "processing_progress": 0, "processing_error": None}}
    )
    asyncio.create_task(run_auto_processing(video_id, current_user["id"], only_types=remaining))
    return {"status": "reprocessing_started", "types_to_process": remaining, "already_completed": list(completed)}

@api_router.post("/analysis/generate")
async def generate_analysis(input: AnalysisRequest, current_user: dict = Depends(get_current_user)):
    """Manual single analysis generation"""
    video = await db.videos.find_one({"id": input.video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})

    # Fetch roster for richer prompts
    roster = await db.players.find({"match_id": video["match_id"]}, {"_id": 0}).to_list(100)
    roster_context = ""
    if roster:
        roster_lines = [f"#{p.get('number', '?')} {p['name']} ({p.get('position', '')}) - {p.get('team', '')}" for p in roster]
        roster_context = "\n\nKnown Players:\n" + "\n".join(roster_lines)

    tmp_path = None
    try:
        tmp_path = await prepare_video_sample(video)

        chat = LlmChat(
            api_key=EMERGENT_KEY,
            session_id=f"analysis-{input.video_id}",
            system_message="You are an expert soccer analyst. You will receive video samples from multiple points throughout the match. Analyze the full match based on these samples and provide detailed tactical insights."
        ).with_model("gemini", "gemini-3.1-pro-preview")

        video_file = FileContentWithMimeType(file_path=tmp_path, mime_type="video/mp4")

        prompts = {
            "tactical": f"Analyze this soccer match video between {match['team_home']} and {match['team_away']}. Provide detailed tactical analysis.{roster_context}",
            "player_performance": f"Analyze individual player performances in this match between {match['team_home']} and {match['team_away']}.{roster_context}",
            "highlights": f"Identify key moments and highlights from this match between {match['team_home']} and {match['team_away']}.{roster_context}"
        }
        prompt = prompts.get(input.analysis_type, prompts["tactical"])
        response = await chat.send_message(UserMessage(text=prompt, file_contents=[video_file]))

        # Delete old analysis of same type
        await db.analyses.delete_many({"video_id": input.video_id, "user_id": current_user["id"], "analysis_type": input.analysis_type})

        analysis_id = str(uuid.uuid4())
        analysis_doc = {
            "id": analysis_id,
            "video_id": input.video_id,
            "match_id": video["match_id"],
            "user_id": current_user["id"],
            "analysis_type": input.analysis_type,
            "content": response,
            "status": "completed",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.analyses.insert_one(analysis_doc)
        return {"analysis_id": analysis_id, "content": response, "status": "completed"}
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

# ===== Analysis (read endpoints moved to routes/analysis.py) =====
# AI generation endpoints stay below because they depend on the auto-processing pipeline.

# ===== Annotations =====
# Annotation CRUD moved to routes/annotations.py

# ===== Clips =====

@api_router.post("/clips", response_model=Clip)
async def create_clip(input: ClipCreate, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one({"id": input.video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    clip_obj = Clip(user_id=current_user["id"], match_id=video["match_id"], **input.model_dump())
    await db.clips.insert_one(clip_obj.model_dump())
    return clip_obj

@api_router.get("/clips", response_model=List[Clip])
async def list_all_user_clips(
    limit: int = 500,
    match_id: Optional[str] = None,
    player_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """List clips for the current user, most recent first. Optional filters:
    `match_id` (all clips for one match) and `player_id` (clips where the
    player is tagged). Powers cross-match bulk share, scouting packets, and
    the iter12 mention E2E test fixture.
    """
    query: dict = {"user_id": current_user["id"]}
    if match_id:
        query["match_id"] = match_id
    if player_id:
        query["player_ids"] = player_id
    clips = await db.clips.find(query, {"_id": 0}).sort("created_at", -1).to_list(max(1, min(limit, 2000)))
    return clips


@api_router.get("/clips/video/{video_id}", response_model=List[Clip])
async def get_clips(video_id: str, current_user: dict = Depends(get_current_user)):
    clips = await db.clips.find({"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(1000)
    return clips

@api_router.delete("/clips/{clip_id}")
async def delete_clip(clip_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.clips.delete_one({"id": clip_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Clip not found")
    return {"message": "Clip deleted"}


class ClipUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    clip_type: Optional[str] = None
    player_ids: Optional[List[str]] = None


@api_router.patch("/clips/{clip_id}")
async def update_clip(clip_id: str, body: ClipUpdate, current_user: dict = Depends(get_current_user)):
    """Edit clip metadata (used primarily for player tagging after creation)."""
    clip = await db.clips.find_one({"id": clip_id, "user_id": current_user["id"]}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    # If player_ids are being set, validate they all exist and belong to this user
    if "player_ids" in updates and updates["player_ids"]:
        owned = await db.players.count_documents(
            {"id": {"$in": updates["player_ids"]}, "user_id": current_user["id"]}
        )
        if owned != len(updates["player_ids"]):
            raise HTTPException(
                status_code=400, detail="One or more player_ids are unknown or not yours"
            )
    if not updates:
        return {"status": "noop"}
    await db.clips.update_one({"id": clip_id}, {"$set": updates})
    return {"status": "updated", **updates}

# ===== Highlights =====
# `/highlights/video/{video_id}` moved to routes/analysis.py.

@api_router.get("/clips/{clip_id}/download")
async def download_clip_info(clip_id: str, current_user: dict = Depends(get_current_user)):
    clip = await db.clips.find_one({"id": clip_id, "user_id": current_user["id"]}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    video = await db.videos.find_one({"id": clip["video_id"]}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return {
        "clip": clip,
        "video_url": f"/api/videos/{video['id']}",
        "download_instructions": "Use the start_time and end_time to extract the clip from the video"
    }

# ===== Timeline Markers =====
# `/markers/video/{video_id}` moved to routes/analysis.py.

# ===== Clip Video Download (actual MP4 extraction) =====

@api_router.post("/clips/{clip_id}/ai-suggest-tags")
async def ai_suggest_clip_tags(clip_id: str, current_user: dict = Depends(get_current_user)):
    """Extract a frame from the clip and ask Gemini Vision which jersey numbers
    are visible in it. Match those numbers to roster players and return suggestions.

    Returns: {"suggestions": [{"player_id": "...", "name": "...", "number": 7, "confidence": "high"}], "raw": [7, 10]}
    """
    import subprocess
    import json as _json

    clip = await db.clips.find_one({"id": clip_id, "user_id": current_user["id"]}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    video = await db.videos.find_one(
        {"id": clip["video_id"], "is_deleted": False}, {"_id": 0}
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Roster for the match (and any team-affiliated players for this user)
    match_id = clip.get("match_id") or video.get("match_id")
    roster_query = {"user_id": current_user["id"]}
    if match_id:
        roster_query = {
            "user_id": current_user["id"],
            "$or": [{"match_id": match_id}, {"match_id": None}],
        }
    roster = await db.players.find(
        roster_query, {"_id": 0, "id": 1, "name": 1, "number": 1, "position": 1}
    ).to_list(200)
    roster_by_number: dict[int, list[dict]] = {}
    for p in roster:
        if p.get("number") is not None:
            roster_by_number.setdefault(p["number"], []).append(p)

    # Frame timestamp = clip mid-point for best chance of a clear shot
    frame_ts = clip["start_time"] + max(0.0, (clip["end_time"] - clip["start_time"]) / 2)

    raw_path = None
    frame_path = tempfile.mktemp(suffix=".jpg", dir="/var/video_chunks")

    try:
        # Assemble source video (same pattern as clip extraction)
        if video.get("is_chunked"):
            chunk_paths = video.get("chunk_paths", {}) or {}
            chunk_backends = video.get("chunk_backends", {}) or {}
            chunk_size = video.get("chunk_size", 50 * 1024 * 1024)
            total_chunks = video.get("total_chunks", 0)
            raw_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")
            with open(raw_path, "wb") as f:
                for i in range(total_chunks):
                    path = chunk_paths.get(str(i))
                    if not path:
                        f.write(b"\x00" * chunk_size)
                        continue
                    backend = chunk_backends.get(str(i), "storage")
                    if backend == "filesystem" and not os.path.exists(path):
                        f.write(b"\x00" * chunk_size)
                        continue
                    try:
                        chunk_info = {"backend": backend, "path": path}
                        data = await read_chunk_data(video["id"], i, chunk_info)
                        f.write(data)
                        del data
                    except Exception:
                        f.write(b"\x00" * chunk_size)
        else:
            raw_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")
            data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
            with open(raw_path, "wb") as f:
                f.write(data)
            del data

        # Extract a single frame at frame_ts, scaled down so Gemini sees it cheaply
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-ss", str(frame_ts),
            "-i", raw_path,
            "-frames:v", "1",
            "-vf", "scale=854:-1",  # ~480p width
            "-q:v", "3",
            frame_path,
        ]
        result = await run_in_threadpool(
            subprocess.run, ffmpeg_cmd, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0 or not os.path.exists(frame_path):
            raise HTTPException(status_code=500, detail="Failed to extract frame for AI analysis")

        # Send frame to Gemini Vision
        if not EMERGENT_KEY:
            raise HTTPException(status_code=500, detail="LLM key not configured")

        prompt = (
            "You are analyzing a single frame from a soccer match. "
            "Identify all clearly visible jersey numbers worn by players actively involved in the play "
            "(not background/unfocused players). "
            "Reply with a JSON object only, like: {\"jersey_numbers\": [7, 10, 23]}. "
            "If no number is clearly readable, return {\"jersey_numbers\": []}. "
            "Do not include any other text."
        )
        chat = LlmChat(
            api_key=EMERGENT_KEY,
            session_id=f"ai-tag-{clip_id}",
            system_message="You are a sports vision assistant. Always reply with valid JSON.",
        ).with_model("gemini", "gemini-2.5-flash")

        image_attachment = FileContentWithMimeType(file_path=frame_path, mime_type="image/jpeg")
        response = await chat.send_message(UserMessage(text=prompt, file_contents=[image_attachment]))

        # Parse Gemini's JSON
        raw_text = response if isinstance(response, str) else str(response)
        # Strip ```json fences if present
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").lstrip("json").strip()
        try:
            parsed = _json.loads(cleaned)
            jersey_numbers = parsed.get("jersey_numbers", []) or []
        except Exception:
            jersey_numbers = []

        # Map numbers -> roster players
        suggestions = []
        for n in jersey_numbers:
            try:
                n_int = int(n)
            except (TypeError, ValueError):
                continue
            for p in roster_by_number.get(n_int, []):
                suggestions.append({
                    "player_id": p["id"],
                    "name": p["name"],
                    "number": n_int,
                    "position": p.get("position", ""),
                    "confidence": "medium",  # Gemini doesn't quantify; UI lets coach confirm
                })

        return {
            "suggestions": suggestions,
            "raw_numbers": [int(n) for n in jersey_numbers if str(n).isdigit()],
            "frame_time": frame_ts,
        }

    finally:
        for p in (raw_path, frame_path):
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass


@api_router.get("/clips/{clip_id}/extract")
async def extract_clip_video(clip_id: str, current_user: dict = Depends(get_current_user)):
    """Extract actual video segment for a clip using ffmpeg and return as streaming MP4"""
    import subprocess
    
    clip = await db.clips.find_one({"id": clip_id, "user_id": current_user["id"]}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    video = await db.videos.find_one({"id": clip["video_id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    raw_path = None
    out_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")
    
    try:
        # Assemble source video
        if video.get("is_chunked"):
            raw_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")
            chunk_paths = video.get("chunk_paths", {})
            chunk_backends = video.get("chunk_backends", {})
            total_chunks = video.get("total_chunks", len(chunk_paths))
            chunk_size = video.get("chunk_size", CHUNK_SIZE)
            
            with open(raw_path, 'wb') as f:
                for i in range(total_chunks):
                    path = chunk_paths.get(str(i))
                    if not path:
                        f.write(b'\x00' * chunk_size)
                        continue
                    backend = chunk_backends.get(str(i), "storage")
                    if backend == "filesystem" and not os.path.exists(path):
                        f.write(b'\x00' * chunk_size)
                        continue
                    try:
                        chunk_info = {"backend": backend, "path": path}
                        data = await read_chunk_data(video["id"], i, chunk_info)
                        f.write(data)
                        del data
                    except Exception:
                        f.write(b'\x00' * chunk_size)
        else:
            raw_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")
            data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
            with open(raw_path, 'wb') as f:
                f.write(data)
            del data
        
        # Extract clip with ffmpeg
        duration = clip["end_time"] - clip["start_time"]
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-ss", str(clip["start_time"]),
            "-i", raw_path,
            "-t", str(duration),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            out_path
        ]
        result = await run_in_threadpool(subprocess.run, ffmpeg_cmd, capture_output=True, text=True, timeout=300)
        
        if raw_path and os.path.exists(raw_path):
            os.unlink(raw_path)
        
        if result.returncode != 0 or not os.path.exists(out_path):
            raise HTTPException(status_code=500, detail="Failed to extract clip")
        
        safe_title = "".join(c for c in clip["title"] if c.isalnum() or c in " -_").strip()[:50] or "clip"
        
        async def stream_and_cleanup():
            try:
                with open(out_path, 'rb') as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        yield chunk
            finally:
                if os.path.exists(out_path):
                    os.unlink(out_path)
        
        return StreamingResponse(
            stream_and_cleanup(),
            media_type="video/mp4",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.mp4"'}
        )
    except HTTPException:
        raise
    except Exception as e:
        for p in [raw_path, out_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
        raise HTTPException(status_code=500, detail=f"Clip extraction failed: {str(e)[:200]}")

# ===== Batch Clip Download (ZIP) =====

class ClipZipRequest(BaseModel):
    clip_ids: List[str]

@api_router.post("/clips/download-zip")
async def download_clips_zip(input: ClipZipRequest, current_user: dict = Depends(get_current_user)):
    """Extract multiple clips and return as a ZIP file"""
    import subprocess
    import zipfile
    
    if not input.clip_ids:
        raise HTTPException(status_code=400, detail="No clip IDs provided")
    if len(input.clip_ids) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 clips per download")
    
    clips = await db.clips.find(
        {"id": {"$in": input.clip_ids}, "user_id": current_user["id"]}, {"_id": 0}
    ).to_list(20)
    
    if not clips:
        raise HTTPException(status_code=404, detail="No clips found")
    
    # Group by video to avoid reassembling the same video multiple times
    video_clips = {}
    for clip in clips:
        vid = clip["video_id"]
        if vid not in video_clips:
            video_clips[vid] = []
        video_clips[vid].append(clip)
    
    zip_path = tempfile.mktemp(suffix=".zip", dir="/var/video_chunks")
    extracted_files = []
    
    try:
        for video_id, clip_list in video_clips.items():
            video = await db.videos.find_one({"id": video_id, "is_deleted": False}, {"_id": 0})
            if not video:
                continue
            
            # Assemble source video once per video
            raw_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")
            if video.get("is_chunked"):
                chunk_paths = video.get("chunk_paths", {})
                chunk_backends = video.get("chunk_backends", {})
                total_chunks = video.get("total_chunks", len(chunk_paths))
                chunk_size = video.get("chunk_size", CHUNK_SIZE)
                with open(raw_path, 'wb') as f:
                    for i in range(total_chunks):
                        path = chunk_paths.get(str(i))
                        if not path:
                            f.write(b'\x00' * chunk_size)
                            continue
                        backend = chunk_backends.get(str(i), "storage")
                        if backend == "filesystem" and not os.path.exists(path):
                            f.write(b'\x00' * chunk_size)
                            continue
                        try:
                            chunk_info = {"backend": backend, "path": path}
                            data = await read_chunk_data(video_id, i, chunk_info)
                            f.write(data)
                            del data
                        except Exception:
                            f.write(b'\x00' * chunk_size)
            else:
                data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
                with open(raw_path, 'wb') as f:
                    f.write(data)
                del data
            
            # Extract each clip from this video
            for clip in clip_list:
                out_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")
                duration = clip["end_time"] - clip["start_time"]
                safe_title = "".join(c for c in clip["title"] if c.isalnum() or c in " -_").strip()[:40] or "clip"
                
                ffmpeg_cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(clip["start_time"]),
                    "-i", raw_path,
                    "-t", str(duration),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart",
                    out_path
                ]
                result = await run_in_threadpool(subprocess.run, ffmpeg_cmd, capture_output=True, text=True, timeout=300)
                
                if result.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                    extracted_files.append((out_path, f"{safe_title}.mp4"))
                else:
                    if os.path.exists(out_path):
                        os.unlink(out_path)
            
            # Cleanup raw video
            if os.path.exists(raw_path):
                os.unlink(raw_path)
        
        if not extracted_files:
            raise HTTPException(status_code=500, detail="Failed to extract any clips")
        
        # Create ZIP
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_STORED) as zf:
            for file_path, filename in extracted_files:
                zf.write(file_path, filename)
        
        # Cleanup extracted files
        for file_path, _ in extracted_files:
            if os.path.exists(file_path):
                os.unlink(file_path)
        
        zip_size = os.path.getsize(zip_path)
        logger.info(f"Created clip ZIP: {zip_size/(1024*1024):.1f}MB with {len(extracted_files)} clips")
        
        async def stream_zip():
            try:
                with open(zip_path, 'rb') as f:
                    while True:
                        chunk = f.read(1024 * 1024)
                        if not chunk:
                            break
                        yield chunk
            finally:
                if os.path.exists(zip_path):
                    os.unlink(zip_path)
        
        return StreamingResponse(
            stream_zip(),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="highlights.zip"'}
        )
    except HTTPException:
        raise
    except Exception as e:
        for fp, _ in extracted_files:
            if os.path.exists(fp):
                try:
                    os.unlink(fp)
                except Exception:
                    pass
        if os.path.exists(zip_path):
            try:
                os.unlink(zip_path)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"ZIP creation failed: {str(e)[:200]}")

# ===== Trimmed Analysis =====

class TrimmedAnalysisRequest(BaseModel):
    video_id: str
    analysis_type: str
    trim_start: Optional[float] = None
    trim_end: Optional[float] = None

@api_router.post("/analysis/generate-trimmed")
async def generate_trimmed_analysis(input: TrimmedAnalysisRequest, current_user: dict = Depends(get_current_user)):
    """Generate analysis on a trimmed section of video"""
    video = await db.videos.find_one({"id": input.video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})

    roster = await db.players.find({"match_id": video["match_id"]}, {"_id": 0}).to_list(100)
    roster_context = ""
    if roster:
        roster_lines = [f"#{p.get('number', '?')} {p['name']} ({p.get('position', '')}) - {p.get('team', '')}" for p in roster]
        roster_context = "\n\nKnown Players:\n" + "\n".join(roster_lines)

    tmp_path = None
    try:
        tmp_path = await prepare_video_sample(video, trim_start=input.trim_start, trim_end=input.trim_end)

        chat = LlmChat(
            api_key=EMERGENT_KEY,
            session_id=f"trim-{input.video_id}-{input.analysis_type}",
            system_message="You are an expert soccer analyst. Analyze the provided video segment and provide detailed insights."
        ).with_model("gemini", "gemini-3.1-pro-preview")

        video_file = FileContentWithMimeType(file_path=tmp_path, mime_type="video/mp4")
        trim_label = ""
        if input.trim_start is not None or input.trim_end is not None:
            s = int(input.trim_start or 0)
            e = int(input.trim_end or 0)
            trim_label = f" (analyzing from {s//60}:{s%60:02d} to {e//60}:{e%60:02d})"

        prompts = {
            "tactical": f"Analyze this soccer match segment{trim_label} between {match['team_home']} and {match['team_away']}. Provide tactical analysis.{roster_context}",
            "player_performance": f"Analyze player performances in this segment{trim_label} between {match['team_home']} and {match['team_away']}.{roster_context}",
            "highlights": f"Identify key moments in this segment{trim_label} between {match['team_home']} and {match['team_away']}.{roster_context}",
        }
        prompt = prompts.get(input.analysis_type, prompts["tactical"])
        response = await chat.send_message(UserMessage(text=prompt, file_contents=[video_file]))

        await db.analyses.delete_many({"video_id": input.video_id, "user_id": current_user["id"], "analysis_type": input.analysis_type})

        analysis_doc = {
            "id": str(uuid.uuid4()),
            "video_id": input.video_id,
            "match_id": video["match_id"],
            "user_id": current_user["id"],
            "analysis_type": input.analysis_type,
            "content": response,
            "status": "completed",
            "trim_start": input.trim_start,
            "trim_end": input.trim_end,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.analyses.insert_one(analysis_doc)
        return {"analysis_id": analysis_doc["id"], "content": response, "status": "completed"}
    except Exception as e:
        logger.error(f"Trimmed analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)[:200]}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


# Mount Teams router (new module)
_teams_api = APIRouter(prefix="/api")
_teams_api.include_router(teams_router)
app.include_router(_teams_api)

# Mount OG share-link prerender router (folders + clips)
_og_api = APIRouter(prefix="/api")
_og_api.include_router(og_router)
app.include_router(_og_api)

# Mount Players router (multi-team rosters, profile pics, promote, etc.)
_players_api = APIRouter(prefix="/api")
_players_api.include_router(players_router)
app.include_router(_players_api)

# Mount Player Profile + Clip-Collection (batch share) router
_pp_api = APIRouter(prefix="/api")
_pp_api.include_router(player_profile_router)
app.include_router(_pp_api)

# Mount Folders, Matches, Annotations, Analysis, Insights (CRUD-style routers)
for r in (folders_router, matches_router, annotations_router, analysis_router, insights_router, season_trends_router, player_trends_router, coach_network_router, videos_router, annotation_templates_router, coach_pulse_router, push_notifications_router, voice_annotations_router, spoken_summary_router, admin_router, scouting_packets_router, password_reset_router, scout_listings_router, messaging_router):
    _api = APIRouter(prefix="/api")
    _api.include_router(r)
    app.include_router(_api)

# ===== Player Profile Pics =====
# (Moved to routes/players.py — this section intentionally left empty)

# ===== Clip Sharing =====

@api_router.post("/clips/{clip_id}/share")
async def toggle_clip_share(clip_id: str, current_user: dict = Depends(get_current_user)):
    clip = await db.clips.find_one({"id": clip_id, "user_id": current_user["id"]}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if clip.get("share_token"):
        await db.clips.update_one({"id": clip_id}, {"$set": {"share_token": None}})
        return {"status": "unshared", "share_token": None}
    token = str(uuid.uuid4())[:12]
    await db.clips.update_one({"id": clip_id}, {"$set": {"share_token": token}})
    return {"status": "shared", "share_token": token}

@api_router.get("/shared/clip/{share_token}")
async def get_shared_clip_detail(share_token: str):
    clip = await db.clips.find_one({"share_token": share_token}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Shared clip not found")
    match = await db.matches.find_one({"id": clip.get("match_id")}, {"_id": 0, "team_home": 1, "team_away": 1, "date": 1, "competition": 1})
    owner = await db.users.find_one({"id": clip["user_id"]}, {"_id": 0, "name": 1})
    players = []
    if clip.get("player_ids"):
        players = await db.players.find({"id": {"$in": clip["player_ids"]}}, {"_id": 0, "id": 1, "name": 1, "number": 1, "profile_pic_url": 1}).to_list(20)

    # Fire push notification to the clip owner (throttled: max 1 per clip per 6h)
    try:
        from services.push_notifications import send_to_user as _send_push
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        last_notified = clip.get("last_view_notify_at")
        now = _dt.now(_tz.utc)
        throttle_ok = not last_notified or (
            now - _dt.fromisoformat(str(last_notified).replace("Z", "+00:00"))
        ) > _td(hours=6)
        if throttle_ok:
            clip_title = (clip.get("title") or "Shared clip")[:60]
            await _send_push(
                user_id=clip["user_id"],
                title="Someone watched your clip",
                body=f'"{clip_title}" was just opened.',
                url=f"/clip/{share_token}",
            )
            await db.clips.update_one(
                {"share_token": share_token},
                {"$set": {"last_view_notify_at": now.isoformat()}},
            )
    except Exception as _e:
        logger.info("push notify (clip view) skipped: %s", _e)

    return {"clip": clip, "match": match, "owner": owner.get("name") if owner else "Coach", "players": players}

# ===== Auto-clip from AI Markers =====

async def auto_create_clips_from_markers(video_id: str, user_id: str, match_id: str):
    """Automatically create clips from AI timeline markers with event-specific padding"""
    markers = await db.markers.find({"video_id": video_id, "user_id": user_id, "auto_generated": True}, {"_id": 0}).to_list(100)
    if not markers:
        return
    await db.clips.delete_many({"video_id": video_id, "user_id": user_id, "auto_generated": True})
    created = 0
    for m in markers:
        if m.get("type") in ("card", "foul"):
            pad_before, pad_after = 20, 5
        else:
            pad_before, pad_after = 8, 8
        start = max(0, m["time"] - pad_before)
        end = m["time"] + pad_after
        clip_type = "goal" if m.get("type") == "goal" else "highlight"
        clip = {
            "id": str(uuid.uuid4()), "user_id": user_id, "video_id": video_id, "match_id": match_id,
            "title": f"[AI] {m.get('label', m.get('type', 'Event'))}",
            "start_time": start, "end_time": end, "clip_type": clip_type,
            "description": f"Auto-generated: {m.get('type')} at {int(m['time']//60)}:{int(m['time']%60):02d}",
            "player_ids": [], "auto_generated": True, "share_token": None,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.clips.insert_one(clip)
        created += 1
    logger.info(f"Auto-created {created} clips from AI markers for video {video_id}")

# ===== Register all api_router routes =====
app.include_router(api_router)

# ===== Auto-Resume on Startup =====

async def resume_interrupted_processing():
    """On server restart, find any videos stuck in 'processing' or 'queued' state and resume them"""
    await asyncio.sleep(5)  # Wait for server to fully initialize
    try:
        stuck_videos = await db.videos.find(
            {"processing_status": {"$in": ["processing", "queued"]}},
            {"_id": 0, "id": 1, "user_id": 1}
        ).to_list(100)

        if not stuck_videos:
            logger.info("No interrupted processing jobs to resume")
            return

        logger.info(f"Found {len(stuck_videos)} interrupted processing jobs — resuming")

        for video in stuck_videos:
            video_id = video["id"]
            user_id = video["user_id"]

            # Check which types are already completed
            completed = set()
            analyses = await db.analyses.find(
                {"video_id": video_id, "status": "completed"},
                {"_id": 0, "analysis_type": 1}
            ).to_list(10)
            for a in analyses:
                completed.add(a["analysis_type"])

            # Delete failed ones so they can be retried
            await db.analyses.delete_many({"video_id": video_id, "status": "failed"})

            remaining = [t for t in ["tactical", "player_performance", "highlights", "timeline_markers"] if t not in completed]

            if remaining:
                logger.info(f"Resuming processing for video {video_id}: {remaining} (already done: {list(completed)})")
                asyncio.create_task(run_auto_processing(video_id, user_id, only_types=remaining))
            else:
                # All types completed, just mark as done
                await db.videos.update_one(
                    {"id": video_id},
                    {"$set": {
                        "processing_status": "completed",
                        "processing_progress": 100,
                        "processing_current": None,
                        "processing_completed_at": datetime.now(timezone.utc).isoformat()
                    }}
                )
                logger.info(f"Video {video_id} already fully processed, marked as completed")

    except Exception as e:
        logger.error(f"Failed to resume interrupted processing: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    # Ensure ffmpeg is installed (persists across container restarts)
    import shutil
    if not shutil.which("ffmpeg"):
        logger.info("ffmpeg not found — installing...")
        result = await run_in_threadpool(
            subprocess.run,
            ["bash", "-c", "apt-get update -qq && apt-get install -y -qq ffmpeg"],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            logger.info(f"ffmpeg installed: {shutil.which('ffmpeg')}")
        else:
            logger.error(f"ffmpeg install failed: {result.stderr[-200:]}")
    else:
        logger.info(f"ffmpeg available: {shutil.which('ffmpeg')}")
    
    try:
        init_storage()
        logger.info("Storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
    # Ensure chunk storage directory exists
    os.makedirs(CHUNK_STORAGE_DIR, exist_ok=True)
    logger.info(f"Chunk storage dir: {CHUNK_STORAGE_DIR}")
    logger.info(f"Server boot ID: {SERVER_BOOT_ID}")
    
    # Auto-resume interrupted processing from previous server instance
    asyncio.create_task(resume_interrupted_processing())
    # Periodic sweeper for permanently purging soft-deleted videos
    asyncio.create_task(deleted_video_sweeper())
    # APScheduler — weekly Coach Pulse blast every Monday 08:00 UTC +
    # email-queue retry every 30 min for quota-deferred sends.
    start_coach_pulse_scheduler()


# ===== APScheduler: Weekly Coach Pulse Blast =====
_scheduler = None


def start_coach_pulse_scheduler():
    """Start an AsyncIOScheduler that fires:
      1) Coach Pulse weekly blast every Monday 08:00 UTC
      2) Email-queue retry sweep every 30 minutes (for quota-deferred sends)
    Idempotent: running multiple times is a no-op."""
    global _scheduler
    if _scheduler is not None:
        return
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
        from routes.coach_pulse import run_weekly_blast
        from services.email_queue import process_queue

        async def _weekly_job():
            try:
                result = await run_weekly_blast(triggered_by="apscheduler")
                logger.info("[apscheduler] coach_pulse weekly blast result: %s", result)
            except Exception as e:
                logger.error("[apscheduler] coach_pulse weekly blast crashed: %s", e)

        async def _queue_retry_job():
            try:
                result = await process_queue(limit=200)
                if result["processed"] > 0:
                    logger.info("[apscheduler] email queue retry: %s", result)
            except Exception as e:
                logger.error("[apscheduler] email queue retry crashed: %s", e)

        async def _scout_digest_job():
            try:
                from services.scout_digest import send_weekly_digest
                result = await send_weekly_digest(triggered_by="apscheduler")
                logger.info("[apscheduler] scout weekly digest: %s", result)
            except Exception as e:
                logger.error("[apscheduler] scout weekly digest crashed: %s", e)

        _scheduler = AsyncIOScheduler(timezone="UTC")
        _scheduler.add_job(
            _weekly_job,
            CronTrigger(day_of_week="mon", hour=8, minute=0, timezone="UTC"),
            id="coach_pulse_weekly",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        _scheduler.add_job(
            _queue_retry_job,
            IntervalTrigger(minutes=30),
            id="email_queue_retry",
            replace_existing=True,
            misfire_grace_time=600,
        )
        _scheduler.add_job(
            _scout_digest_job,
            CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
            id="scout_digest_weekly",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        _scheduler.start()
        logger.info(
            "[apscheduler] scheduler started — coach_pulse_weekly (Mon 08:00 UTC) + email_queue_retry (every 30 min) + scout_digest_weekly (Mon 09:00 UTC)"
        )
    except Exception as e:
        logger.error("[apscheduler] failed to start scheduler: %s", e)


async def deleted_video_sweeper():
    """Hard-delete videos that have been soft-deleted for more than 24h.

    Runs every hour. Removes the video record entirely (the cascade-delete of
    clips/analyses/markers and storage cleanup happened at delete time).
    """
    while True:
        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            result = await db.videos.delete_many(
                {"is_deleted": True, "deleted_at": {"$lt": cutoff}}
            )
            if result.deleted_count > 0:
                logger.info(
                    f"[sweeper] Permanently purged {result.deleted_count} soft-deleted videos"
                )
        except Exception as e:
            logger.error(f"[sweeper] error: {e}")
        await asyncio.sleep(3600)

@app.on_event("shutdown")
async def shutdown_db_client():
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass
        _scheduler = None
    client.close()
