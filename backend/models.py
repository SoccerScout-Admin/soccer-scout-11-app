"""Pydantic models for all entities"""
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: str = "analyst"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class MatchCreate(BaseModel):
    team_home: str
    team_away: str
    date: str
    competition: Optional[str] = None
    folder_id: Optional[str] = None

class MatchUpdate(BaseModel):
    team_home: Optional[str] = None
    team_away: Optional[str] = None
    date: Optional[str] = None
    competition: Optional[str] = None
    folder_id: Optional[str] = None

class Video(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    match_id: str
    original_filename: str
    size: int
    content_type: str = "video/mp4"
    storage_path: Optional[str] = None
    is_chunked: bool = False
    total_chunks: int = 0
    chunk_size: int = 10485760
    chunk_paths: dict = Field(default_factory=dict)
    chunk_sizes: dict = Field(default_factory=dict)
    chunk_backends: dict = Field(default_factory=dict)
    is_deleted: bool = False
    processing_status: str = "none"
    processing_progress: int = 0
    processing_current: Optional[str] = None
    processing_error: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class Annotation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    video_id: str
    timestamp: float
    annotation_type: str
    content: str
    player_id: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class Clip(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    video_id: str
    match_id: Optional[str] = None
    title: str
    start_time: float
    end_time: float
    clip_type: str = "highlight"
    description: Optional[str] = None
    player_ids: List[str] = Field(default_factory=list)
    share_token: Optional[str] = None
    auto_generated: bool = False
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class AnalysisRequest(BaseModel):
    video_id: str
    analysis_type: str

class Folder(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    name: str
    parent_id: Optional[str] = None
    is_private: bool = False
    share_token: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class Player(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    match_id: Optional[str] = None
    team_id: Optional[str] = None
    name: str
    number: Optional[int] = None
    position: Optional[str] = None
    team: Optional[str] = None
    profile_pic_url: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class Team(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    name: str
    club: Optional[str] = None
    season: str
    logo_url: Optional[str] = None
    share_token: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class TrimmedAnalysisRequest(BaseModel):
    video_id: str
    analysis_type: str
    trim_start: Optional[float] = None
    trim_end: Optional[float] = None

class ClipZipRequest(BaseModel):
    clip_ids: List[str]
