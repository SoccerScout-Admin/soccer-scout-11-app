from fastapi import FastAPI, APIRouter, HTTPException, Header, UploadFile, File, Depends
from fastapi.responses import Response, StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import jwt
import bcrypt
import requests
from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
import tempfile
import shutil

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

app = FastAPI()
api_router = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def init_storage():
    global storage_key
    if storage_key:
        return storage_key
    try:
        resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
        resp.raise_for_status()
        storage_key = resp.json()["storage_key"]
        logger.info("Storage initialized successfully")
        return storage_key
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
        raise

def put_object(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=300
    )
    resp.raise_for_status()
    return resp.json()

def get_object(path: str) -> tuple[bytes, str]:
    key = init_storage()
    resp = requests.get(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key}, timeout=120
    )
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")

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
    video_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class MatchCreate(BaseModel):
    team_home: str
    team_away: str
    date: str
    competition: str = ""

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

class ChunkedUploadInit(BaseModel):
    match_id: str
    filename: str
    file_size: int
    content_type: str = "video/mp4"

class ChunkedUploadChunk(BaseModel):
    upload_id: str
    chunk_index: int
    total_chunks: int

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
        logger.warning(f"Login attempt for non-existent user: {input.email}")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    try:
        password_match = bcrypt.checkpw(input.password.encode('utf-8'), user["password"].encode('utf-8'))
        if not password_match:
            logger.warning(f"Invalid password attempt for user: {input.email}")
            raise HTTPException(status_code=401, detail="Invalid email or password")
    except Exception as e:
        logger.error(f"Bcrypt error during login for {input.email}: {str(e)}")
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_token(user["id"], user["email"])
    return AuthResponse(token=token, user={"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]})

@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {"id": current_user["id"], "email": current_user["email"], "name": current_user["name"], "role": current_user["role"]}

@api_router.get("/health")
async def health_check():
    try:
        await db.command('ping')
        db_status = "connected"
    except Exception:
        db_status = "disconnected"
    
    return {
        "status": "healthy",
        "service": "soccer-scout-api",
        "database": db_status,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@api_router.get("/debug/match/{match_id}")
async def debug_match(match_id: str, current_user: dict = Depends(get_current_user)):
    """Debug endpoint to check if match exists for user"""
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    return {
        "match_exists": match is not None,
        "match_id": match_id,
        "user_id": current_user["id"],
        "match": match
    }

@app.get("/health")
async def root_health_check():
    return {
        "status": "healthy",
        "service": "soccer-scout-api",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@api_router.post("/matches", response_model=Match)
async def create_match(input: MatchCreate, current_user: dict = Depends(get_current_user)):
    match_obj = Match(user_id=current_user["id"], **input.model_dump())
    await db.matches.insert_one(match_obj.model_dump())
    return match_obj

@api_router.get("/matches", response_model=List[Match])
async def get_matches(current_user: dict = Depends(get_current_user)):
    matches = await db.matches.find({"user_id": current_user["id"]}, {"_id": 0}).to_list(1000)
    return matches

@api_router.get("/matches/{match_id}", response_model=Match)
async def get_match(match_id: str, current_user: dict = Depends(get_current_user)):
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    return match

@api_router.post("/videos/upload")
async def upload_video(file: UploadFile = File(...), match_id: str = "", current_user: dict = Depends(get_current_user)):
    if not match_id:
        logger.warning(f"Upload attempted without match_id by user {current_user['id']}")
        raise HTTPException(status_code=400, detail="match_id is required")
    
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        logger.warning(f"Upload attempted for non-existent match {match_id} by user {current_user['id']}")
        raise HTTPException(status_code=404, detail="Match not found")
    
    logger.info(f"Starting video upload: {file.filename} ({file.content_type}) for match {match_id}")
    
    ext = file.filename.split(".")[-1] if "." in file.filename else "mp4"
    video_id = str(uuid.uuid4())
    path = f"{APP_NAME}/videos/{current_user['id']}/{video_id}.{ext}"
    
    try:
        # Stream file in chunks to avoid memory issues with large files
        chunk_size = 5 * 1024 * 1024  # 5MB chunks
        file_data = bytearray()
        
        logger.info(f"Reading file in chunks (chunk_size: {chunk_size} bytes)")
        while chunk := await file.read(chunk_size):
            file_data.extend(chunk)
            if len(file_data) % (50 * 1024 * 1024) == 0:  # Log every 50MB
                logger.info(f"Progress: {len(file_data) / (1024*1024):.1f}MB read")
        
        total_size = len(file_data)
        logger.info(f"Video file read successfully: {total_size} bytes ({total_size/(1024*1024):.1f}MB)")
        
        # Upload to storage with timeout handling
        logger.info(f"Uploading {total_size/(1024*1024):.1f}MB to object storage...")
        result = put_object(path, bytes(file_data), file.content_type or "video/mp4")
        logger.info(f"Video uploaded to storage: {result['path']}, size: {result['size']}")
        
        video_doc = {
            "id": video_id,
            "match_id": match_id,
            "user_id": current_user["id"],
            "storage_path": result["path"],
            "original_filename": file.filename,
            "content_type": file.content_type or "video/mp4",
            "size": result["size"],
            "is_deleted": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.videos.insert_one(video_doc)
        await db.matches.update_one({"id": match_id}, {"$set": {"video_id": video_id}})
        
        logger.info(f"Video upload complete: {video_id} ({result['size']} bytes)")
        return {"video_id": video_id, "path": result["path"], "size": result["size"]}
    except Exception as e:
        logger.error(f"Video upload failed for match {match_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@api_router.post("/videos/upload/init")
async def init_chunked_upload(input: ChunkedUploadInit, current_user: dict = Depends(get_current_user)):
    """Initialize a chunked upload for large files (10GB+) - supports resume"""
    match = await db.matches.find_one({"id": input.match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    # Check for existing upload session with same file
    existing_upload = await db.chunked_uploads.find_one({
        "user_id": current_user["id"],
        "match_id": input.match_id,
        "filename": input.filename,
        "file_size": input.file_size,
        "status": {"$in": ["initialized", "in_progress"]}
    }, {"_id": 0})
    
    if existing_upload:
        # Check if temp directory actually exists
        upload_id = existing_upload["upload_id"]
        temp_dir = f"/tmp/video_uploads/{upload_id}"
        
        if os.path.exists(temp_dir):
            # Valid resume - temp files exist
            video_id = existing_upload["video_id"]
            chunks_received = existing_upload.get("chunks_received", 0)
            chunk_size = 10485760  # 10MB
            
            # Get list of already uploaded chunks
            uploaded_chunks = []
            chunk_files = [f for f in os.listdir(temp_dir) if f.startswith('chunk_')]
            uploaded_chunks = [int(f.split('_')[1].split('.')[0]) for f in chunk_files]
            uploaded_chunks.sort()
            
            logger.info(f"Resuming upload: {upload_id} for video {video_id}, {len(uploaded_chunks)} chunks found on disk")
            return {
                "upload_id": upload_id,
                "video_id": video_id,
                "chunk_size": chunk_size,
                "resume": True,
                "chunks_received": len(uploaded_chunks),
                "uploaded_chunks": uploaded_chunks
            }
        else:
            # Temp files missing - mark as failed and create new session
            logger.warning(f"Upload {upload_id} has no temp files, marking as failed")
            await db.chunked_uploads.update_one(
                {"upload_id": upload_id},
                {"$set": {"status": "failed", "error": "Temp files not found"}}
            )
    
    # Create new upload session
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
        "chunks_received": 0,
        "status": "initialized",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_chunk_at": datetime.now(timezone.utc).isoformat()
    }
    await db.chunked_uploads.insert_one(upload_doc)
    
    logger.info(f"Initialized new chunked upload: {upload_id} for video {video_id}, size: {input.file_size} bytes")
    return {"upload_id": upload_id, "video_id": video_id, "chunk_size": 10485760, "resume": False}

@api_router.get("/videos/upload/status/{upload_id}")
async def get_upload_status(upload_id: str, current_user: dict = Depends(get_current_user)):
    """Get status of a chunked upload"""
    upload = await db.chunked_uploads.find_one({"upload_id": upload_id, "user_id": current_user["id"]}, {"_id": 0})
    if not upload:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    # Get list of uploaded chunks
    uploaded_chunks = []
    temp_dir = f"/tmp/video_uploads/{upload_id}"
    if os.path.exists(temp_dir):
        chunk_files = [f for f in os.listdir(temp_dir) if f.startswith('chunk_')]
        uploaded_chunks = [int(f.split('_')[1].split('.')[0]) for f in chunk_files]
        uploaded_chunks.sort()
    
    return {
        "upload_id": upload_id,
        "video_id": upload.get("video_id"),
        "filename": upload.get("filename"),
        "file_size": upload.get("file_size"),
        "chunks_received": upload.get("chunks_received", 0),
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
    """Upload a single chunk of a large video file - stores to temp file, supports resume"""
    upload = await db.chunked_uploads.find_one({"upload_id": upload_id, "user_id": current_user["id"]}, {"_id": 0})
    if not upload:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    # Setup temp directory (use /tmp which has more space)
    temp_dir = f"/tmp/video_uploads/{upload_id}"
    os.makedirs(temp_dir, exist_ok=True)
    chunk_file_path = f"{temp_dir}/chunk_{chunk_index:06d}.bin"
    
    # Check if chunk already exists (resume scenario)
    if os.path.exists(chunk_file_path):
        existing_size = os.path.getsize(chunk_file_path)
        logger.info(f"Chunk {chunk_index+1}/{total_chunks} already exists (resume), size: {existing_size} bytes")
        
        # Update status to in_progress
        await db.chunked_uploads.update_one(
            {"upload_id": upload_id},
            {"$set": {"status": "in_progress", "last_chunk_at": datetime.now(timezone.utc).isoformat()}}
        )
        
        # If all chunks received, finalize
        if chunk_index + 1 == total_chunks:
            # Check if we actually have all chunks
            chunk_files = [f for f in os.listdir(temp_dir) if f.startswith('chunk_')]
            if len(chunk_files) >= total_chunks:
                logger.info(f"All chunks present for {upload_id}, starting assembly...")
                return await finalize_chunked_upload(upload_id, current_user, temp_dir)
        
        return {"status": "chunk_skipped", "chunk_index": chunk_index, "message": "Chunk already uploaded (resumed)"}
    
    # Read and save new chunk data
    chunk_data = await file.read()
    with open(chunk_file_path, 'wb') as f:
        f.write(chunk_data)
    
    # Update progress
    await db.chunked_uploads.update_one(
        {"upload_id": upload_id},
        {
            "$inc": {"chunks_received": 1},
            "$set": {
                "status": "in_progress",
                "last_chunk_at": datetime.now(timezone.utc).isoformat()
            }
        }
    )
    
    logger.info(f"Chunk {chunk_index+1}/{total_chunks} saved for upload {upload_id}, size: {len(chunk_data)} bytes")
    
    # If all chunks received, assemble and upload to storage
    if chunk_index + 1 == total_chunks:
        # Double-check all chunks are present
        chunk_files = [f for f in os.listdir(temp_dir) if f.startswith('chunk_')]
        if len(chunk_files) >= total_chunks:
            logger.info(f"All {total_chunks} chunks received for {upload_id}, starting assembly...")
            return await finalize_chunked_upload(upload_id, current_user, temp_dir)
        else:
            logger.warning(f"Final chunk received but only {len(chunk_files)}/{total_chunks} chunks present")
    
    return {"status": "chunk_received", "chunk_index": chunk_index, "chunks_received": chunk_index + 1, "total_chunks": total_chunks}

async def finalize_chunked_upload(upload_id: str, current_user: dict, temp_dir: str):
    """Assemble chunks from temp files and upload to storage"""
    upload = await db.chunked_uploads.find_one({"upload_id": upload_id}, {"_id": 0})
    if not upload:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    try:
        logger.info(f"Assembling file from temp directory: {temp_dir}")
        
        # Get all chunk files sorted by index
        chunk_files = sorted([f for f in os.listdir(temp_dir) if f.startswith('chunk_')])
        total_chunks = len(chunk_files)
        
        logger.info(f"Found {total_chunks} chunk files to assemble")
        
        # Create a temporary file for the assembled video
        assembled_file_path = f"{temp_dir}/assembled_video.tmp"
        total_size = 0
        
        # Assemble chunks into single file
        with open(assembled_file_path, 'wb') as outfile:
            for i, chunk_file in enumerate(chunk_files):
                chunk_path = os.path.join(temp_dir, chunk_file)
                with open(chunk_path, 'rb') as infile:
                    chunk_data = infile.read()
                    outfile.write(chunk_data)
                    total_size += len(chunk_data)
                
                if (i + 1) % 100 == 0:
                    logger.info(f"Assembled {i+1}/{total_chunks} chunks ({total_size/(1024*1024*1024):.2f}GB)")
        
        logger.info(f"File fully assembled: {total_size} bytes ({total_size/(1024*1024*1024):.2f}GB)")
        
        # Upload assembled file to storage
        ext = upload["filename"].split(".")[-1] if "." in upload["filename"] else "mp4"
        storage_path = f"{APP_NAME}/videos/{upload['user_id']}/{upload['video_id']}.{ext}"
        
        logger.info(f"Uploading assembled file to storage: {storage_path}")
        
        # Read assembled file and upload
        with open(assembled_file_path, 'rb') as f:
            file_data = f.read()
        
        result = put_object(storage_path, file_data, upload["content_type"])
        logger.info(f"Upload to storage complete: {result['path']}")
        
        # Save video metadata
        video_doc = {
            "id": upload["video_id"],
            "match_id": upload["match_id"],
            "user_id": upload["user_id"],
            "storage_path": result["path"],
            "original_filename": upload["filename"],
            "content_type": upload["content_type"],
            "size": result["size"],
            "is_deleted": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        await db.videos.insert_one(video_doc)
        await db.matches.update_one({"id": upload["match_id"]}, {"$set": {"video_id": upload["video_id"]}})
        
        # Update upload status
        await db.chunked_uploads.update_one(
            {"upload_id": upload_id},
            {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}}
        )
        
        # Clean up temporary files
        logger.info(f"Cleaning up temporary files: {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        logger.info(f"Chunked upload finalized: {upload['video_id']}")
        return {"status": "completed", "video_id": upload["video_id"], "path": result["path"], "size": result["size"]}
    
    except Exception as e:
        logger.error(f"Failed to finalize chunked upload {upload_id}: {str(e)}")
        # Clean up on error
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        
        await db.chunked_uploads.update_one(
            {"upload_id": upload_id},
            {"$set": {"status": "failed", "error": str(e)}}
        )
        raise HTTPException(status_code=500, detail=f"Upload finalization failed: {str(e)}")

@api_router.get("/videos/{video_id}")
async def get_video(video_id: str, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one({"id": video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    data, content_type = get_object(video["storage_path"])
    return Response(content=data, media_type=video["content_type"])

@api_router.get("/videos/{video_id}/metadata")
async def get_video_metadata(video_id: str, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one({"id": video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video

@api_router.post("/analysis/generate")
async def generate_analysis(input: AnalysisRequest, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one({"id": input.video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})
    
    data, _ = get_object(video["storage_path"])
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{video['original_filename'].split('.')[-1]}") as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    
    try:
        chat = LlmChat(
            api_key=EMERGENT_KEY,
            session_id=f"analysis-{input.video_id}",
            system_message="You are an expert soccer analyst. Analyze match videos and provide detailed tactical insights."
        ).with_model("gemini", "gemini-3.1-pro-preview")
        
        video_file = FileContentWithMimeType(
            file_path=tmp_path,
            mime_type=video["content_type"]
        )
        
        prompts = {
            "tactical": f"Analyze this soccer match video between {match['team_home']} and {match['team_away']}. Provide detailed tactical analysis covering: formations used, pressing patterns, build-up play, defensive organization, key tactical moments, and suggested improvements.",
            "player_performance": f"Analyze individual player performances in this match. Identify standout players, areas of strength and weakness, work rate, positioning, and decision-making quality.",
            "highlights": f"Identify and describe the key moments and highlights from this match: goals, near-misses, crucial saves, tactical changes, momentum shifts, and game-changing plays."
        }
        
        prompt = prompts.get(input.analysis_type, prompts["tactical"])
        
        response = await chat.send_message(UserMessage(
            text=prompt,
            file_contents=[video_file]
        ))
        
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
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

@api_router.get("/analysis/video/{video_id}")
async def get_analyses(video_id: str, current_user: dict = Depends(get_current_user)):
    analyses = await db.analyses.find({"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(100)
    return analyses

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

@api_router.post("/clips", response_model=Clip)
async def create_clip(input: ClipCreate, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one({"id": input.video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    clip_obj = Clip(
        user_id=current_user["id"],
        match_id=video["match_id"],
        **input.model_dump()
    )
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

@api_router.get("/highlights/video/{video_id}")
async def get_highlights_package(video_id: str, current_user: dict = Depends(get_current_user)):
    video = await db.videos.find_one({"id": video_id, "user_id": current_user["id"], "is_deleted": False}, {"_id": 0})
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})
    clips = await db.clips.find({"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(1000)
    analyses = await db.analyses.find({"video_id": video_id, "user_id": current_user["id"]}, {"_id": 0}).to_list(100)
    
    package = {
        "match": match,
        "video": {
            "id": video["id"],
            "filename": video["original_filename"],
            "size": video["size"]
        },
        "clips": clips,
        "analyses": analyses,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }
    
    return package

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


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    try:
        init_storage()
        logger.info("Storage initialized")
    except Exception as e:
        logger.error(f"Storage init failed: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()