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
SERVER_BOOT_ID = str(uuid.uuid4())  # Unique per server process — changes on restart
SERVER_BOOT_TIME = datetime.now(timezone.utc).isoformat()

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== Import modular routes =====
from routes.teams import router as teams_router
from routes.og import router as og_router
from routes.players import router as players_router
from routes.player_profile import router as player_profile_router

# ===== Storage: Connection Pooling + Retry for SSL resilience =====

def create_storage_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=0,  # No urllib3 retries - all retries at application level
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10,
    )
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session

storage_session = create_storage_session()

def init_storage():
    global storage_key
    if storage_key:
        # Verify the key still works by checking if session changed
        return storage_key
    try:
        resp = storage_session.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
        resp.raise_for_status()
        storage_key = resp.json()["storage_key"]
        logger.info("Storage initialized successfully")
        return storage_key
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
        raise

def reset_storage():
    """Reset storage key so it re-initializes on next call"""
    global storage_key
    storage_key = None

def put_object_sync(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    resp = storage_session.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=(3, 15)  # 3s connect, 15s read - fail fast for fallback
    )
    resp.raise_for_status()
    return resp.json()

async def put_object_with_retry(path: str, data: bytes, content_type: str, max_retries: int = 2) -> dict:
    """Upload to storage with fast retry and session recreation on SSL errors"""
    global storage_session
    last_error = None
    for attempt in range(max_retries):
        try:
            result = await run_in_threadpool(put_object_sync, path, data, content_type)
            return result
        except Exception as e:
            last_error = e
            error_str = str(e)
            is_retryable = "SSL" in error_str or "Connection" in error_str or "EOF" in error_str or "500" in error_str
            if attempt < max_retries - 1 and is_retryable:
                wait_time = 2
                logger.warning(f"Storage upload failed (attempt {attempt+1}/{max_retries}), retrying in {wait_time}s: {error_str[:100]}")
                storage_session = create_storage_session()
                reset_storage()
                init_storage()
                await asyncio.sleep(wait_time)
            else:
                raise
    raise last_error

def get_object_sync(path: str) -> tuple:
    key = init_storage()
    resp = storage_session.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key}, timeout=120
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")

def delete_object_sync(path: str):
    key = init_storage()
    try:
        storage_session.delete(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=30)
    except Exception:
        pass

# Legacy wrappers (used by non-chunked upload and analysis)
def put_object(path, data, content_type):
    return put_object_sync(path, data, content_type)

def get_object(path):
    return get_object_sync(path)

# ===== Circuit Breaker for Object Storage =====

CHUNK_STORAGE_DIR = "/var/video_chunks"
os.makedirs(CHUNK_STORAGE_DIR, exist_ok=True)

class StorageCircuitBreaker:
    def __init__(self, failure_threshold=1, reset_timeout=120):
        self.consecutive_failures = 0
        self.failure_threshold = failure_threshold
        self.last_failure_time = 0
        self.reset_timeout = reset_timeout

    @property
    def is_open(self):
        if self.consecutive_failures >= self.failure_threshold:
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.consecutive_failures = 0
                return False
            return True
        return False

    def record_failure(self):
        self.consecutive_failures += 1
        self.last_failure_time = time.time()

    def record_success(self):
        self.consecutive_failures = 0

storage_breaker = StorageCircuitBreaker()

async def store_chunk(video_id: str, user_id: str, chunk_index: int, data: bytes) -> dict:
    """Store chunk - tries Object Storage first, falls back to local filesystem (/var overlay, 84GB)"""
    chunk_path = f"{APP_NAME}/videos/{user_id}/{video_id}_chunk_{chunk_index:06d}.bin"

    if not storage_breaker.is_open:
        try:
            result = await put_object_with_retry(chunk_path, data, "application/octet-stream", max_retries=2)
            storage_breaker.record_success()
            return {"backend": "storage", "path": chunk_path, "size": len(data)}
        except Exception as e:
            storage_breaker.record_failure()
            logger.warning(f"Object Storage failed (breaker: {storage_breaker.consecutive_failures}), falling back to filesystem: {str(e)[:80]}")
    else:
        logger.info("Circuit breaker OPEN - using filesystem directly")

    # Fallback: store on local filesystem (/var is on 84GB overlay, NOT the 9.8GB /app partition)
    video_dir = os.path.join(CHUNK_STORAGE_DIR, video_id)
    os.makedirs(video_dir, exist_ok=True)
    local_path = os.path.join(video_dir, f"chunk_{chunk_index:06d}.bin")
    await run_in_threadpool(_write_file, local_path, data)
    logger.info(f"Chunk {chunk_index} stored on filesystem ({len(data)} bytes)")
    return {"backend": "filesystem", "path": local_path, "size": len(data)}

def _write_file(path: str, data: bytes):
    with open(path, 'wb') as f:
        f.write(data)

def _read_file(path: str) -> bytes:
    with open(path, 'rb') as f:
        return f.read()

async def read_chunk_data(video_id: str, chunk_index: int, chunk_info: dict) -> bytes:
    """Read chunk from the appropriate backend"""
    backend = chunk_info.get("backend", "storage")
    path = chunk_info.get("path", "")

    if backend == "filesystem":
        return await run_in_threadpool(_read_file, path)
    elif backend == "mongodb":
        doc = await db.video_chunks.find_one(
            {"video_id": video_id, "chunk_index": chunk_index},
            {"data": 1}
        )
        if doc and "data" in doc:
            return bytes(doc["data"])
        raise Exception(f"Chunk {chunk_index} not found in MongoDB")
    else:
        data, _ = await run_in_threadpool(get_object_sync, path)
        return data

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

@api_router.post("/matches", response_model=Match)
async def create_match(input: MatchCreate, current_user: dict = Depends(get_current_user)):
    match_obj = Match(user_id=current_user["id"], **input.model_dump())
    await db.matches.insert_one(match_obj.model_dump())
    return match_obj

@api_router.get("/matches", response_model=List[Match])
async def get_matches(current_user: dict = Depends(get_current_user)):
    matches = await db.matches.find({"user_id": current_user["id"]}, {"_id": 0}).to_list(1000)
    # Enrich with processing status
    for match in matches:
        if match.get("video_id"):
            video = await db.videos.find_one(
                {"id": match["video_id"]},
                {"_id": 0, "processing_status": 1, "processing_progress": 1}
            )
            if video:
                match["processing_status"] = video.get("processing_status", "none")
                match["processing_progress"] = video.get("processing_progress", 0)
    return matches

@api_router.get("/matches/{match_id}", response_model=Match)
async def get_match(match_id: str, current_user: dict = Depends(get_current_user)):
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match

@api_router.patch("/matches/{match_id}")
async def update_match(match_id: str, updates: dict, current_user: dict = Depends(get_current_user)):
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    allowed = {"folder_id", "team_home", "team_away", "date", "competition"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if filtered:
        await db.matches.update_one({"id": match_id}, {"$set": filtered})
    return {"status": "updated"}

# ===== Folders =====

@api_router.post("/folders")
async def create_folder(input: FolderCreate, current_user: dict = Depends(get_current_user)):
    if input.parent_id:
        parent = await db.folders.find_one({"id": input.parent_id, "user_id": current_user["id"]}, {"_id": 0})
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found")
    folder = Folder(user_id=current_user["id"], **input.model_dump())
    await db.folders.insert_one(folder.model_dump())
    return folder.model_dump()

@api_router.get("/folders")
async def get_folders(current_user: dict = Depends(get_current_user)):
    folders = await db.folders.find({"user_id": current_user["id"]}, {"_id": 0}).to_list(500)
    return folders

@api_router.patch("/folders/{folder_id}")
async def update_folder(folder_id: str, input: FolderUpdate, current_user: dict = Depends(get_current_user)):
    folder = await db.folders.find_one({"id": folder_id, "user_id": current_user["id"]}, {"_id": 0})
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    updates = {k: v for k, v in input.model_dump().items() if v is not None}
    if updates:
        await db.folders.update_one({"id": folder_id}, {"$set": updates})
    return {"status": "updated"}

@api_router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, current_user: dict = Depends(get_current_user)):
    folder = await db.folders.find_one({"id": folder_id, "user_id": current_user["id"]}, {"_id": 0})
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    # Move child folders to parent
    await db.folders.update_many(
        {"parent_id": folder_id, "user_id": current_user["id"]},
        {"$set": {"parent_id": folder.get("parent_id")}}
    )
    # Move matches to parent folder
    await db.matches.update_many(
        {"folder_id": folder_id, "user_id": current_user["id"]},
        {"$set": {"folder_id": folder.get("parent_id")}}
    )
    await db.folders.delete_one({"id": folder_id})
    return {"status": "deleted"}

# ===== Folder Sharing =====

@api_router.post("/folders/{folder_id}/share")
async def toggle_folder_share(folder_id: str, current_user: dict = Depends(get_current_user)):
    """Generate or revoke a share token for a public folder"""
    folder = await db.folders.find_one({"id": folder_id, "user_id": current_user["id"]}, {"_id": 0})
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    if folder.get("is_private"):
        raise HTTPException(status_code=400, detail="Cannot share a private folder. Set it to public first.")
    
    if folder.get("share_token"):
        # Revoke sharing
        await db.folders.update_one({"id": folder_id}, {"$set": {"share_token": None}})
        return {"status": "unshared", "share_token": None}
    else:
        # Generate share token
        token = str(uuid.uuid4())[:12]
        await db.folders.update_one({"id": folder_id}, {"$set": {"share_token": token}})
        return {"status": "shared", "share_token": token}

@api_router.get("/shared/{share_token}")
async def get_shared_folder(share_token: str):
    """Public endpoint: view a shared folder and its matches (no auth required)"""
    folder = await db.folders.find_one({"share_token": share_token, "is_private": False}, {"_id": 0})
    if not folder:
        raise HTTPException(status_code=404, detail="Shared folder not found or link expired")
    
    matches = await db.matches.find(
        {"folder_id": folder["id"], "user_id": folder["user_id"]}, {"_id": 0}
    ).to_list(500)
    
    # Enrich with processing status
    for match in matches:
        if match.get("video_id"):
            video = await db.videos.find_one(
                {"id": match["video_id"]},
                {"_id": 0, "processing_status": 1, "processing_progress": 1}
            )
            if video:
                match["processing_status"] = video.get("processing_status", "none")
    
    owner = await db.users.find_one({"id": folder["user_id"]}, {"_id": 0, "name": 1, "role": 1})
    
    return {
        "folder": {"id": folder["id"], "name": folder["name"]},
        "owner": {"name": owner.get("name", "Coach") if owner else "Coach", "role": owner.get("role", "") if owner else ""},
        "matches": matches
    }

@api_router.get("/shared/{share_token}/match/{match_id}")
async def get_shared_match_detail(share_token: str, match_id: str):
    """Public endpoint: view a specific match's analyses, clips, annotations, and roster"""
    folder = await db.folders.find_one({"share_token": share_token, "is_private": False}, {"_id": 0})
    if not folder:
        raise HTTPException(status_code=404, detail="Shared folder not found or link expired")
    
    match = await db.matches.find_one(
        {"id": match_id, "folder_id": folder["id"], "user_id": folder["user_id"]}, {"_id": 0}
    )
    if not match:
        raise HTTPException(status_code=404, detail="Match not found in this shared folder")
    
    result = {"match": match, "folder_name": folder["name"]}
    
    if match.get("video_id"):
        video = await db.videos.find_one({"id": match["video_id"]}, {"_id": 0, "id": 1, "processing_status": 1, "original_filename": 1, "size": 1})
        result["video"] = video
        
        analyses = await db.analyses.find(
            {"video_id": match["video_id"], "user_id": folder["user_id"], "status": "completed"},
            {"_id": 0}
        ).to_list(10)
        result["analyses"] = analyses
        
        clips = await db.clips.find(
            {"video_id": match["video_id"], "user_id": folder["user_id"]},
            {"_id": 0}
        ).to_list(100)
        result["clips"] = clips
        
        annotations = await db.annotations.find(
            {"video_id": match["video_id"], "user_id": folder["user_id"]},
            {"_id": 0}
        ).to_list(500)
        result["annotations"] = annotations
    
    players = await db.players.find(
        {"match_id": match_id, "user_id": folder["user_id"]},
        {"_id": 0}
    ).to_list(100)
    result["players"] = players
    
    return result

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

@api_router.get("/videos/{video_id}/access-token")
async def get_video_access_token(video_id: str, current_user: dict = Depends(get_current_user)):
    """Generate a short-lived access token for video streaming (prevents exposing main JWT in URLs)"""
    video = await db.videos.find_one({"id": video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0, "id": 1})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    # Short-lived token (5 min) specifically for this video
    import time
    video_token = jwt.encode(
        {"user_id": current_user["id"], "video_id": video_id, "exp": int(time.time()) + 300, "type": "video_access"},
        JWT_SECRET, algorithm="HS256"
    )
    return {"token": video_token}

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

@api_router.get("/videos/{video_id}/metadata")
async def get_video_metadata(video_id: str, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one({"id": video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    # Don't send chunk_paths in metadata (too large for large uploads)
    result = {k: v for k, v in video.items() if k not in ("chunk_paths", "chunk_sizes", "chunk_backends")}
    
    # Add data integrity check for chunked videos
    if video.get("is_chunked"):
        chunk_paths = video.get("chunk_paths", {})
        chunk_backends = video.get("chunk_backends", {})
        total = video.get("total_chunks", len(chunk_paths))
        available = 0
        for i in range(total):
            path = chunk_paths.get(str(i))
            if not path:
                continue
            backend = chunk_backends.get(str(i), "storage")
            if backend == "filesystem" and not os.path.exists(path):
                continue
            available += 1
        result["chunks_available"] = available
        result["chunks_total"] = total
        result["data_integrity"] = "full" if available == total else ("partial" if available > 0 else "unavailable")
    
    return result

# ===== Auto-Processing (Hudl/Veo-like) =====

def build_roster_context(roster: list) -> str:
    """Build roster context string for AI prompts"""
    if not roster:
        return ""
    roster_lines = []
    for p in roster:
        line = f"#{p.get('number', '?')} {p['name']}"
        if p.get('position'):
            line += f" ({p['position']})"
        if p.get('team'):
            line += f" - {p['team']}"
        roster_lines.append(line)
    return "\n\n**Known Players on the Roster:**\n" + "\n".join(roster_lines) + "\n\nReference these players by name and number in your analysis when you can identify them."


def build_analysis_prompts(match: dict, roster_context: str, segment_preamble: str) -> dict:
    """Build the AI prompt dictionary for each analysis type"""
    return {
        "tactical": f"Analyze this soccer match video between {match['team_home']} and {match['team_away']}. Provide detailed tactical analysis covering:\n\n1. **Formations** - What formations are each team using? Any formation changes during the match?\n2. **Pressing Patterns** - How do teams press? High press, mid-block, or low block?\n3. **Build-up Play** - How do teams build from the back? Through the middle or wide?\n4. **Defensive Organization** - Shape, line height, compactness\n5. **Key Tactical Moments** - Pivotal tactical decisions that influenced the game\n6. **Recommendations** - Tactical improvements for both teams{roster_context}",
        "player_performance": f"Analyze individual player performances in this soccer match between {match['team_home']} and {match['team_away']}. For each notable player provide:\n\n1. **Standout Performers** - Who were the best players and why?\n2. **Key Contributions** - Goals, assists, key passes, tackles\n3. **Work Rate & Positioning** - Movement, runs, defensive contribution\n4. **Decision Making** - Quality of decisions in key moments\n5. **Areas for Improvement** - What each key player could do better\n6. **Player Ratings** - Rate key players out of 10 with justification{roster_context}",
        "highlights": f"Identify and describe ALL key moments and highlights from this soccer match between {match['team_home']} and {match['team_away']}. Include:\n\n1. **Goals & Assists** - Describe each goal in detail with timestamps if visible\n2. **Near Misses** - Close chances that didn't result in goals\n3. **Outstanding Saves** - Goalkeeper heroics\n4. **Tactical Shifts** - Moments where the game's momentum changed\n5. **Key Fouls & Cards** - Significant disciplinary moments\n6. **Game-Changing Plays** - Moments that altered the match outcome\n\nFor each moment, indicate the approximate time if visible and rate its significance (1-5 stars).{roster_context}",
        "timeline_markers": f"Watch this soccer match video between {match['team_home']} and {match['team_away']}. The video contains multiple segments from across the full match at high quality.\n\n{segment_preamble}Identify EVERY key event with precise match timestamps (in seconds from the start of the match, NOT from the start of each segment).\n\nReturn ONLY a JSON array of event objects. Each object must have:\n- \"time\": match timestamp in seconds (number, from match start)\n- \"type\": one of \"goal\", \"shot\", \"save\", \"foul\", \"card\", \"substitution\", \"tactical\", \"chance\"\n- \"label\": short description (max 60 chars)\n- \"team\": which team (\"{match['team_home']}\" or \"{match['team_away']}\" or \"neutral\")\n- \"importance\": 1-5 (5 = most important, e.g. goals)\n\nBe thorough — identify goals, shots on target, saves, dangerous attacks, key fouls, tactical changes. Aim for 15-30 events across the full match.\n\nReturn ONLY the JSON array, no other text.{roster_context}"
    }


async def parse_and_store_markers(response: str, video_id: str, match_id: str, user_id: str):
    """Parse timeline markers JSON from AI response and store in DB"""
    import json as json_mod
    clean = response.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[1] if "\n" in clean else clean[3:]
        if clean.endswith("```"):
            clean = clean[:-3]
        clean = clean.strip()
    markers_data = json_mod.loads(clean)
    if not isinstance(markers_data, list):
        return 0
    await db.markers.delete_many({"video_id": video_id, "user_id": user_id, "auto_generated": True})
    for m in markers_data:
        marker_doc = {
            "id": str(uuid.uuid4()),
            "video_id": video_id,
            "match_id": match_id,
            "user_id": user_id,
            "time": float(m.get("time", 0)),
            "type": m.get("type", "chance"),
            "label": str(m.get("label", ""))[:100],
            "team": m.get("team", "neutral"),
            "importance": min(5, max(1, int(m.get("importance", 3)))),
            "auto_generated": True,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.markers.insert_one(marker_doc)
    logger.info(f"Stored {len(markers_data)} AI timeline markers for video {video_id}")
    await auto_create_clips_from_markers(video_id, user_id, match_id)
    return len(markers_data)


async def run_single_analysis(video_id: str, user_id: str, match_id: str, analysis_type: str, video_file_path: str, prompt: str):
    """Run a single analysis type against Gemini and store the result"""
    chat = LlmChat(
        api_key=EMERGENT_KEY,
        session_id=f"auto-{video_id}-{analysis_type}",
        system_message="You are an expert soccer analyst. You will receive the full match video (compressed). Analyze the entire match and provide detailed tactical insights, player assessments, highlight identification, and precise timestamp markers for key events."
    ).with_model("gemini", "gemini-3.1-pro-preview")

    video_file = FileContentWithMimeType(file_path=video_file_path, mime_type="video/mp4")
    response = await chat.send_message(UserMessage(text=prompt, file_contents=[video_file]))

    analysis_doc = {
        "id": str(uuid.uuid4()),
        "video_id": video_id,
        "match_id": match_id,
        "user_id": user_id,
        "analysis_type": analysis_type,
        "content": response,
        "status": "completed",
        "auto_generated": True,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.analyses.insert_one(analysis_doc)
    logger.info(f"Auto-processing {video_id}: {analysis_type} COMPLETED")

    # Parse timeline markers if applicable
    if analysis_type == "timeline_markers" and response:
        try:
            await parse_and_store_markers(response, video_id, match_id, user_id)
        except Exception as parse_err:
            logger.warning(f"Failed to parse timeline markers JSON: {parse_err}")

    return response


async def run_auto_processing(video_id: str, user_id: str, only_types: list = None):
    """Background task: runs analysis types after upload. Saves each independently so partial completion survives restarts."""
    all_types = ["tactical", "player_performance", "highlights", "timeline_markers"]
    analysis_types = only_types if only_types else all_types
    tmp_path = None
    tmp_path_720p = None

    try:
        await db.videos.update_one(
            {"id": video_id},
            {"$set": {"processing_status": "processing", "processing_progress": 0}}
        )

        video = await db.videos.find_one({"id": video_id}, {"_id": 0})
        if not video:
            logger.error(f"Auto-processing: video {video_id} not found")
            return

        match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})
        if not match:
            logger.error(f"Auto-processing: match for video {video_id} not found")
            return

        # Build context
        roster = await db.players.find({"match_id": video["match_id"]}, {"_id": 0}).to_list(100)
        roster_context = build_roster_context(roster)

        # Prepare video samples
        try:
            tmp_path = await prepare_video_sample(video)
        except Exception as e:
            logger.error(f"Auto-processing: failed to prepare video sample: {e}")
            await db.videos.update_one(
                {"id": video_id},
                {"$set": {"processing_status": "failed", "processing_error": f"Failed to prepare video: {str(e)[:200]}"}}
            )
            return

        # For timeline markers, prepare 480p multi-segment sample
        segments_info = None
        if "timeline_markers" in analysis_types:
            try:
                tmp_path_720p, segments_info = await prepare_video_segments_720p(video)
                logger.info("Prepared 720p segments for timeline markers")
            except Exception as e:
                logger.warning(f"720p segments failed, will fall back to standard sample: {e}")

        # Build prompts
        segment_preamble = ""
        if segments_info:
            segment_preamble = "Segment timing (these are the real match times shown in the video):\n" + segments_info + "\n\n"
        prompts = build_analysis_prompts(match, roster_context, segment_preamble)

        # Run each analysis type
        for idx, analysis_type in enumerate(analysis_types):
            progress = int((idx / len(analysis_types)) * 100)
            await db.videos.update_one(
                {"id": video_id},
                {"$set": {"processing_progress": progress, "processing_current": analysis_type}}
            )
            logger.info(f"Auto-processing {video_id}: {analysis_type} ({progress}%)")

            use_path = tmp_path_720p if (analysis_type == "timeline_markers" and tmp_path_720p) else tmp_path

            try:
                await run_single_analysis(video_id, user_id, video["match_id"], analysis_type, use_path, prompts[analysis_type])
            except Exception as e:
                logger.error(f"Auto-processing {video_id}: {analysis_type} FAILED: {e}")
                analysis_doc = {
                    "id": str(uuid.uuid4()),
                    "video_id": video_id,
                    "match_id": video["match_id"],
                    "user_id": user_id,
                    "analysis_type": analysis_type,
                    "content": f"Analysis could not be completed: {str(e)[:200]}",
                    "status": "failed",
                    "auto_generated": True,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                await db.analyses.insert_one(analysis_doc)

        # Final status
        completed_analyses = await db.analyses.find(
            {"video_id": video_id, "user_id": user_id, "status": "completed"},
            {"_id": 0, "analysis_type": 1}
        ).to_list(10)
        final_status = "completed" if len(completed_analyses) > 0 else "failed"
        await db.videos.update_one(
            {"id": video_id},
            {"$set": {"processing_status": final_status, "processing_progress": 100, "processing_current": None, "processing_completed_at": datetime.now(timezone.utc).isoformat()}}
        )
        logger.info(f"Auto-processing {'COMPLETE' if final_status == 'completed' else 'FAILED (all types)'} for video {video_id}")

    except Exception as e:
        logger.error(f"Auto-processing FAILED for video {video_id}: {e}")
        await db.videos.update_one(
            {"id": video_id},
            {"$set": {"processing_status": "failed", "processing_error": str(e)[:200]}}
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        if tmp_path_720p and os.path.exists(tmp_path_720p):
            os.unlink(tmp_path_720p)

async def prepare_video_sample(video: dict, trim_start: float = None, trim_end: float = None) -> str:
    """Compress entire video (or trimmed portion) to 360p for AI analysis.
    For Gemini File API: target <1.5GB, 360p resolution."""
    
    ext = video["original_filename"].split(".")[-1] if "." in video["original_filename"] else "mp4"
    raw_path = tempfile.mktemp(suffix=f".{ext}", dir="/var/video_chunks")
    clip_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")

    try:
        if video.get("is_chunked"):
            chunk_paths = video.get("chunk_paths", {})
            chunk_backends = video.get("chunk_backends", {})
            total_chunks = video.get("total_chunks", len(chunk_paths))
            chunk_size = video.get("chunk_size", CHUNK_SIZE)

            # Write ALL available chunks to assemble the full video
            logger.info(f"Assembling full video from {total_chunks} chunks")
            
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
                    chunk_info = {"backend": backend, "path": path}
                    try:
                        data = await read_chunk_data(video["id"], i, chunk_info)
                        f.write(data)
                        del data
                    except Exception as e:
                        logger.warning(f"  Skipping chunk {i}: {str(e)[:60]}")
                        f.write(b'\x00' * chunk_size)

            raw_size = os.path.getsize(raw_path)
            logger.info(f"Assembled full video: {raw_size/(1024*1024*1024):.2f}GB")
        else:
            data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
            with open(raw_path, 'wb') as f:
                f.write(data)
            del data

        # Build ffmpeg command: compress entire video to low res for AI
        # For videos > 60min, use very aggressive compression to stay under ~50MB for reliable API upload
        video_size_gb = os.path.getsize(raw_path) / (1024*1024*1024)
        if video_size_gb > 2:
            # Very large/long video: 240p, 5fps, aggressive CRF
            scale_filter = "scale=320:180:force_original_aspect_ratio=decrease,pad=320:180:(ow-iw)/2:(oh-ih)/2"
            fps = "5"
            crf = "40"
        else:
            # Normal video: 360p, 12fps
            scale_filter = "scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2"
            fps = "12"
            crf = "35"
        
        ffmpeg_cmd = ["ffmpeg", "-y"]
        
        # Trim support
        if trim_start is not None and trim_start > 0:
            ffmpeg_cmd += ["-ss", str(int(trim_start))]
        ffmpeg_cmd += ["-i", raw_path]
        if trim_end is not None and trim_end > 0:
            duration = trim_end - (trim_start or 0)
            ffmpeg_cmd += ["-t", str(int(duration))]
        
        ffmpeg_cmd += [
            "-vf", scale_filter,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", crf,
            "-r", fps,
            "-c:a", "aac",
            "-b:a", "32k",
            "-ac", "1",
            "-movflags", "+faststart",
            clip_path
        ]

        logger.info(f"Compressing video to {'240p/8fps' if video_size_gb > 2 else '360p/12fps'} (trim={trim_start}-{trim_end}, src={video_size_gb:.1f}GB)")
        result = await run_in_threadpool(
            subprocess.run, ffmpeg_cmd,
            capture_output=True, text=True, timeout=1800  # 30min timeout for long videos
        )

        # Delete raw file to free disk
        if os.path.exists(raw_path):
            os.unlink(raw_path)
            logger.info("Deleted raw video file")

        if result.returncode == 0 and os.path.exists(clip_path) and os.path.getsize(clip_path) > 1000:
            clip_size = os.path.getsize(clip_path)
            logger.info(f"Created {clip_size/(1024*1024):.1f}MB compressed video for AI")
            return clip_path
        else:
            stderr = result.stderr[-500:] if result.stderr else ""
            if "moov atom not found" in stderr:
                raise Exception("Video data incomplete — moov atom missing. Re-upload needed.")
            elif "Invalid data found" in stderr:
                raise Exception("Not a valid video format. Re-upload a valid video file.")
            else:
                logger.error(f"ffmpeg compress failed: rc={result.returncode}, stderr={stderr}")
                raise Exception("Failed to compress video for analysis")

    except Exception:
        for p in [raw_path, clip_path]:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
        raise


async def prepare_video_segments_720p(video: dict) -> tuple:
    """Extract multiple 720p segments from across the match for high-quality timeline analysis.
    Returns (clip_path, segment_info_text) where segment_info_text describes
    the time offsets for each segment so the AI can map to real match timestamps."""
    
    ext = video["original_filename"].split(".")[-1] if "." in video["original_filename"] else "mp4"
    raw_path = tempfile.mktemp(suffix=f".{ext}", dir="/var/video_chunks")
    clip_path = tempfile.mktemp(suffix=".mp4", dir="/var/video_chunks")
    segment_files = []

    try:
        # Assemble full video
        if video.get("is_chunked"):
            chunk_paths = video.get("chunk_paths", {})
            chunk_backends = video.get("chunk_backends", {})
            total_chunks = video.get("total_chunks", len(chunk_paths))
            chunk_size = video.get("chunk_size", CHUNK_SIZE)

            logger.info(f"[720p segments] Assembling full video from {total_chunks} chunks")
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
                    chunk_info = {"backend": backend, "path": path}
                    try:
                        data = await read_chunk_data(video["id"], i, chunk_info)
                        f.write(data)
                        del data
                    except Exception as e:
                        logger.warning(f"  Skipping chunk {i}: {str(e)[:60]}")
                        f.write(b'\x00' * chunk_size)
        else:
            data, _ = await run_in_threadpool(get_object_sync, video["storage_path"])
            with open(raw_path, 'wb') as f:
                f.write(data)
            del data

        # Probe duration
        probe = await run_in_threadpool(
            subprocess.run,
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", raw_path],
            capture_output=True, text=True, timeout=60
        )
        duration = 0
        if probe.returncode == 0 and probe.stdout.strip():
            try:
                duration = float(probe.stdout.strip())
            except ValueError:
                pass
        logger.info(f"[720p segments] Video duration: {duration:.0f}s ({duration/60:.1f}min)")

        if duration <= 0:
            raise Exception("Could not determine video duration")

        # Extract segments at 480p, 12fps for good quality while keeping file size manageable
        segment_duration = 60  # 1 minute each
        num_segments = 12
        if duration < segment_duration * num_segments:
            num_segments = max(1, int(duration / segment_duration))
        
        segment_starts = []
        for i in range(num_segments):
            pct = i / max(1, num_segments - 1)
            start = pct * max(0, duration - segment_duration)
            segment_starts.append(max(0, start))

        logger.info(f"[720p segments] Extracting {num_segments} x {segment_duration}s segments at 480p")

        segment_info_parts = []
        for idx, start in enumerate(segment_starts):
            seg_path = tempfile.mktemp(suffix=f"_seg{idx}.mp4", dir="/var/video_chunks")
            seg_cmd = [
                "ffmpeg", "-y",
                "-ss", str(int(start)),
                "-i", raw_path,
                "-t", str(segment_duration),
                "-vf", "scale=-2:480",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "30",
                "-r", "12",
                "-c:a", "aac",
                "-b:a", "48k",
                "-movflags", "+faststart",
                seg_path
            ]
            seg_result = await run_in_threadpool(
                subprocess.run, seg_cmd,
                capture_output=True, text=True, timeout=300
            )
            if seg_result.returncode == 0 and os.path.exists(seg_path) and os.path.getsize(seg_path) > 1000:
                seg_size = os.path.getsize(seg_path) / (1024 * 1024)
                segment_files.append(seg_path)
                s_min, s_sec = divmod(int(start), 60)
                e_min, e_sec = divmod(int(start + segment_duration), 60)
                segment_info_parts.append(
                    f"Segment {idx+1}: match time {s_min}:{s_sec:02d} to {e_min}:{e_sec:02d}"
                )
                logger.info(f"  Segment {idx+1}/{num_segments}: {start:.0f}s, {seg_size:.1f}MB")
            else:
                logger.warning(f"  Segment {idx+1} failed at {start:.0f}s")
                if os.path.exists(seg_path):
                    os.unlink(seg_path)

        # Delete raw file to free disk
        if os.path.exists(raw_path):
            os.unlink(raw_path)
            logger.info("[720p segments] Deleted raw video file")

        if not segment_files:
            raise Exception("Failed to extract any video segments")

        # Concatenate all segments into one file
        if len(segment_files) == 1:
            os.rename(segment_files[0], clip_path)
            segment_files = []
        else:
            concat_list = tempfile.mktemp(suffix=".txt", dir="/var/video_chunks")
            with open(concat_list, 'w') as f:
                for seg in segment_files:
                    f.write(f"file '{seg}'\n")
            concat_result = await run_in_threadpool(
                subprocess.run,
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", concat_list, "-c", "copy", "-movflags", "+faststart", clip_path],
                capture_output=True, text=True, timeout=300
            )
            # Cleanup
            if os.path.exists(concat_list):
                os.unlink(concat_list)
            for seg in segment_files:
                if os.path.exists(seg):
                    os.unlink(seg)
            segment_files = []
            if concat_result.returncode != 0:
                raise Exception("Failed to concatenate video segments")

        clip_size = os.path.getsize(clip_path) / (1024 * 1024)
        segment_info_text = "\n".join(segment_info_parts)
        logger.info(f"[720p segments] Created {clip_size:.1f}MB combined clip ({len(segment_info_parts)} segments)")
        return clip_path, segment_info_text

    except Exception:
        for p in [raw_path, clip_path] + segment_files:
            if p and os.path.exists(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
        raise

# ===== AI Analysis Endpoints =====

@api_router.get("/videos/{video_id}/processing-status")
async def get_processing_status(video_id: str, current_user: dict = Depends(get_current_user)):
    """Polling endpoint for frontend to check processing progress"""
    video = await db.videos.find_one(
        {"id": video_id, "user_id": current_user["id"]},
        {"_id": 0, "chunk_paths": 0, "chunk_sizes": 0, "chunk_backends": 0}
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Check which analysis types are completed
    completed_types = []
    failed_types = []
    analyses = await db.analyses.find(
        {"video_id": video_id, "user_id": current_user["id"]},
        {"_id": 0, "analysis_type": 1, "status": 1}
    ).to_list(10)
    for a in analyses:
        if a.get("status") == "completed":
            completed_types.append(a["analysis_type"])
        elif a.get("status") == "failed":
            failed_types.append(a["analysis_type"])
    
    return {
        "processing_status": video.get("processing_status", "none"),
        "processing_progress": video.get("processing_progress", 0),
        "processing_current": video.get("processing_current"),
        "processing_error": video.get("processing_error"),
        "processing_completed_at": video.get("processing_completed_at"),
        "completed_types": completed_types,
        "failed_types": failed_types,
        "server_boot_id": SERVER_BOOT_ID
    }

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

@api_router.get("/analysis/video/{video_id}")
async def get_analyses(video_id: str, current_user: dict = Depends(get_current_user)):
    analyses = await db.analyses.find({"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(100)
    return analyses

# ===== Annotations =====

@api_router.post("/annotations", response_model=Annotation)
async def create_annotation(input: AnnotationCreate, current_user: dict = Depends(get_current_user)):
    annotation_obj = Annotation(user_id=current_user["id"], **input.model_dump())
    await db.annotations.insert_one(annotation_obj.model_dump())
    return annotation_obj

@api_router.get("/annotations/video/{video_id}", response_model=List[Annotation])
async def get_annotations(video_id: str, current_user: dict = Depends(get_current_user)):
    annotations = await db.annotations.find({"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(1000)
    return annotations

@api_router.delete("/annotations/{annotation_id}")
async def delete_annotation(annotation_id: str, current_user: dict = Depends(get_current_user)):
    result = await db.annotations.delete_one({"id": annotation_id, "user_id": current_user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"message": "Annotation deleted"}

# ===== Clips =====

@api_router.post("/clips", response_model=Clip)
async def create_clip(input: ClipCreate, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one({"id": input.video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    clip_obj = Clip(user_id=current_user["id"], match_id=video["match_id"], **input.model_dump())
    await db.clips.insert_one(clip_obj.model_dump())
    return clip_obj

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
    if not updates:
        return {"status": "noop"}
    await db.clips.update_one({"id": clip_id}, {"$set": updates})
    return {"status": "updated", **updates}

# ===== Highlights =====

@api_router.get("/highlights/video/{video_id}")
async def get_highlights_package(video_id: str, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one({"id": video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})
    clips = await db.clips.find({"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(1000)
    analyses = await db.analyses.find({"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(100)
    return {
        "match": match,
        "video": {"id": video["id"], "filename": video["original_filename"], "size": video["size"]},
        "clips": clips,
        "analyses": analyses,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }

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

@api_router.get("/markers/video/{video_id}")
async def get_markers(video_id: str, current_user: dict = Depends(get_current_user)):
    markers = await db.markers.find({"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(500)
    return markers

# ===== Clip Video Download (actual MP4 extraction) =====

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

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
