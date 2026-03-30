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
    
    hashed = bcrypt.hashpw(input.password.encode('utf-8'), bcrypt.gensalt())
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
    return AuthResponse(token=token, user={"id": user_id, "email": input.email, "name": input.name, "role": input.role})

@api_router.post("/auth/login", response_model=AuthResponse)
async def login(input: LoginRequest):
    user = await db.users.find_one({"email": input.email}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if not bcrypt.checkpw(input.password.encode('utf-8'), user["password"].encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_token(user["id"], user["email"])
    return AuthResponse(token=token, user={"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]})

@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {"id": current_user["id"], "email": current_user["email"], "name": current_user["name"], "role": current_user["role"]}

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
        raise HTTPException(status_code=400, detail="match_id is required")
    
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    
    ext = file.filename.split(".")[-1] if "." in file.filename else "mp4"
    video_id = str(uuid.uuid4())
    path = f"{APP_NAME}/videos/{current_user['id']}/{video_id}.{ext}"
    
    data = await file.read()
    result = put_object(path, data, file.content_type or "video/mp4")
    
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
    
    return {"video_id": video_id, "path": result["path"], "size": result["size"]}

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