from fastapi import FastAPI, APIRouter, HTTPException, Header, UploadFile, File, Depends, Request, Query
from fastapi.responses import Response, StreamingResponse, JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from motor.motor_asyncio import AsyncIOMotorClient
import os
import stat
import re
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import jwt
import bcrypt
from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
import tempfile
import asyncio
import subprocess

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
from routes.highlight_reels import router as highlight_reels_router
from routes.recruiter_lens import router as recruiter_lens_router

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

# iter83 — persistent PV-backed fallback path for chunks (used by dismiss
# cleanup in iter85 to free local-disk space for abandoned sessions).
from db import PERSISTENT_CHUNK_DIR  # noqa: E402,F401


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

# Cookie config — same-origin deployment (preview & production both serve frontend
# and API from the same host), so SameSite=Lax is sufficient against CSRF for most
# unsafe-method calls. Path=/ so it's sent on /api/* requests. Max-age matches the
# 7-day JWT expiry. Secure=True in production (HTTPS).
ACCESS_TOKEN_COOKIE = "access_token"
ACCESS_TOKEN_COOKIE_MAX_AGE = 7 * 24 * 60 * 60  # 7 days, matches JWT expiry
ACCESS_TOKEN_COOKIE_SECURE = os.environ.get("ENVIRONMENT", "").lower() != "development"

# CSRF protection — double-submit token pattern (iter54).
# We pair every cookie-authenticated session with a non-HttpOnly `csrf_token`
# cookie. Frontend reads it via document.cookie and echoes it back as the
# `X-CSRF-Token` header on every unsafe-method request. Server compares the
# two — if they don't match → 403. An attacker on another origin cannot read
# the cookie (Same-Origin Policy blocks document.cookie cross-site), so they
# cannot forge the matching header → cookie auth is now CSRF-proof.
CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_COOKIE_MAX_AGE = ACCESS_TOKEN_COOKIE_MAX_AGE  # same lifetime as session

def _generate_csrf_token() -> str:
    """32 bytes of URL-safe randomness — ~256 bits of entropy. Unguessable."""
    import secrets
    return secrets.token_urlsafe(32)

def _set_csrf_cookie(response: Response, token: str) -> None:
    """Set the CSRF token cookie. NOT HttpOnly — frontend must read it via JS
    to echo in the X-CSRF-Token header (that's the double-submit pattern).
    SameSite=Lax + Secure still apply, so the cookie won't be sent on
    cross-site unsafe methods regardless."""
    response.set_cookie(
        key=CSRF_COOKIE,
        value=token,
        httponly=False,  # must be JS-readable for the double-submit echo
        secure=ACCESS_TOKEN_COOKIE_SECURE,
        samesite="lax",
        max_age=CSRF_COOKIE_MAX_AGE,
        path="/",
    )

def _clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(key=CSRF_COOKIE, path="/")


def _set_auth_cookie(response: Response, token: str) -> None:
    """Set the httpOnly auth cookie on a FastAPI Response.

    httponly=True → blocks JS read access → XSS-proof.
    samesite='lax' → blocks cross-site POST/DELETE but allows top-level GET nav.
    secure=True (in prod) → cookie only sent over HTTPS.
    path='/' so it's sent on every /api/* call.
    """
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=token,
        httponly=True,
        secure=ACCESS_TOKEN_COOKIE_SECURE,
        samesite="lax",
        max_age=ACCESS_TOKEN_COOKIE_MAX_AGE,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE, path="/")


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

async def _maybe_autopromote_admin(user: dict) -> dict:
    """If `ADMIN_AUTOPROMOTE_EMAIL` env var is set and the user's email matches
    (case-insensitive), flip their role to `admin` and return the updated user
    dict. Idempotent — already-admin users are a no-op. Supports
    comma-separated lists so multiple owners can be configured without a code
    change. Logged at WARNING level so we have an audit trail of every
    auto-promotion in production logs (iter76, real production owner-onboard
    fix 2026-05-18)."""
    raw = os.environ.get("ADMIN_AUTOPROMOTE_EMAIL", "").strip()
    if not raw:
        return user
    current_role = (user.get("role") or "").lower()
    if current_role in ("admin", "owner"):
        return user  # nothing to do
    user_email = (user.get("email") or "").strip().lower()
    if not user_email:
        return user
    allowed = {e.strip().lower() for e in raw.split(",") if e.strip()}
    if user_email not in allowed:
        return user
    try:
        await db.users.update_one(
            {"id": user["id"]}, {"$set": {"role": "admin"}}
        )
        logger.warning(
            f"ADMIN_AUTOPROMOTE_EMAIL match — promoted {user_email} "
            f"from role={current_role!r} to role='admin' (user_id={user['id']})"
        )
        user["role"] = "admin"
    except Exception as e:
        # Failing to promote must never break login or auth — log and proceed.
        logger.error(f"Admin auto-promote failed for {user_email}: {e}")
    return user


async def get_current_user(request: Request, authorization: str = Header(None)):
    """Authenticate the caller. Reads the httpOnly access_token cookie first
    (XSS-proof, the migration target); falls back to the legacy Authorization
    Bearer header so users with existing localStorage tokens stay logged in
    until their next login refreshes the cookie."""
    token = None
    # 1) Preferred: httpOnly cookie
    cookie_token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if cookie_token:
        token = cookie_token
    # 2) Legacy fallback: Authorization Bearer header (existing clients)
    elif authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = verify_token(token)
    user = await db.users.find_one({"id": payload["user_id"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # iter76: auto-promote on every authenticated request so an existing
    # logged-in user gets their role flipped without a logout/login cycle.
    user = await _maybe_autopromote_admin(user)
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
async def register(input: RegisterRequest, response: Response):
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
    _set_auth_cookie(response, token)  # httpOnly cookie — primary auth channel
    _set_csrf_cookie(response, _generate_csrf_token())  # csrf double-submit token
    logger.info(f"New user registered: {input.email}")
    # Token still returned in JSON for backwards-compat with old frontends that
    # haven't shipped the cookie-aware code yet. Safe to remove in a future
    # iteration once all clients are on >= iter52.
    return AuthResponse(token=token, user={"id": user_id, "email": input.email, "name": input.name, "role": input.role})

@api_router.post("/auth/login", response_model=AuthResponse)
async def login(input: LoginRequest, request: Request, response: Response):
    # Brute-force guard — check BEFORE bcrypt to deny attackers both the slow
    # comparison (CPU DoS surface) and any timing oracle. Raises 429 with
    # Retry-After on lockout.
    from services.login_rate_limiter import (
        check_login_attempt, record_failed_login, record_successful_login,
    )
    await check_login_attempt(request, input.email, db)

    user = await db.users.find_one({"email": input.email}, {"_id": 0})
    if not user:
        await record_failed_login(request, input.email, db)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    try:
        if not bcrypt.checkpw(input.password.encode('utf-8'), user["password"].encode('utf-8')):
            await record_failed_login(request, input.email, db)
            raise HTTPException(status_code=401, detail="Invalid email or password")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bcrypt error during login for {input.email}: {str(e)}")
        await record_failed_login(request, input.email, db)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    await record_successful_login(request, input.email, db)
    # iter76: auto-promote owner emails BEFORE issuing the token so the
    # returned role reflects the updated value the rest of the session uses.
    user = await _maybe_autopromote_admin(user)
    token = create_token(user["id"], user["email"])
    _set_auth_cookie(response, token)
    _set_csrf_cookie(response, _generate_csrf_token())  # csrf double-submit token
    return AuthResponse(token=token, user={"id": user["id"], "email": user["email"], "name": user["name"], "role": user["role"]})

@api_router.post("/auth/logout")
async def logout(response: Response):
    """Clear the auth cookie + CSRF cookie. Idempotent — safe to call without an active session."""
    _clear_auth_cookie(response)
    _clear_csrf_cookie(response)
    return {"status": "logged_out"}

@api_router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {"id": current_user["id"], "email": current_user["email"], "name": current_user["name"], "role": current_user["role"]}

# ===== Health =====

# Build metadata — captured at module load so it reflects the actual deployed code.
# BUILD_VERSION should be bumped each iteration that ships to production.
# SHIPPED_FEATURES is the human-readable changelog the dashboard footer pings to confirm
# "yes, the latest code reached production".
BUILD_VERSION = "iter104"

# Max number of times resume_interrupted_processing will re-queue a video
# that's still stuck at 0% progress. After this many attempts with no
# forward movement, we conclude the pod is OOM-killing ffmpeg BEFORE the
# Python handler can fire iter63's auto-retry tier, and we mark the video
# failed with the same "compress with HandBrake" guidance — better to fail
# clearly than infinite-loop the pod across the rest of the user's work.
_MAX_RESUME_ATTEMPTS = 3
SHIPPED_FEATURES = [
    "auto-highlight-reels",
    "trending-reel-library",
    "weekly-reel-recap",
    "disk-safety-sweepers",
    "pwa-install-modal",
    "qr-code-install-share",
    "pwa-install-share-teammate",
    "upload-limit-20gb",
    "compress-before-upload-tip",
    "smart-large-file-nudge",
    "compression-calculator",
    "send-compression-instructions",
    "notify-when-upload-done",
    "gitignore-deploy-fix",
    "build-info-chip",
    "build-staleness-warning",
    "aggressive-disk-sweeper-5min",
    "disk-pressure-circuit-breaker",
    "disk-stats-in-health-endpoint",
    "disk-pressure-banner",
    "httponly-cookie-auth",
    "dashboard-hook-refactor",
    "manual-result-summary-split",
    "csrf-double-submit-protection",
    "routes-auth-cookie-sync-fix",
    "login-brute-force-rate-limit",
    "compute-benchmarks-refactor",
    "download-clips-zip-refactor",
    "test-credential-fixture",
    "unused-imports-cleanup",
    "player-edit-modal",
    "player-birth-year-and-grade",
    "auto-scroll-on-form-open",
    "radon-precommit-hook",
    "csv-roster-import-demographics",
    # iter59 — Recruiter Lens family
    "shareable-filtered-team-urls",
    "recruiter-outreach-tracked-emails",
    "hot-lead-auto-followup",
    "recruiter-lens-og-cards",
    # iter60 — production deploy polish
    "disk-pressure-threshold-95pct",
    "dashboard-empty-state-welcome",
    "dashboard-promo-cards-hidden-when-empty",
    # iter61 — roster-first match creation
    "create-match-roster-step",
    "import-existing-team-roster",
    "match-roster-csv-paste",
    "awaiting-roster-gate-and-banner",
    "match-roster-status-endpoint",
    "run-anyway-override",
    # iter62 — ffmpeg failure clarity
    "ffmpeg-error-classification",
    "ffmpeg-oom-detection",
    "ffmpeg-timeout-detection",
    "stderr-tail-not-head",
    # iter63 — blank-screen fix + ffmpeg auto-retry + jsx-no-undef regression test
    "match-detail-missing-import-fix",
    "use-clip-collection-setter-fix",
    "eslint-strict-jsx-no-undef-config",
    "frontend-undefined-references-regression-test",
    "ffmpeg-auto-retry-aggressive-scaling",
    "ffmpeg-deterministic-failure-no-retry",
    # iter64 — processing-events instrumentation
    "processing-events-collection",
    "processing-events-stats-endpoint",
    "processing-events-recent-endpoint",
    "retry-save-rate-tracking",
    # iter65 — admin dashboard + auto-alert spike detector
    "admin-processing-events-dashboard",
    "processing-pipeline-charts",
    "hourly-failure-rate-alert",
    "alert-dedup-window",
    "alert-escalation-on-rising-rate",
    "manual-alert-trigger-endpoint",
    # iter66 — complexity refactors from code-review report
    "refactor-processing-events-stats",
    "refactor-generate-match-insights",
    "refactor-build-match-recap-prompt",
    "refactor-browse-public-reels",
    "refactor-my-reel-stats",
    # iter82 — patience through transient object-storage outages
    "client-upload-retry-budget-20",
    "storage-degraded-friendly-status",
    "auto-refresh-pending-uploads-banner-on-failure",
    "put-object-retry-budget-6",
    "predeploy-gitignore-cleanup-script",
    # iter83 — persistent chunk fallback + supervisor self-healing gitignore
    "persistent-chunk-fallback-on-app-pv",
    "background-chunk-migration-loop",
    "supervisor-gitignore-keeper-watchdog",
    "no-more-503-on-filesystem-fallback",
    "persistent-storage-pressure-503",
    # iter84 — resume across devices
    "resume-across-devices-banner",
    "me-pending-uploads-endpoint",
    # iter85 — dismiss button on resume banner
    "dismiss-pending-upload-endpoint",
    "resume-banner-row-dismiss-buttons",
    "dismiss-frees-persistent-fallback-chunks",
    # iter86 — in-app cross-device notifications + TTL sweeper
    "me-notifications-recent-endpoint",
    "in-app-notification-polling",
    "processing-complete-fires-user-notification",
    "dismissed-uploads-30d-ttl-sweeper",
    "user-notifications-30d-ttl-sweeper",
    # iter87 — P0 fix: moov atom corruption from migration race
    "migration-write-then-update-then-delete-ordering",
    "fail-fast-on-missing-chunk-no-more-zero-fill",
    "persistent-filesystem-existence-check-in-integrity",
    # iter88 — recovery path for stuck videos
    "recover-chunks-endpoint",
    "try-recovery-button-on-failed-banner",
    "migrate-one-chunk-3-state-result",
    "chunk-backend-lost-tag-excluded-from-integrity",
    # iter89 — disable dangerous /app fallback by default, broaden recovery gate
    "persistent-filesystem-fallback-opt-in-via-env",
    "try-recovery-button-broadened-to-all-storage-failures",
    "persistent-fallback-warn-log-audit",
    "503-retry-after-60s-when-fallback-disabled",
    # iter90 — pre-flight storage probe to fail-fast on outages
    "storage-health-probe-endpoint",
    "client-preflight-storage-check",
    "storage-probe-30s-cache",
    # iter91 — global storage outage banner
    "global-storage-outage-banner",
    # iter92 — bulk resume picker
    "bulk-resume-modal",
    "me-pending-uploads-exposes-file-size-bytes",
    "resume-all-button-on-banner",
    # iter93 — storage cleanup report for support escalation
    "storage-cleanup-report-endpoint",
    # iter94 — storage cleanup UI + proactive leak tracking
    "storage-cleanup-admin-ui",
    "mark-orphan-chunks-endpoint",
    "weekly-storage-growth-audit",
    "storage-growth-trend-history",
    "copy-support-email-draft",
    # iter95 — broaden orphan detection to catch the actual leak sources
    "orphan-bucket-abandoned-uploads",
    "orphan-bucket-completed-uploads-without-video",
    "orphan-bucket-stuck-videos",
    "shared-orphan-bucket-collector",
    # iter96 — weekly storage-growth digest email
    "weekly-storage-growth-digest-email",
    "storage-digest-opt-out-preference",
    "send-storage-digest-now-endpoint",
    "growth-threshold-1gb-trigger",
    # iter97 — pod-OOM-cycle remediation for sub-2GB videos
    "aggressive-tier-threshold-800mb",
    "ffmpeg-memory-guards-threads1-bufsize",
    "rapid-oom-cycle-detection-2-attempts-5min",
    "pod-cycling-yellow-warning-banner",
    # iter98 — async analysis generation to dodge Cloudflare 100s edge timeout
    "async-analysis-generate-202",
    "async-analysis-generate-trimmed-202",
    "analysis-status-polling-frontend",
    "pending-analysis-row-placeholder",
    # iter99 — AI quality bump for goal/player recognition
    "ai-segments-18x45s-denser-coverage",
    "ai-segments-720p-legible-jersey-numbers",
    "ai-prompt-explicit-goal-detection-cues",
    "ai-marker-player-number-and-name-fields",
    "ai-player-performance-jersey-first-prompt",
    # iter100 — Rich markers panel UI
    "markers-panel-scannable-list",
    "markers-panel-type-filter-pills",
    "markers-panel-jersey-avatars",
    "markers-panel-click-to-seek",
    # iter101 — scene-cut-biased segment selection to actually catch goals
    "scene-cut-biased-segment-selection",
    "ffmpeg-scdet-240p-proxy-detection",
    "non-overlapping-window-greedy-pick",
    "even-spacing-fallback-on-scdet-failure",
    "marker-prompt-celebration-fallback-goal-detection",
    "marker-prompt-no-guess-jersey-numbers",
    "segments-crf-24-better-jersey-legibility",
    # iter102 — Hudl-style manual player tagging on AI markers
    "marker-patch-endpoint",
    "marker-delete-endpoint",
    "marker-manual-tag-provenance-badge",
    "tag-player-modal-roster-picker",
    "marker-row-edit-pencil-button",
    # iter103 — segment-encoder tier-down for >800MB files (memory regression fix)
    "segments-tier-down-800mb-480p",
    "segments-skip-scdet-on-heavy-files",
    "cycling-banner-blameless-messaging",
    # iter104 — memory probe endpoint to verify support's pod-size bump
    "health-memory-cgroup-probe",
]

def _get_build_sha() -> str:
    """Best-effort git SHA lookup. Returns 'unknown' if git isn't available
    (e.g., in a minimal deployment image with .git stripped)."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2, cwd="/app",
        )
        if result.returncode == 0:
            return result.stdout.strip() or "unknown"
    except Exception:
        pass
    return "unknown"

BUILD_SHA = _get_build_sha()
BUILT_AT = datetime.now(timezone.utc).isoformat()

@api_router.get("/health/memory")
async def memory_health():
    """iter104 — Expose the pod's actual cgroup memory limit + current RSS
    so we can confirm whether Emergent Support's "bump to 20 GB" actually
    landed in production. If production reports 4 GB instead of 20 GB, the
    support ticket didn't ship — user needs to escalate."""
    cgroup_limit_bytes = None
    cgroup_path_used = None
    # cgroup v2 (modern containers)
    for candidate in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(candidate) as f:
                raw = f.read().strip()
            if raw and raw != "max":
                cgroup_limit_bytes = int(raw)
                cgroup_path_used = candidate
                break
        except (OSError, ValueError):
            continue

    # Current RSS of THIS process
    rss_bytes = None
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    rss_bytes = int(line.split()[1]) * 1024
                    break
    except OSError:
        pass

    # Host total memory for context
    host_total_bytes = None
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    host_total_bytes = int(line.split()[1]) * 1024
                    break
    except OSError:
        pass

    def _gb(n):
        return round(n / (1024 ** 3), 2) if n else None

    # The iter97/iter103 tier thresholds depend on this. Surface them so
    # the user/admin can see whether the safe-tier logic actually needs to
    # fire on their pod size.
    return {
        "cgroup_limit_bytes": cgroup_limit_bytes,
        "cgroup_limit_gb": _gb(cgroup_limit_bytes),
        "cgroup_path": cgroup_path_used,
        "process_rss_bytes": rss_bytes,
        "process_rss_gb": _gb(rss_bytes),
        "host_total_bytes": host_total_bytes,
        "host_total_gb": _gb(host_total_bytes),
        "iter103_heavy_file_threshold_gb": 0.8,
        "verdict": (
            "20gb-class-pod-confirmed" if cgroup_limit_bytes and cgroup_limit_bytes >= 18 * 1024 ** 3
            else "8gb-class-pod" if cgroup_limit_bytes and cgroup_limit_bytes >= 7 * 1024 ** 3
            else "4gb-or-smaller-pod-needs-support-bump" if cgroup_limit_bytes
            else "unknown"
        ),
    }


@api_router.get("/health")
async def health_check():
    try:
        await db.command('ping')
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    # Disk usage — surfaces the same data that triggers the upload circuit
    # breaker so the dashboard chip + admins can see disk pressure at a glance.
    disk = None
    try:
        import shutil as _shutil
        total, used, free = _shutil.disk_usage(CHUNK_STORAGE_DIR)
        pct = round((used / total) * 100, 1) if total > 0 else 0
        disk = {
            "used_gb": round(used / (1024 ** 3), 2),
            "total_gb": round(total / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2),
            "used_pct": pct,
            "uploads_blocked": pct >= DISK_FULL_THRESHOLD_PCT or free < DISK_FULL_RESERVE_BYTES,
            "threshold_pct": DISK_FULL_THRESHOLD_PCT,
        }
    except (OSError, NameError):
        pass

    return {
        "status": "healthy",
        "service": "soccer-scout-api",
        "database": db_status,
        "disk": disk,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@api_router.get("/health/deploy")
async def deploy_health():
    """Returns build metadata so the user can verify which version is live in
    production without clicking through every feature. Public endpoint — no
    auth required (build info isn't sensitive)."""
    return {
        "build": BUILD_VERSION,
        "sha": BUILD_SHA,
        "built_at": BUILT_AT,
        "features": SHIPPED_FEATURES,
        "feature_count": len(SHIPPED_FEATURES),
    }

@app.get("/health")
async def root_health_check():
    return {"status": "healthy", "service": "soccer-scout-api", "timestamp": datetime.now(timezone.utc).isoformat()}


# ===== iter90 — Object Storage pre-flight probe =====
#
# Real production bug 2026-05-23: Emergent's object storage backend went
# fully unavailable for >1h, returning 500 on every PUT and GET. With
# iter89's correct refusal to fall back to ephemeral /app, every chunk
# upload 503'd and the iter82 client burned its full 20-retry budget
# (~15 min) before alerting the user — three separate times. This probe
# lets the frontend fail FAST with a friendly modal BEFORE the 15-minute
# loop. The probe is a single ~1KB PUT roundtrip cached for 30s.

import time as _time_for_probe  # noqa: E402

_STORAGE_PROBE_CACHE = {"at": 0.0, "result": None}
_STORAGE_PROBE_TTL_SECS = 30


async def _probe_object_storage(now_ts: float) -> dict:
    """Single-shot health probe: init → PUT ~1KB → return result.
    Doesn't do a GET roundtrip — if PUT succeeds we trust the read path
    (the real outage broke both, but PUT alone is sufficient signal and
    half the latency)."""
    import asyncio as _asyncio
    import requests as _requests
    from db import STORAGE_URL, EMERGENT_KEY, APP_NAME

    def _sync():
        sess = _requests.Session()
        try:
            r = sess.post(f"{STORAGE_URL}/init",
                          json={"emergent_key": EMERGENT_KEY}, timeout=(3, 5))
            if r.status_code != 200:
                return {"healthy": False, "reason": f"init returned {r.status_code}",
                        "latency_ms": int((_time_for_probe.time() - now_ts) * 1000)}
            key = r.json().get("storage_key")
            if not key:
                return {"healthy": False, "reason": "init returned no storage_key",
                        "latency_ms": int((_time_for_probe.time() - now_ts) * 1000)}
            r = sess.put(
                f"{STORAGE_URL}/objects/{APP_NAME}/healthcheck/iter90_probe_{int(now_ts)}.bin",
                headers={"X-Storage-Key": key, "Content-Type": "application/octet-stream"},
                data=b"probe" * 200,  # ~1KB
                timeout=(3, 8),
            )
            if r.status_code == 200:
                return {"healthy": True, "latency_ms": int((_time_for_probe.time() - now_ts) * 1000)}
            return {"healthy": False, "reason": f"PUT returned {r.status_code}",
                    "latency_ms": int((_time_for_probe.time() - now_ts) * 1000)}
        except Exception as e:
            return {"healthy": False, "reason": f"{type(e).__name__}: {str(e)[:80]}",
                    "latency_ms": int((_time_for_probe.time() - now_ts) * 1000)}

    return await _asyncio.get_event_loop().run_in_executor(None, _sync)


@api_router.get("/health/storage")
async def storage_health_probe():
    """Real probe of Emergent Object Storage. Caches the result for 30s so
    a burst of upload attempts can't DDoS the upstream. Public endpoint —
    no auth — because the frontend needs to check this BEFORE init (which
    is also auth'd, but checking here means we can tell the user instantly
    that an upload would fail).

    Returns:
      {healthy: true, latency_ms: 50, cached: false}
      OR
      {healthy: false, reason: "PUT returned 500", latency_ms: 87, cached: false}
    """
    import time as _time
    now = _time.time()
    cached = _STORAGE_PROBE_CACHE["result"]
    if cached and (now - _STORAGE_PROBE_CACHE["at"]) < _STORAGE_PROBE_TTL_SECS:
        return {**cached, "cached": True}

    result = await _probe_object_storage(now)
    _STORAGE_PROBE_CACHE["at"] = now
    _STORAGE_PROBE_CACHE["result"] = result
    return {**result, "cached": False}


# ===== iter93 — Object Storage cleanup report =====
#
# Real production incident 2026-05-24: Emergent Support told the user
# "your account hit its object-storage capacity limit" — but the user has
# NEVER successfully completed an upload + analysis cycle. So how is it
# full?
#
# Investigation found:
#   • Emergent Object Storage exposes `Allow: PUT, GET, HEAD` — there is
#     NO DELETE endpoint exposed to the app. Users cannot reclaim storage.
#   • Every failed upload, paused session, dismissed video, and re-tried
#     migration leaves chunks behind in object storage forever.
#   • Across iter80-iter88 the user accumulated ~10-30 GB of orphan
#     chunks per major upload attempt.
#
# This endpoint generates a report — a JSON inventory of every chunk in
# object storage that is SAFE TO DELETE per the app's own state. The user
# can email this report to support@emergent.sh asking for a one-time
# server-side purge (until Emergent ships a DELETE API).


@api_router.get("/admin/storage-cleanup/report")
async def storage_cleanup_report(current_user: dict = Depends(get_current_user)):
    """Inventory of every storage-backed chunk that is SAFE TO DELETE per
    the app's own bookkeeping. Categorized by reason so the user (or
    Emergent staff doing a manual purge) can choose which buckets to
    actually wipe.

    Categories returned:
      - dismissed_sessions: chunked_uploads with `dismissed_at` set
      - abandoned_uploads: chunked_uploads stuck in_progress/initialized for
        >6h with no dismiss (pod restart killed the client mid-upload but the
        chunks landed; user never came back). iter95 — most common leak path
        in production.
      - completed_uploads_without_video: chunked_uploads with status=completed
        whose video record was never created or has been hard-deleted from
        videos collection. Pure orphan: the upload finalized but nothing
        consumes it. iter95.
      - failed_videos: videos with processing_status=failed (kept around for
        recovery via iter88 endpoint, but storage chunks are reclaimable
        once the user has either re-uploaded or formally given up)
      - stuck_videos: videos in processing_status pending/processing for >2h
        (ffmpeg OOM-killed the pod before the failure state could be written).
        iter95.
      - deleted_videos: videos with is_deleted=true
      - lost_chunks: chunks where chunk_backends[i] == "lost"

    Admin-only (any authenticated user can run this for their OWN data —
    matches the iter85 dismiss pattern). Returns chunk PATHS, not file
    bytes — Emergent's storage staff can run the equivalent of
    `for path in paths: storage.delete(path)` on the backend.
    """
    uid = current_user["id"]
    buckets, total_chunks, total_bytes = await _collect_all_orphan_buckets(uid, capture_paths=True)

    return {
        "user_id": uid,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_orphan_chunks": total_chunks,
            "total_estimated_bytes": total_bytes,
            "total_estimated_gb": round(total_bytes / (1024 ** 3), 2),
            "by_bucket": {k: len(v) for k, v in buckets.items()},
        },
        "buckets": buckets,
        "instructions": (
            "Emergent Object Storage's public API does NOT expose a DELETE method "
            "(Allow: PUT, GET, HEAD as of 2026-05-24). To reclaim this storage, "
            "email support@emergent.sh with subject "
            "'Manual purge requested — orphan chunks from failed/dismissed uploads' "
            "and attach this report. They can purge the listed paths server-side."
        ),
    }


# iter95 — abandonment thresholds for the orphan-bucket detector.
# An upload that hasn't been touched in 6+ hours is realistically never coming
# back; a video stuck in "processing" for 2+ hours has been OOM-killed mid-job
# (typical ffmpeg pass on this app finishes well under 30 min).
_ABANDONED_UPLOAD_THRESHOLD_HOURS = 6
_STUCK_VIDEO_THRESHOLD_HOURS = 2

# All bucket keys the report/snapshot/mark-orphans endpoints share.
_ORPHAN_BUCKET_KEYS = [
    "dismissed_sessions",
    "abandoned_uploads",
    "completed_uploads_without_video",
    "failed_videos",
    "stuck_videos",
    "deleted_videos",
    "lost_chunks",
]


async def _collect_all_orphan_buckets(uid: str, capture_paths: bool):
    """Single source of truth for the orphan-bucket logic.

    When `capture_paths=True` returns (buckets_dict_of_lists, total_chunks,
    total_bytes) — used by the report endpoint that needs per-path detail.
    When `capture_paths=False` returns (buckets_dict_of_int_counts,
    total_chunks, total_bytes) — used by the weekly audit snapshot.
    """
    if capture_paths:
        buckets = {k: [] for k in _ORPHAN_BUCKET_KEYS}
    else:
        buckets = {k: 0 for k in _ORPHAN_BUCKET_KEYS}
    total_chunks = 0
    total_bytes = 0

    def _collect(doc: dict, bucket_key: str):
        nonlocal total_chunks, total_bytes
        cp = doc.get("chunk_paths") or {}
        cb = doc.get("chunk_backends") or {}
        sizes = doc.get("chunk_sizes", {})
        for idx_str, path in cp.items():
            if cb.get(idx_str) != "storage":
                continue
            size_est = sizes.get(idx_str) or 10 * 1024 * 1024
            if capture_paths:
                buckets[bucket_key].append({"path": path, "size_estimate": size_est, "bucket": bucket_key})
            else:
                buckets[bucket_key] += 1
            total_chunks += 1
            total_bytes += size_est

    now = datetime.now(timezone.utc)
    abandon_cutoff = (now - timedelta(hours=_ABANDONED_UPLOAD_THRESHOLD_HOURS)).isoformat()
    stuck_cutoff = (now - timedelta(hours=_STUCK_VIDEO_THRESHOLD_HOURS)).isoformat()

    # 1. Dismissed chunked_uploads (user explicitly waved off)
    async for s in db.chunked_uploads.find(
        {"user_id": uid, "dismissed_at": {"$exists": True}},
        {"_id": 0, "chunk_paths": 1, "chunk_backends": 1, "chunk_sizes": 1},
    ):
        _collect(s, "dismissed_sessions")

    # 2. iter95 — abandoned in-progress chunked_uploads (no dismiss, no completion, stale)
    async for s in db.chunked_uploads.find(
        {
            "user_id": uid,
            "status": {"$in": ["in_progress", "initialized", "uploading"]},
            "dismissed_at": {"$exists": False},
            "created_at": {"$lt": abandon_cutoff},
        },
        {"_id": 0, "chunk_paths": 1, "chunk_backends": 1, "chunk_sizes": 1},
    ):
        _collect(s, "abandoned_uploads")

    # 3. iter95 — completed chunked_uploads with no matching live video record
    # Gather completed upload sessions then check whether the video they
    # finalized into still exists (or was hard-deleted).
    completed_sessions = []
    async for s in db.chunked_uploads.find(
        {"user_id": uid, "status": "completed"},
        {"_id": 0, "chunk_paths": 1, "chunk_backends": 1, "chunk_sizes": 1, "video_id": 1},
    ):
        completed_sessions.append(s)
    if completed_sessions:
        vid_ids = [s.get("video_id") for s in completed_sessions if s.get("video_id")]
        existing_vids = set()
        if vid_ids:
            async for v in db.videos.find(
                {"id": {"$in": vid_ids}}, {"_id": 0, "id": 1}
            ):
                existing_vids.add(v["id"])
        for s in completed_sessions:
            if s.get("video_id") and s["video_id"] not in existing_vids:
                _collect(s, "completed_uploads_without_video")

    # 4. Failed videos — split between alive (recoverable) and is_deleted
    async for v in db.videos.find(
        {"user_id": uid, "processing_status": "failed"},
        {"_id": 0, "chunk_paths": 1, "chunk_backends": 1, "chunk_sizes": 1, "is_deleted": 1},
    ):
        _collect(v, "deleted_videos" if v.get("is_deleted") else "failed_videos")

    # 5. iter95 — stuck videos (ffmpeg OOM'd the pod before failure could write)
    async for v in db.videos.find(
        {
            "user_id": uid,
            "processing_status": {"$in": ["pending", "processing"]},
            "created_at": {"$lt": stuck_cutoff},
            "is_deleted": {"$ne": True},
        },
        {"_id": 0, "chunk_paths": 1, "chunk_backends": 1, "chunk_sizes": 1},
    ):
        _collect(v, "stuck_videos")

    # 6. "lost" chunk tags from iter88 — these point at nothing (file was
    # already gone) but the storage path might still exist from before the
    # loss event.
    async for v in db.videos.find(
        {"user_id": uid, "chunk_backends": {"$exists": True}},
        {"_id": 0, "chunk_paths": 1, "chunk_backends": 1, "chunk_sizes": 1},
    ):
        cp = v.get("chunk_paths") or {}
        cb = v.get("chunk_backends") or {}
        for idx_str, backend in cb.items():
            if backend == "lost" and cp.get(idx_str):
                if capture_paths:
                    buckets["lost_chunks"].append(
                        {"path": cp[idx_str], "size_estimate": 10 * 1024 * 1024, "bucket": "lost_chunks"}
                    )
                else:
                    buckets["lost_chunks"] += 1
                total_chunks += 1
                total_bytes += 10 * 1024 * 1024

    return buckets, total_chunks, total_bytes


# ============================================================================
# iter94 — Proactive leak prevention
# Storage cleanup UI + orphan-path persistence so when Emergent ships DELETE
# we can sweep instantly. Plus a weekly storage-growth audit so the user can
# see trends without re-running the full report.
# ============================================================================

@api_router.post("/admin/storage-cleanup/mark-orphans")
async def storage_cleanup_mark_orphans(current_user: dict = Depends(get_current_user)):
    """Materialize the current orphan-chunk inventory into the `orphan_chunks`
    collection so we have an immutable ledger of paths that are SAFE TO DELETE
    once Emergent ships a DELETE API.

    Idempotent: re-runs `upsert` keyed on (user_id, path). The `marked_at`
    field is set on first insert and never changes; `last_seen_at` updates
    every run so we can tell which orphans are still around.

    Returns counts: `{newly_marked, refreshed, total_marked_now}`.
    """
    uid = current_user["id"]
    now_iso = datetime.now(timezone.utc).isoformat()

    buckets, _, _ = await _collect_all_orphan_buckets(uid, capture_paths=True)
    paths_seen: list[dict] = []
    for bucket_key, entries in buckets.items():
        for e in entries:
            paths_seen.append({"path": e["path"], "bucket": bucket_key, "size_estimate": e["size_estimate"]})

    newly_marked = 0
    refreshed = 0
    for entry in paths_seen:
        res = await db.orphan_chunks.update_one(
            {"user_id": uid, "path": entry["path"]},
            {
                "$setOnInsert": {
                    "id": str(uuid.uuid4()),
                    "user_id": uid,
                    "path": entry["path"],
                    "size_estimate": entry["size_estimate"],
                    "marked_at": now_iso,
                    "purged_at": None,
                },
                "$set": {"last_seen_at": now_iso, "bucket": entry["bucket"]},
            },
            upsert=True,
        )
        if res.upserted_id is not None:
            newly_marked += 1
        else:
            refreshed += 1

    total = await db.orphan_chunks.count_documents({"user_id": uid, "purged_at": None})
    logger.info(
        f"[storage-cleanup] user={uid} marked {newly_marked} new orphan paths "
        f"({refreshed} already tracked, {total} total awaiting purge)"
    )
    return {
        "newly_marked": newly_marked,
        "refreshed": refreshed,
        "total_marked_now": total,
        "generated_at": now_iso,
    }


@api_router.get("/admin/storage-cleanup/audit-history")
async def storage_cleanup_audit_history(
    days: int = 90,
    current_user: dict = Depends(get_current_user),
):
    """Return the user's weekly storage-growth audits for the last N days.

    Each entry: `{recorded_at, total_orphan_chunks, total_estimated_gb, by_bucket{}}`.
    Powers a sparkline / trend chart in the admin UI so the user can see
    whether orphan accumulation is still growing post-fix.
    """
    days = max(7, min(365, days))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    audits = await db.storage_growth_audits.find(
        {"user_id": current_user["id"], "recorded_at": {"$gte": cutoff}},
        {"_id": 0},
    ).sort("recorded_at", 1).to_list(length=500)
    return {"days": days, "audits": audits}


# Weekly storage-growth audit — runs as a startup background task.
STORAGE_AUDIT_INTERVAL_SECS = 7 * 24 * 3600  # weekly
STORAGE_AUDIT_STARTUP_STAGGER_SECS = 600  # 10min after boot


async def _storage_growth_audit_loop():
    """Once a week, snapshot every active user's orphan-chunk totals into
    `storage_growth_audits` so the admin UI can render a trend line.

    Cheap: one aggregate per user; no scan of chunk bytes themselves.
    Startup stagger so a fresh boot doesn't fire immediately."""
    await asyncio.sleep(STORAGE_AUDIT_STARTUP_STAGGER_SECS)
    while True:
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            # Active users = anyone who has touched chunked_uploads or videos
            # in the last 90 days. Tight bound so we don't audit dormant accts.
            users_with_data = set()
            cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
            async for u in db.chunked_uploads.find(
                {"created_at": {"$gte": cutoff}}, {"_id": 0, "user_id": 1}
            ):
                if u.get("user_id"):
                    users_with_data.add(u["user_id"])
            async for v in db.videos.find(
                {"created_at": {"$gte": cutoff}}, {"_id": 0, "user_id": 1}
            ):
                if v.get("user_id"):
                    users_with_data.add(v["user_id"])

            audited = 0
            for uid in users_with_data:
                snapshot = await _compute_orphan_snapshot(uid)
                await db.storage_growth_audits.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": uid,
                    "recorded_at": now_iso,
                    "total_orphan_chunks": snapshot["total_chunks"],
                    "total_estimated_bytes": snapshot["total_bytes"],
                    "total_estimated_gb": round(snapshot["total_bytes"] / (1024 ** 3), 2),
                    "by_bucket": snapshot["by_bucket"],
                })
                audited += 1
                # iter96 — fire a digest email if growth crossed the threshold
                try:
                    await _maybe_send_storage_digest(uid, snapshot, now_iso)
                except Exception as digest_err:
                    logger.exception(f"[storage-audit] digest send failed for {uid}: {digest_err}")
            if audited:
                logger.info(f"[storage-audit] weekly snapshot recorded for {audited} active users")
        except Exception as e:
            logger.exception(f"[storage-audit] tick failed (will retry next week): {e}")
        await asyncio.sleep(STORAGE_AUDIT_INTERVAL_SECS)


async def _compute_orphan_snapshot(uid: str) -> dict:
    """Lightweight version of the report endpoint — returns just counts +
    bytes per bucket. Used by the weekly audit loop."""
    by_bucket, total_chunks, total_bytes = await _collect_all_orphan_buckets(uid, capture_paths=False)
    return {
        "total_chunks": total_chunks,
        "total_bytes": total_bytes,
        "by_bucket": by_bucket,
    }


# iter96 — Weekly storage-growth digest email
# When orphan storage grows >= 1 GB between snapshots, fire a Resend email
# pointing the user at /admin/storage-cleanup so they can act before the
# quota gets eaten silently. Opt-out via users.storage_digest_opt_out=true.
STORAGE_DIGEST_THRESHOLD_GB = 1.0


_BUCKET_HUMAN_LABELS = {
    "dismissed_sessions": "Dismissed paused uploads",
    "abandoned_uploads": "Abandoned in-progress uploads",
    "completed_uploads_without_video": "Completed uploads with no video record",
    "failed_videos": "Failed videos",
    "stuck_videos": "Stuck videos (ffmpeg OOM-killed)",
    "deleted_videos": "Deleted videos",
    "lost_chunks": "Lost chunks",
}


async def _maybe_send_storage_digest(uid: str, snapshot: dict, now_iso: str) -> Optional[dict]:
    """Send a digest if storage grew >= threshold since last snapshot.

    Rules:
      - User must have an email on file (skip silently if not).
      - User must not have `storage_digest_opt_out=True`.
      - Current orphan storage must be >= threshold (no point alerting on
        100 MB of fluff).
      - Either no prior snapshot (first send), OR delta_gb >= threshold.

    Returns the send-result dict or None if skipped.
    """
    user = await db.users.find_one(
        {"id": uid}, {"_id": 0, "email": 1, "name": 1, "storage_digest_opt_out": 1}
    )
    if not user or not user.get("email"):
        return None
    if user.get("storage_digest_opt_out") is True:
        return None

    current_gb = round(snapshot["total_bytes"] / (1024 ** 3), 2)
    if current_gb < STORAGE_DIGEST_THRESHOLD_GB:
        return None

    # Most recent prior snapshot (the one we just inserted is at `now_iso`)
    prior = await db.storage_growth_audits.find_one(
        {"user_id": uid, "recorded_at": {"$lt": now_iso}},
        {"_id": 0, "total_estimated_gb": 1, "recorded_at": 1},
        sort=[("recorded_at", -1)],
    )
    prior_gb = (prior or {}).get("total_estimated_gb", 0.0)
    delta_gb = round(current_gb - prior_gb, 2)

    is_first_send = prior is None
    if not is_first_send and delta_gb < STORAGE_DIGEST_THRESHOLD_GB:
        # No meaningful growth → skip
        return None

    # Build email
    from services.email_queue import send_or_queue
    base_url = (os.environ.get("PUBLIC_APP_URL")
                or os.environ.get("REACT_APP_BACKEND_URL", "")).rstrip("/")
    cleanup_link = f"{base_url}/admin/storage-cleanup" if base_url else "/admin/storage-cleanup"

    top_buckets = sorted(
        snapshot["by_bucket"].items(), key=lambda kv: kv[1], reverse=True
    )[:3]
    top_buckets = [(k, v) for k, v in top_buckets if v > 0]
    bucket_rows = "".join(
        f'<tr><td style="padding:6px 12px;color:#A3A3A3;">{_BUCKET_HUMAN_LABELS.get(k, k)}</td>'
        f'<td style="padding:6px 12px;text-align:right;color:#FBBF24;font-weight:bold;">{v} chunks</td></tr>'
        for k, v in top_buckets
    ) or '<tr><td colspan="2" style="padding:6px 12px;color:#666;">—</td></tr>'

    delta_label = "First measurement" if is_first_send else f"+{delta_gb} GB this week"
    headline = (
        f"Your Soccer Scout storage has accumulated <strong>~{current_gb} GB</strong> of "
        f"reclaimable orphan chunks ({snapshot['total_chunks']:,} chunks total)."
    )

    coach_name = user.get("name") or "there"
    html = f"""<html><body style="margin:0;padding:24px;background:#0A0A0A;color:#E5E5E5;font-family:Inter,sans-serif;">
  <table style="max-width:600px;margin:0 auto;width:100%;border-collapse:collapse;background:#141414;border:1px solid #222;">
    <tr><td style="padding:24px;">
      <p style="margin:0 0 12px;font-size:11px;letter-spacing:0.25em;color:#FBBF24;text-transform:uppercase;font-weight:bold;">
        Storage Quota Alert
      </p>
      <h1 style="margin:0 0 16px;font-size:22px;font-weight:bold;color:#FFFFFF;">
        Hi {coach_name},
      </h1>
      <p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:#E5E5E5;">
        {headline}
      </p>
      <table style="width:100%;background:#0A0A0A;border:1px solid #222;margin-bottom:20px;">
        <tr><td style="padding:12px;border-bottom:1px solid #222;">
          <p style="margin:0 0 4px;font-size:10px;letter-spacing:0.2em;text-transform:uppercase;color:#666;">Growth</p>
          <p style="margin:0;font-size:24px;font-weight:bold;color:#FBBF24;">{delta_label}</p>
        </td></tr>
        <tr><td style="padding:0;">
          <table style="width:100%;font-size:13px;">
            <tr><th style="padding:8px 12px;text-align:left;color:#666;font-weight:normal;text-transform:uppercase;font-size:10px;letter-spacing:0.2em;">Top sources</th>
                <th style="padding:8px 12px;text-align:right;color:#666;font-weight:normal;"></th></tr>
            {bucket_rows}
          </table>
        </td></tr>
      </table>
      <p style="margin:0 0 16px;font-size:13px;color:#A3A3A3;line-height:1.6;">
        These chunks come from uploads that failed, were dismissed, or got pod-killed mid-finalize.
        Because Emergent's object storage API exposes no DELETE endpoint, the app can't reclaim
        them — you'll need to email support to free the quota.
      </p>
      <p style="margin:0 0 24px;text-align:center;">
        <a href="{cleanup_link}"
           style="display:inline-block;background:#FBBF24;color:#000;padding:14px 28px;
                  font-weight:bold;text-decoration:none;font-size:14px;">
          OPEN STORAGE CLEANUP →
        </a>
      </p>
      <p style="margin:0;padding-top:20px;border-top:1px solid #222;font-size:11px;color:#666;line-height:1.5;">
        Don't want these alerts? Toggle "Weekly storage digest" off on
        <a href="{cleanup_link}" style="color:#7DD3FC;">the Storage Cleanup page</a>.
        We only send when growth crosses {STORAGE_DIGEST_THRESHOLD_GB} GB so you won't get noise.
      </p>
    </td></tr>
  </table>
</body></html>"""

    subject = f"Storage Quota Alert: {delta_label}"
    result = await send_or_queue(
        to_email=user["email"],
        subject=subject,
        html=html,
        kind="storage_growth_digest",
        metadata={
            "user_id": uid,
            "current_gb": current_gb,
            "delta_gb": delta_gb,
            "is_first_send": is_first_send,
            "total_chunks": snapshot["total_chunks"],
        },
    )

    # Stamp the snapshot so the admin UI can show "Last digest sent" status
    await db.storage_growth_audits.update_one(
        {"user_id": uid, "recorded_at": now_iso},
        {"$set": {"digest_sent_at": now_iso, "digest_status": result.get("status")}},
    )
    return result


@api_router.post("/admin/storage-cleanup/send-digest-now")
async def storage_cleanup_send_digest_now(current_user: dict = Depends(get_current_user)):
    """Manual one-shot trigger — useful for verifying the email pipeline
    without waiting a week for the audit loop."""
    uid = current_user["id"]
    snapshot = await _compute_orphan_snapshot(uid)
    # Pretend this is the most recent snapshot so _maybe_send_storage_digest
    # computes delta against the prior real one.
    now_iso = datetime.now(timezone.utc).isoformat()
    await db.storage_growth_audits.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": uid,
        "recorded_at": now_iso,
        "total_orphan_chunks": snapshot["total_chunks"],
        "total_estimated_bytes": snapshot["total_bytes"],
        "total_estimated_gb": round(snapshot["total_bytes"] / (1024 ** 3), 2),
        "by_bucket": snapshot["by_bucket"],
        "triggered_manually": True,
    })
    result = await _maybe_send_storage_digest(uid, snapshot, now_iso)
    if result is None:
        return {
            "status": "skipped",
            "reason": (
                f"No meaningful growth (current: {round(snapshot['total_bytes'] / (1024 ** 3), 2)} GB, "
                f"threshold: {STORAGE_DIGEST_THRESHOLD_GB} GB) or user opted out / no email on file."
            ),
        }
    return {"status": result.get("status"), "queue_id": result.get("queue_id")}


@api_router.post("/me/preferences/storage-digest")
async def set_storage_digest_preference(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """Opt out of (or back in to) the weekly storage-growth digest email."""
    opt_out = bool(body.get("opt_out", False))
    await db.users.update_one(
        {"id": current_user["id"]},
        {"$set": {"storage_digest_opt_out": opt_out}},
    )
    return {"opt_out": opt_out}


@api_router.get("/me/preferences/storage-digest")
async def get_storage_digest_preference(current_user: dict = Depends(get_current_user)):
    user = await db.users.find_one(
        {"id": current_user["id"]}, {"_id": 0, "storage_digest_opt_out": 1}
    )
    return {"opt_out": bool((user or {}).get("storage_digest_opt_out", False))}


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

# Disk-pressure circuit breaker — refuses new uploads when /var/video_chunks is
# >80% full so we don't trip the ephemeral-storage eviction that's been killing
# the pod. Returns HTTP 503 with a Retry-After hint so the frontend can surface
# a clear "system is full, try again in a few minutes" message instead of the
# upload silently hanging then erroring partway through.
DISK_FULL_THRESHOLD_PCT = 95
DISK_FULL_RESERVE_BYTES = 2 * 1024 ** 3  # also block if <2GB free regardless of pct


def _check_disk_pressure(incoming_bytes: int = 0):
    """Raise HTTPException(503) if the chunk storage volume is under pressure.

    Two triggers:
      1) Used % >= DISK_FULL_THRESHOLD_PCT (default 95%)
      2) Free bytes after this upload would drop below DISK_FULL_RESERVE_BYTES (2GB)

    The 2GB absolute floor is the real safeguard — it's what protects the pod
    from eviction. The percentage gate is intentionally high (95%) because in
    Kubernetes the chunk dir shares a volume with system files / package caches
    / node_modules etc, so baseline usage routinely sits at 70-85% even with
    zero user videos. Triggering on raw percentage caused a false-positive
    "Heavy server load" banner on production with 73GB still free."""
    try:
        import shutil as _shutil
        total, used, free = _shutil.disk_usage(CHUNK_STORAGE_DIR)
    except OSError:
        return  # fail-open if disk_usage itself fails — we don't want to block uploads on a stat error

    pct = (used / total) * 100 if total > 0 else 0
    projected_free = free - max(0, incoming_bytes)

    if pct >= DISK_FULL_THRESHOLD_PCT or projected_free < DISK_FULL_RESERVE_BYTES:
        logger.warning(
            f"[disk-pressure] BLOCKING upload — used={used/(1024**3):.1f}G / "
            f"{total/(1024**3):.1f}G ({pct:.0f}%), free={free/(1024**3):.1f}G, "
            f"incoming={incoming_bytes/(1024**3):.2f}G, threshold={DISK_FULL_THRESHOLD_PCT}%"
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Our servers are under heavy load processing other matches right now. "
                "Please try uploading again in a few minutes — your file will resume from "
                "wherever it stopped if you've already started."
            ),
            headers={"Retry-After": "300"},  # 5 minutes
        )


@api_router.post("/videos/upload")
async def upload_video(file: UploadFile = File(...), match_id: str = "", current_user: dict = Depends(get_current_user)):
    if not match_id:
        raise HTTPException(status_code=400, detail="match_id is required")
    _check_disk_pressure()
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

    # Disk circuit breaker — refuse upfront so a coach with a 15 GB file isn't
    # 7 GB into an upload when the disk fills up.
    _check_disk_pressure(incoming_bytes=input.file_size or 0)

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


@api_router.get("/matches/{match_id}/pending-uploads")
async def list_pending_uploads(match_id: str, current_user: dict = Depends(get_current_user)):
    """Return any incomplete chunked-upload sessions for a given match so the
    match-page UI can show a "Resume incomplete upload" banner.

    A coach with a flaky home connection can lose half their upload, close
    the tab, and come back the next day without realizing they can pick the
    same file and resume from where they left off. This endpoint feeds a
    banner on the match page that surfaces that recovery path.

    Filters to in-progress / failed / initialized sessions only — sessions
    that completed don't belong here (the resulting video doc handles its
    own state).
    """
    cursor = db.chunked_uploads.find({
        "match_id": match_id,
        "user_id": current_user["id"],
        "status": {"$in": ["initialized", "in_progress", "failed"]},
    }, {"_id": 0}).sort("created_at", -1).limit(5)
    sessions = await cursor.to_list(5)
    out = []
    for s in sessions:
        chunk_paths = s.get("chunk_paths", {})
        uploaded = len(chunk_paths)
        file_size = s.get("file_size", 0)
        chunk_size = s.get("chunk_size", CHUNK_SIZE)
        total = max(1, -(-file_size // chunk_size))  # ceil
        out.append({
            "upload_id": s.get("upload_id"),
            "video_id": s.get("video_id"),
            "filename": s.get("filename"),
            "file_size": file_size,
            "file_size_gb": round(file_size / (1024 ** 3), 2),
            "chunks_received": uploaded,
            "total_chunks": total,
            "progress_pct": round((uploaded / total) * 100, 1) if total else 0,
            "status": s.get("status"),
            "created_at": s.get("created_at"),
            "last_chunk_at": s.get("last_chunk_at"),
        })
    return {"count": len(out), "sessions": out}


@api_router.get("/me/pending-uploads")
async def list_my_pending_uploads(current_user: dict = Depends(get_current_user)):
    """iter84 — Resume Across Devices.

    Return every in-flight chunked upload owned by `current_user`, across
    all matches. Powers a dashboard banner so a coach who starts an upload
    on one device (e.g. laptop at the field) can see + jump back to it from
    a different device (e.g. phone on the drive home) without first having
    to remember which match they were uploading to.

    The actual resume still requires re-picking the same file on the new
    device — chunks already on the server are durable post-iter83. The
    init endpoint matches on (user_id, match_id, filename, file_size) so a
    file with the same name+size on any device resolves to the same
    session.

    Results are joined with the `matches` collection so the UI can show
    a human-readable "Home vs Away" label per pending upload."""
    cursor = db.chunked_uploads.find({
        "user_id": current_user["id"],
        "status": {"$in": ["initialized", "in_progress", "failed"]},
        # iter85 — dismiss button: hide sessions the user explicitly waved off.
        # The dismissed status keeps the row in Mongo for audit/forensics
        # without cluttering the dashboard banner.
        "dismissed_at": {"$exists": False},
    }, {"_id": 0}).sort("created_at", -1).limit(20)
    sessions = await cursor.to_list(20)
    if not sessions:
        return {"count": 0, "sessions": []}

    # Batch-fetch the match docs to avoid N+1 — coaches with 10+ pending
    # uploads (e.g. after a long flaky-wifi weekend) shouldn't slow the
    # dashboard to a crawl.
    match_ids = list({s.get("match_id") for s in sessions if s.get("match_id")})
    matches = await db.matches.find(
        {"id": {"$in": match_ids}, "user_id": current_user["id"]},
        {"_id": 0, "id": 1, "team_home": 1, "team_away": 1, "date": 1},
    ).to_list(len(match_ids))
    match_by_id = {m["id"]: m for m in matches}

    out = []
    for s in sessions:
        chunk_paths = s.get("chunk_paths", {})
        uploaded = len(chunk_paths)
        file_size = s.get("file_size", 0)
        chunk_size = s.get("chunk_size", CHUNK_SIZE)
        total = max(1, -(-file_size // chunk_size))
        m = match_by_id.get(s.get("match_id")) or {}
        match_label = (
            f"{m.get('team_home', '')} vs {m.get('team_away', '')}".strip(" vs")
            or "Match"
        )
        out.append({
            "upload_id": s.get("upload_id"),
            "video_id": s.get("video_id"),
            "match_id": s.get("match_id"),
            "match_label": match_label,
            "match_date": m.get("date"),
            "filename": s.get("filename"),
            "file_size": file_size,
            "file_size_gb": round(file_size / (1024 ** 3), 2),
            "chunks_received": uploaded,
            "total_chunks": total,
            "progress_pct": round((uploaded / total) * 100, 1) if total else 0,
            "status": s.get("status"),
            "last_chunk_at": s.get("last_chunk_at"),
        })
    return {"count": len(out), "sessions": out}


@api_router.delete("/me/pending-uploads/{upload_id}")
async def dismiss_my_pending_upload(upload_id: str, current_user: dict = Depends(get_current_user)):
    """iter85 — Dismiss button on resume banner.

    A coach who has 14 stale "0/85 chunks (0%)" sessions from a flaky-wifi
    weekend doesn't want them cluttering the dashboard forever. This endpoint
    marks ONE session as dismissed so it disappears from
    `/api/me/pending-uploads`, and best-effort deletes any persistent
    fallback chunks on `/app/.video_chunks` so disk doesn't grow unbounded.

    We intentionally DO NOT hard-delete the chunked_uploads row — the
    `dismissed_at` timestamp keeps the audit trail (when, why, how far it
    got) in case the user later wants to know "what happened to that game
    last weekend?". Mongo TTL or a future sweeper can hard-purge after a
    grace period if storage pressure forces it.
    """
    session = await db.chunked_uploads.find_one(
        {"upload_id": upload_id, "user_id": current_user["id"]},
        {"_id": 0},
    )
    if not session:
        # Idempotent: dismissing a session that doesn't exist (or that some
        # other tab already dismissed) is a no-op success rather than a 404.
        return {"upload_id": upload_id, "dismissed": True, "already": True}
    if session.get("dismissed_at"):
        return {"upload_id": upload_id, "dismissed": True, "already": True}

    # Best-effort: free up any persistent_filesystem chunks on /app so the
    # next upload doesn't run out of disk. Object-storage chunks are cheap
    # so we leave those to natural lifecycle cleanup.
    chunk_paths = session.get("chunk_paths", {})
    chunk_backends = session.get("chunk_backends", {})
    freed_files = 0
    for idx_str, backend_name in chunk_backends.items():
        if backend_name not in ("filesystem", "persistent_filesystem"):
            continue
        local_path = chunk_paths.get(idx_str)
        if not local_path:
            continue
        try:
            if os.path.exists(local_path):
                os.remove(local_path)
                freed_files += 1
        except OSError as e:
            logger.warning(f"dismiss: could not delete {local_path}: {e}")

    # Best-effort: clean up the now-empty per-video chunk directory too.
    video_id = session.get("video_id")
    if video_id:
        for parent_dir in (PERSISTENT_CHUNK_DIR, CHUNK_STORAGE_DIR):
            video_dir = os.path.join(parent_dir, video_id)
            try:
                if os.path.isdir(video_dir) and not os.listdir(video_dir):
                    os.rmdir(video_dir)
            except OSError:
                pass

    await db.chunked_uploads.update_one(
        {"upload_id": upload_id},
        {"$set": {
            "dismissed_at": datetime.now(timezone.utc).isoformat(),
            "dismissed_freed_chunk_files": freed_files,
        }},
    )
    logger.info(f"dismiss: upload_id={upload_id} dismissed by user={current_user['id']}, freed {freed_files} local chunk files")
    return {"upload_id": upload_id, "dismissed": True, "freed_chunk_files": freed_files}


# ===== iter86 — In-app notifications across devices =====
#
# Web Push (services/push_notifications.py) only fires on devices that
# subscribed AND granted permission. Many coaches don't bother. This
# endpoint powers a polling fallback: every authenticated tab pulls recent
# notifications and shows them locally (showLocalNotification + sonner
# toast), so a coach who's actively using the app on Device B gets a
# visible signal the moment Device A finishes processing — without any
# push permission required.


@api_router.get("/me/notifications/recent")
async def list_my_recent_notifications(
    since: str = "",
    current_user: dict = Depends(get_current_user),
):
    """Return notifications for the current user created after `since` (ISO
    timestamp). If `since` is empty or unparseable, defaults to 24h ago.
    Capped at 20 records so a long-idle client doesn't drown the poller.

    Per-device "already seen" filtering happens client-side in
    localStorage — the server doesn't track which device saw what (a coach
    using both laptop and phone simultaneously WANTS both to ping)."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    if since:
        try:
            parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
            # Use whichever is more recent — protects against a client sending
            # an ancient timestamp that would return ~unbounded results.
            cutoff = max(cutoff, parsed)
        except ValueError:
            pass

    cursor = db.user_notifications.find(
        {"user_id": current_user["id"], "created_at": {"$gte": cutoff.isoformat()}},
        {"_id": 0},
    ).sort("created_at", -1).limit(20)
    notifs = await cursor.to_list(20)
    return {"count": len(notifs), "notifications": notifs}


@api_router.post("/videos/upload/chunk")
async def upload_chunk(
    upload_id: str = "",
    chunk_index: int = 0,
    total_chunks: int = 0,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """Upload a single chunk directly to object storage (non-blocking, with retry)"""
    # Hard floor — abort in-progress uploads only if disk has <500MB free (about
    # to crash the pod). The 80% / 2GB pre-upload check in init_chunked_upload
    # already gates new sessions; this is the last line of defense for sessions
    # that started before disk pressure spiked.
    try:
        import shutil as _shutil
        _, _, free = _shutil.disk_usage(CHUNK_STORAGE_DIR)
        if free < 500 * 1024 * 1024:  # <500MB free → abort to save the pod
            logger.error(f"[disk-pressure] aborting chunk upload — only {free/(1024**2):.0f}MB free")
            raise HTTPException(
                status_code=503,
                detail="Disk is full. Upload paused — try resuming in a few minutes once we clear processing backlog.",
                headers={"Retry-After": "300"},
            )
    except (OSError, NameError):
        pass

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
        # iter83: store_chunk returns one of {"storage", "persistent_filesystem"}.
        # Both are safe to commit — persistent_filesystem lives on /app (PV
        # backed), so it survives pod restarts and gets migrated to object
        # storage by the background task in services/storage.py. The only
        # error path that surfaces is RuntimeError("persistent_storage_full"),
        # which we translate to 503 + Retry-After so the iter79 client retry
        # loop backs off until disk frees up.
        try:
            store_result = await store_chunk(video_id, upload["user_id"], chunk_index, chunk_data)
        except RuntimeError as rerr:
            reason = str(rerr)
            logger.warning(f"Chunk {chunk_index+1}/{total_chunks} rejected: {reason}")
            # iter89: when persistent_filesystem fallback is disabled, the
            # only 5xx path is "object storage temporarily unavailable" —
            # bump Retry-After higher so the iter82 client-side 20-retry
            # budget doesn't burn through cycles before storage actually
            # comes back. 60s vs 30s.
            retry_after = "60" if "fallback_disabled" in reason else "30"
            raise HTTPException(
                status_code=503,
                detail="Storage temporarily unavailable. Retry the chunk.",
                headers={"Retry-After": retry_after},
            )
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

    except HTTPException:
        # Don't swallow our own 503 retry-trigger inside the broad except below
        raise
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

    # Auto-start processing only when a roster is already attached. Coaches
    # repeatedly flagged that AI runs without player context produce vague
    # attributions ("midfielder #7" rather than "Reyes #7") — so iter61 gates
    # the queue on roster presence. The video page shows an "Awaiting roster"
    # banner with both "Add roster" and "Run anyway" CTAs.
    roster_count = await db.players.count_documents({
        "match_id": upload["match_id"], "user_id": upload["user_id"]
    })
    if roster_count > 0:
        await db.videos.update_one(
            {"id": upload["video_id"]},
            {"$set": {"processing_status": "queued", "processing_started_at": datetime.now(timezone.utc).isoformat()}}
        )
        asyncio.create_task(run_auto_processing(upload["video_id"], upload["user_id"]))
        logger.info(f"Auto-processing queued for video {upload['video_id']} (roster={roster_count} players)")
        processing_state = "queued"
    else:
        await db.videos.update_one(
            {"id": upload["video_id"]},
            {"$set": {"processing_status": "awaiting_roster", "processing_progress": 0}}
        )
        logger.info(f"Video {upload['video_id']} parked in awaiting_roster — coach must add players or click Run Anyway")
        processing_state = "awaiting_roster"

    return {"status": "completed", "video_id": upload["video_id"], "size": total_size, "processing": processing_state}

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


@api_router.post("/videos/{video_id}/recover-chunks")
async def recover_chunks(video_id: str, current_user: dict = Depends(get_current_user)):
    """iter88 — Auto-Retry Migration recovery.

    For videos stuck in `processing_status=failed` with the iter87 error
    "Chunk N of M missing — re-upload required.", this endpoint:

      1. Syncs the video doc's chunk_paths/chunk_backends FROM the
         chunked_uploads collection — if migration already swapped a chunk
         to object storage there but the video doc still has a stale
         persistent_filesystem pointer, this fixes it without touching
         storage at all.
      2. Re-runs migration on every chunk still tagged
         persistent_filesystem in the video doc, using the same upload →
         swap-DB → delete-file ordering as the background loop (iter87).
      3. Re-checks integrity. If `full`, resets `processing_status` to
         `pending` and clears the error so the existing "Retry Processing"
         flow can re-run cleanly.

    Returns a summary so the UI can tell the user exactly what happened:
      - "Recovered 3 chunks from migration, your video is ready to retry."
      - "1 chunk is permanently lost (storage backed and missing). Please
         re-upload the file."
    """
    video = await db.videos.find_one(
        {"id": video_id, "user_id": current_user["id"], "is_deleted": False},
        {"_id": 0},
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    if not video.get("is_chunked"):
        raise HTTPException(
            status_code=400,
            detail="Recovery only applies to chunked uploads.",
        )

    from services.storage import _migrate_one_chunk
    from services.processing import _check_chunk_integrity
    from db import APP_NAME

    # Step 1: pull the freshest chunk_backends/chunk_paths from chunked_uploads.
    # The background migration loop updates that collection too, so if a chunk
    # migrated AFTER finalize, the up-to-date pointer lives there.
    synced = 0
    upload = await db.chunked_uploads.find_one(
        {"video_id": video_id, "user_id": current_user["id"]},
        {"_id": 0},
    )
    if upload:
        upload_backends = upload.get("chunk_backends") or {}
        upload_paths = upload.get("chunk_paths") or {}
        video_backends = video.get("chunk_backends") or {}
        video_paths = video.get("chunk_paths") or {}
        sync_set = {}
        for idx_str, backend in upload_backends.items():
            if video_backends.get(idx_str) != backend or video_paths.get(idx_str) != upload_paths.get(idx_str):
                # The chunked_uploads pointer is newer than the video doc — adopt it.
                if upload_paths.get(idx_str):
                    sync_set[f"chunk_backends.{idx_str}"] = backend
                    sync_set[f"chunk_paths.{idx_str}"] = upload_paths[idx_str]
                    synced += 1
        if sync_set:
            await db.videos.update_one({"id": video_id}, {"$set": sync_set})
            video = await db.videos.find_one({"id": video_id}, {"_id": 0})  # reload

    # Step 2: re-run migration on any chunks still marked persistent_filesystem
    # in the video doc. Same write-then-update-then-delete ordering as the
    # background loop.
    migrated = 0
    migration_failures = []
    backends = video.get("chunk_backends") or {}
    paths = video.get("chunk_paths") or {}
    for idx_str, backend in list(backends.items()):
        if backend != "persistent_filesystem":
            continue
        local_path = paths.get(idx_str)
        if not local_path:
            migration_failures.append({"chunk_index": int(idx_str), "reason": "no_local_path"})
            continue
        ok = await _migrate_one_chunk(video_id, idx_str, local_path, current_user["id"])
        if ok == "retry":
            migration_failures.append({"chunk_index": int(idx_str), "reason": "storage_still_failing"})
            continue
        if ok == "lost":
            # Mark the chunk as lost in the video doc so the integrity check
            # correctly reports it as unavailable and the user gets the right
            # "re-upload required" signal.
            try:
                await db.videos.update_one({"id": video_id}, {"$set": {
                    f"chunk_backends.{idx_str}": "lost",
                }})
            except Exception:
                pass
            migration_failures.append({"chunk_index": int(idx_str), "reason": "local_file_lost"})
            continue
        # ok == "migrated"
        new_path = f"{APP_NAME}/videos/{current_user['id']}/{video_id}_chunk_{int(idx_str):06d}.bin"
        try:
            await db.videos.update_one({"id": video_id}, {"$set": {
                f"chunk_backends.{idx_str}": "storage",
                f"chunk_paths.{idx_str}": new_path,
            }})
        except Exception as db_err:
            migration_failures.append({"chunk_index": int(idx_str), "reason": f"db_swap_failed: {db_err!r}"})
            continue
        try:
            os.remove(local_path)
        except OSError:
            pass
        migrated += 1

    # Step 3: re-check integrity and clear the failure state if we're whole again.
    video = await db.videos.find_one({"id": video_id}, {"_id": 0})  # reload final state
    integrity, available, total = await _check_chunk_integrity(video)
    ready_to_retry = integrity == "full"
    if ready_to_retry:
        await db.videos.update_one({"id": video_id}, {"$set": {
            "processing_status": "pending",
            "processing_error": None,
            "processing_progress": 0,
        }})

    return {
        "video_id": video_id,
        "synced_from_uploads": synced,
        "migrated_to_storage": migrated,
        "migration_failures": migration_failures,
        "integrity": integrity,
        "available_chunks": available,
        "total_chunks": total,
        "ready_to_retry": ready_to_retry,
    }


@api_router.post("/videos/{video_id}/start-analysis")
async def start_analysis(video_id: str, current_user: dict = Depends(get_current_user)):
    """Kick off AI analysis for a video that was uploaded but parked in
    `awaiting_roster`. Used by:
      - the "Roster added — start now" CTA (after the coach adds players)
      - the "Run anyway" override (coach explicitly doesn't want roster context)

    Idempotent: if the video is already processing/queued/completed, returns
    a hint and does nothing. Otherwise re-enters the normal processing path
    so all four analysis types run from scratch."""
    video = await db.videos.find_one(
        {"id": video_id, "user_id": current_user["id"], "is_deleted": False},
        {"_id": 0, "processing_status": 1, "match_id": 1},
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    current = video.get("processing_status")
    if current in {"queued", "processing"}:
        return {"status": "already_processing", "processing_status": current}
    if current == "completed":
        return {"status": "already_complete", "processing_status": current}

    roster_count = await db.players.count_documents({
        "match_id": video["match_id"], "user_id": current_user["id"]
    })
    await db.videos.update_one(
        {"id": video_id},
        {"$set": {
            "processing_status": "queued",
            "processing_progress": 0,
            "processing_error": None,
            "processing_started_at": datetime.now(timezone.utc).isoformat(),
        }}
    )
    asyncio.create_task(run_auto_processing(video_id, current_user["id"]))
    logger.info(f"Manual start_analysis: video {video_id} kicked off (roster={roster_count} players)")
    return {"status": "started", "roster_count": roster_count}



@api_router.post("/analysis/generate")
async def generate_analysis(input: AnalysisRequest, current_user: dict = Depends(get_current_user)):
    """iter98 — Manual single analysis generation, now ASYNC.

    Returns 202 immediately with a `pending` analysis row. The actual ffmpeg
    + Gemini work runs in a background task. The frontend polls
    `/api/analysis/video/{video_id}` and sees `status` flip pending→completed
    (or `failed`). This avoids the Cloudflare-edge 100s HTTP timeout that
    surfaced as confusing HTTP 520 errors on 1+ GB videos (real production
    bug 2026-05-27 video f0673397, 1.04 GB / 1:47:48).
    """
    video = await db.videos.find_one(
        {"id": input.video_id, "user_id": current_user["id"], "is_deleted": False},
        {"_id": 0},
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Replace any prior in-flight analysis of the same type so the frontend
    # doesn't see a stale `completed` row alongside the new `pending` one.
    await db.analyses.delete_many({
        "video_id": input.video_id, "user_id": current_user["id"],
        "analysis_type": input.analysis_type,
    })

    analysis_id = str(uuid.uuid4())
    placeholder = {
        "id": analysis_id,
        "video_id": input.video_id,
        "match_id": video["match_id"],
        "user_id": current_user["id"],
        "analysis_type": input.analysis_type,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.analyses.insert_one(dict(placeholder))

    asyncio.create_task(_run_generate_analysis(
        analysis_id=analysis_id,
        video=video,
        user_id=current_user["id"],
        analysis_type=input.analysis_type,
    ))
    return JSONResponse(
        status_code=202,
        content={"analysis_id": analysis_id, "status": "pending"},
    )


async def _run_generate_analysis(
    analysis_id: str, video: dict, user_id: str, analysis_type: str,
):
    """Background worker for `/analysis/generate`. Captures ffmpeg + Gemini
    failures on the analysis row instead of surfacing them as HTTP 520s."""
    match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})
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
            session_id=f"analysis-{video['id']}",
            system_message="You are an expert soccer analyst. You will receive video samples from multiple points throughout the match. Analyze the full match based on these samples and provide detailed tactical insights.",
        ).with_model("gemini", "gemini-3.1-pro-preview")
        video_file = FileContentWithMimeType(file_path=tmp_path, mime_type="video/mp4")
        prompts = {
            "tactical": f"Analyze this soccer match video between {match['team_home']} and {match['team_away']}. Provide detailed tactical analysis.{roster_context}",
            "player_performance": f"Analyze individual player performances in this match between {match['team_home']} and {match['team_away']}.{roster_context}",
            "highlights": f"Identify key moments and highlights from this match between {match['team_home']} and {match['team_away']}.{roster_context}",
        }
        prompt = prompts.get(analysis_type, prompts["tactical"])
        response = await chat.send_message(UserMessage(text=prompt, file_contents=[video_file]))

        await db.analyses.update_one(
            {"id": analysis_id},
            {"$set": {
                "content": response,
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        logger.info(f"[generate_analysis] analysis_id={analysis_id} completed ({analysis_type})")
    except Exception as e:
        logger.exception(f"[generate_analysis] analysis_id={analysis_id} failed: {e}")
        await db.analyses.update_one(
            {"id": analysis_id},
            {"$set": {
                "status": "failed",
                "error": str(e)[:500],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

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
    """Extract actual video segment for a clip using ffmpeg and return as streaming MP4.

    If the clip has a ready AI close-up (`close_up_status="ready"` + an
    on-disk file at `close_up_path`), we serve that pre-stitched mp4
    directly — no re-encoding needed.
    """
    import subprocess

    clip = await db.clips.find_one({"id": clip_id, "user_id": current_user["id"]}, {"_id": 0})
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    safe_title = "".join(c for c in clip["title"] if c.isalnum() or c in " -_").strip()[:50] or "clip"

    # AI close-up shortcut — pre-rendered wide+zoom stitched mp4.
    close_up_path = clip.get("close_up_path") if clip.get("close_up_status") == "ready" else None
    if close_up_path and os.path.exists(close_up_path):
        async def stream_close_up():
            with open(close_up_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    yield chunk
        return StreamingResponse(
            stream_close_up(), media_type="video/mp4",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.mp4"'},
        )

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


# ===== AI Close-up Generation =====

@api_router.post("/clips/{clip_id}/generate-close-up")
async def generate_close_up(clip_id: str, current_user: dict = Depends(get_current_user)):
    """Queue background generation of an AI close-up for this clip.

    Returns immediately; status flips to `pending` then `processing`, and
    finally `ready` (or `failed`) on the clip doc. Polling client should
    re-fetch the clip every few seconds while status is not ready/failed.
    """
    from services.close_up_processor import enqueue_close_up

    clip = await db.clips.find_one(
        {"id": clip_id, "user_id": current_user["id"]},
        {"_id": 0, "id": 1, "close_up_status": 1},
    )
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    current_status = clip.get("close_up_status")
    if current_status == "ready":
        return {"status": "ready", "already_done": True}
    if current_status in ("pending", "processing"):
        return {"status": current_status, "already_queued": True}

    await enqueue_close_up(clip_id)
    return {"status": "pending"}


@api_router.post("/clips/{clip_id}/close-up/retry")
async def retry_close_up(clip_id: str, current_user: dict = Depends(get_current_user)):
    """Force a re-queue (used after a failed close-up generation)."""
    from services.close_up_processor import enqueue_close_up

    clip = await db.clips.find_one(
        {"id": clip_id, "user_id": current_user["id"]}, {"_id": 0, "id": 1},
    )
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    await db.clips.update_one(
        {"id": clip_id},
        {"$unset": {
            "close_up_status": "", "close_up_error": "",
            "close_up_path": "", "close_up_bbox": "",
        }},
    )
    await enqueue_close_up(clip_id)
    return {"status": "pending"}


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
    """iter98 — Generate analysis on a trimmed section of video. ASYNC.

    Same async pattern as /analysis/generate — returns 202 with a placeholder
    `pending` analysis row so Cloudflare can't time out the request even on
    1+ GB sources. Frontend polls /api/analysis/video/{id}.
    """
    video = await db.videos.find_one(
        {"id": input.video_id, "user_id": current_user["id"], "is_deleted": False},
        {"_id": 0},
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    await db.analyses.delete_many({
        "video_id": input.video_id, "user_id": current_user["id"],
        "analysis_type": input.analysis_type,
    })

    analysis_id = str(uuid.uuid4())
    placeholder = {
        "id": analysis_id,
        "video_id": input.video_id,
        "match_id": video["match_id"],
        "user_id": current_user["id"],
        "analysis_type": input.analysis_type,
        "status": "pending",
        "trim_start": input.trim_start,
        "trim_end": input.trim_end,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.analyses.insert_one(dict(placeholder))

    asyncio.create_task(_run_generate_trimmed_analysis(
        analysis_id=analysis_id,
        video=video,
        user_id=current_user["id"],
        analysis_type=input.analysis_type,
        trim_start=input.trim_start,
        trim_end=input.trim_end,
    ))
    return JSONResponse(
        status_code=202,
        content={"analysis_id": analysis_id, "status": "pending"},
    )


async def _run_generate_trimmed_analysis(
    analysis_id: str, video: dict, user_id: str, analysis_type: str,
    trim_start, trim_end,
):
    """Background worker for /analysis/generate-trimmed."""
    match = await db.matches.find_one({"id": video["match_id"]}, {"_id": 0})
    roster = await db.players.find({"match_id": video["match_id"]}, {"_id": 0}).to_list(100)
    roster_context = ""
    if roster:
        roster_lines = [f"#{p.get('number', '?')} {p['name']} ({p.get('position', '')}) - {p.get('team', '')}" for p in roster]
        roster_context = "\n\nKnown Players:\n" + "\n".join(roster_lines)

    tmp_path = None
    try:
        tmp_path = await prepare_video_sample(video, trim_start=trim_start, trim_end=trim_end)

        chat = LlmChat(
            api_key=EMERGENT_KEY,
            session_id=f"trim-{video['id']}-{analysis_type}",
            system_message="You are an expert soccer analyst. Analyze the provided video segment and provide detailed insights.",
        ).with_model("gemini", "gemini-3.1-pro-preview")
        video_file = FileContentWithMimeType(file_path=tmp_path, mime_type="video/mp4")
        trim_label = ""
        if trim_start is not None or trim_end is not None:
            s = int(trim_start or 0)
            e = int(trim_end or 0)
            trim_label = f" (analyzing from {s//60}:{s%60:02d} to {e//60}:{e%60:02d})"
        prompts = {
            "tactical": f"Analyze this soccer match segment{trim_label} between {match['team_home']} and {match['team_away']}. Provide tactical analysis.{roster_context}",
            "player_performance": f"Analyze player performances in this segment{trim_label} between {match['team_home']} and {match['team_away']}.{roster_context}",
            "highlights": f"Identify key moments in this segment{trim_label} between {match['team_home']} and {match['team_away']}.{roster_context}",
        }
        prompt = prompts.get(analysis_type, prompts["tactical"])
        response = await chat.send_message(UserMessage(text=prompt, file_contents=[video_file]))

        await db.analyses.update_one(
            {"id": analysis_id},
            {"$set": {
                "content": response,
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        logger.info(f"[generate_trimmed_analysis] analysis_id={analysis_id} completed ({analysis_type})")
    except Exception as e:
        logger.exception(f"[generate_trimmed_analysis] analysis_id={analysis_id} failed: {e}")
        await db.analyses.update_one(
            {"id": analysis_id},
            {"$set": {
                "status": "failed",
                "error": str(e)[:500],
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


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
for r in (folders_router, matches_router, annotations_router, analysis_router, insights_router, season_trends_router, player_trends_router, coach_network_router, videos_router, annotation_templates_router, coach_pulse_router, push_notifications_router, voice_annotations_router, spoken_summary_router, admin_router, scouting_packets_router, password_reset_router, scout_listings_router, messaging_router, highlight_reels_router, recruiter_lens_router):
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
    goal_clip_ids: list[str] = []
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
        if clip_type == "goal":
            goal_clip_ids.append(clip["id"])
    logger.info(f"Auto-created {created} clips from AI markers for video {video_id}")

    # Auto-queue AI close-ups for every goal — coaches asked for goals to
    # always get a wide+zoom stitched version.
    if goal_clip_ids:
        try:
            from services.close_up_processor import enqueue_close_up
            for clip_id in goal_clip_ids:
                await enqueue_close_up(clip_id)
            logger.info(f"Auto-queued {len(goal_clip_ids)} goal close-ups for video {video_id}")
        except Exception as exc:
            logger.warning(f"close-up auto-queue skipped: {exc}")

# ===== Register all api_router routes =====
app.include_router(api_router)

# ===== Auto-Resume on Startup =====

async def _seed_owner_admin_once():
    """One-time startup migration: promote the canonical app owner email to
    `role: "admin"` so they can access /admin/processing-events without
    needing the env-var path that the Emergent UI doesn't expose on their
    plan tier.

    Idempotent via the `system_migrations` collection — once the
    `iter77_owner_admin_seed` marker is recorded, subsequent restarts are
    no-ops. We delay the marker write until promotion actually succeeds, so
    if the owner hasn't registered yet on the first deploy this migration
    will re-attempt on the next restart instead of being marked complete
    forever.

    Owner email is hardcoded because the deployment-UI env-var path is
    blocked on this user's plan. If the owner ever changes email, replace
    the constant below and bump the migration id (e.g.,
    `iter77b_owner_admin_seed`) so the new value takes effect.
    """
    OWNER_EMAIL = "ben.buursma@gmail.com"
    MIGRATION_ID = "iter77_owner_admin_seed"

    await asyncio.sleep(3)  # let main routes settle so logs aren't interleaved
    try:
        # Idempotent guard — never re-run after a successful seed
        marker = await db.system_migrations.find_one({"id": MIGRATION_ID})
        if marker:
            logger.info(f"iter77 owner-admin seed: already applied at {marker.get('ran_at')}")
            return

        # Case-insensitive lookup so re-typed-with-different-case re-registers
        # don't break the migration
        user = await db.users.find_one(
            {"email": {"$regex": f"^{OWNER_EMAIL}$", "$options": "i"}},
            {"_id": 0, "id": 1, "email": 1, "role": 1},
        )
        if not user:
            logger.warning(
                f"iter77 owner-admin seed: user {OWNER_EMAIL!r} not yet registered. "
                "Will retry on next startup."
            )
            return  # don't record marker — try again next boot

        current_role = (user.get("role") or "").lower()
        if current_role in ("admin", "owner"):
            logger.info(
                f"iter77 owner-admin seed: {user['email']} already has role={current_role!r}, "
                "recording marker so we stop retrying."
            )
        else:
            await db.users.update_one(
                {"id": user["id"]}, {"$set": {"role": "admin"}},
            )
            logger.warning(
                f"iter77 owner-admin seed: promoted {user['email']} "
                f"from role={current_role!r} to role='admin' (user_id={user['id']})"
            )

        # Record the marker on either success path so we don't retry forever
        await db.system_migrations.insert_one({
            "id": MIGRATION_ID,
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "promoted_email": user["email"],
            "promoted_user_id": user["id"],
            "prior_role": current_role,
        })
    except Exception as e:
        # Migration failures must never crash startup
        logger.error(f"iter77 owner-admin seed failed: {e}")


async def resume_interrupted_processing():
    """On server restart, find any videos stuck in 'processing' or 'queued' state and resume them.

    Each resume bumps `resume_attempts` on the video doc. If a video has
    been resumed `_MAX_RESUME_ATTEMPTS` times with zero progress on the
    last attempt, we declare a pod-OOM-loop and mark it `failed` with a
    clear actionable error — re-queueing forever would just keep
    OOM-killing the pod across the rest of the user's work (iter75, real
    production bug 2026-05-18 video 2ebe539f, 3.93 GB).
    """
    await asyncio.sleep(5)  # Wait for server to fully initialize
    try:
        stuck_videos = await db.videos.find(
            {"processing_status": {"$in": ["processing", "queued"]}},
            {"_id": 0, "id": 1, "user_id": 1, "is_chunked": 1, "total_chunks": 1,
             "chunk_paths": 1, "chunk_backends": 1, "file_size_bytes": 1,
             "resume_attempts": 1, "processing_progress": 1, "filename": 1,
             "last_resume_at": 1}
        ).to_list(100)

        if not stuck_videos:
            logger.info("No interrupted processing jobs to resume")
            return

        logger.info(f"Found {len(stuck_videos)} interrupted processing jobs — resuming")

        for video in stuck_videos:
            video_id = video["id"]
            user_id = video["user_id"]

            # Skip videos with incomplete chunk data — re-queueing them is
            # futile (every retry will hit the same fail-fast guard in
            # run_auto_processing). Mark them failed once with a clear
            # actionable error so the user sees the "re-upload required"
            # state instead of an infinite 0% spinner across restarts.
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
                if total > 0 and available < total:
                    pct = round((available / total) * 100, 1)
                    msg = (
                        f"Upload incomplete ({available} of {total} chunks, {pct}%). "
                        "Re-upload required — AI analysis can't run on a partial file."
                    )
                    logger.warning(
                        f"Skipping resume for {video_id}: integrity={available}/{total} "
                        f"({pct}%). Marking failed."
                    )
                    await db.videos.update_one(
                        {"id": video_id},
                        {"$set": {
                            "processing_status": "failed",
                            "processing_error": msg,
                            "processing_progress": 0,
                            "processing_current": None,
                            "processing_completed_at": datetime.now(timezone.utc).isoformat(),
                        }},
                    )
                    continue

            # iter75: pod-OOM-loop detection.
            # If a video has been resumed _MAX_RESUME_ATTEMPTS times AND the
            # last resume made zero progress (still at 0%), conclude that
            # ffmpeg is OOM-killing the pod BEFORE its Python handler can
            # fire iter63's auto-retry. Mark it failed with the "compression
            # required" error — the frontend banner already escalates to
            # the red RE-UPLOAD REQUIRED CTA on `processing_status == 'failed'`.
            #
            # A successful previous attempt that crossed >0% indicates the
            # pipeline IS able to make progress; in that case we keep
            # resuming so iter63's retry-at-240p tier can still kick in.
            #
            # iter97 — Rapid-cycle detection. If 2 OOM-cycles happen within
            # 5 min (which is unambiguously a memory loop, not real work),
            # fail fast at attempt 2 instead of waiting for attempt 3 ≈ 30 min
            # of pain. Compare current resume timestamp to last_resume_at.
            prior_attempts = int(video.get("resume_attempts") or 0)
            prior_progress = int(video.get("processing_progress") or 0)
            prior_resume_at = video.get("last_resume_at")
            rapid_loop = False
            if prior_attempts >= 2 and prior_progress == 0 and prior_resume_at:
                try:
                    prior_dt = datetime.fromisoformat(prior_resume_at)
                    if prior_dt.tzinfo is None:
                        prior_dt = prior_dt.replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - prior_dt).total_seconds() < 300:
                        rapid_loop = True
                except (TypeError, ValueError):
                    pass

            if rapid_loop or (prior_attempts >= _MAX_RESUME_ATTEMPTS and prior_progress == 0):
                size_gb = round((video.get("file_size_bytes") or 0) / (1024 ** 3), 2) or None
                cycle_label = "twice in <5min" if rapid_loop else f"{prior_attempts}×"
                msg = (
                    f"Processing failed {cycle_label} without making any progress. "
                    "Source file is too heavy for our encoding pod — re-compress with "
                    "HandBrake (Fast 720p30 / CQ 28) and re-upload."
                )
                logger.warning(
                    f"Pod-OOM-loop detected for {video_id} "
                    f"(resume_attempts={prior_attempts}, progress=0, rapid={rapid_loop}). "
                    "Marking failed."
                )
                await db.videos.update_one(
                    {"id": video_id},
                    {"$set": {
                        "processing_status": "failed",
                        "processing_error": msg,
                        "processing_progress": 0,
                        "processing_current": None,
                        "processing_completed_at": datetime.now(timezone.utc).isoformat(),
                    }},
                )
                # Log to processing_events so the Top Failed Videos panel
                # picks it up with a distinct failure_mode and the Email Fix
                # button routes the compression-help template (iter71).
                try:
                    from services.processing_events import log_event as _log_event
                    await _log_event(
                        video_id=video_id,
                        user_id=user_id,
                        event_type="final_failure",
                        failure_mode="pod_oom_loop",
                        source_size_gb=size_gb,
                        error_message=f"{msg} (resume_attempts={prior_attempts})",
                    )
                except Exception:
                    pass  # instrumentation must never break the guard
                continue

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
                # Bump the resume counter BEFORE kicking off the new attempt
                # so we count THIS resume even if the pod dies before
                # run_auto_processing can record progress.
                # iter97 — also stamp `last_resume_at` so the rapid-cycle
                # detector above can tell whether 2 OOMs happened within 5 min.
                await db.videos.update_one(
                    {"id": video_id},
                    {
                        "$inc": {"resume_attempts": 1},
                        "$set": {"last_resume_at": datetime.now(timezone.utc).isoformat()},
                    },
                )
                logger.info(
                    f"Resuming processing for video {video_id}: {remaining} "
                    f"(attempt {prior_attempts + 1}/{_MAX_RESUME_ATTEMPTS}, "
                    f"already done: {list(completed)})"
                )
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

# ===== CSRF Middleware =====
#
# Enforces the double-submit token check for cookie-authenticated requests.
# Runs AFTER CORS (lower in source = earlier in inbound middleware chain — yes,
# Starlette wraps middleware in reverse order, so add_middleware calls AFTER
# CORSMiddleware run BEFORE it on inbound requests. That's what we want — CSRF
# rejections still get CORS headers attached on the way out.)
#
# Skip conditions (request passes through without CSRF check):
#   1. Safe methods (GET, HEAD, OPTIONS) — by definition can't mutate state
#   2. Path not under /api (frontend assets, websocket upgrades, etc.)
#   3. Login/register/logout endpoints — they bootstrap the CSRF token, can't have one yet
#   4. Authorization: Bearer header present — legacy clients use explicit credentials,
#      which are inherently CSRF-immune (an attacker can't make the browser send a
#      custom header on a cross-site request without CORS preflight, which fails)
#   5. No access_token cookie — the request is either unauthenticated (the route
#      will 401) or path-token-authenticated (public share links, video src tags)
#
# When the check applies:
#   csrf_token cookie value MUST equal X-CSRF-Token header value.
#   Mismatch → 403.

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/logout",
}

@app.middleware("http")
async def csrf_protection_middleware(request: Request, call_next):
    method = request.method.upper()
    path = request.url.path

    # 1) Safe methods: never CSRF-relevant
    if method in SAFE_METHODS:
        return await call_next(request)
    # 2) Non-API: not our concern
    if not path.startswith("/api"):
        return await call_next(request)
    # 3) Auth bootstrap endpoints
    if path in CSRF_EXEMPT_PATHS:
        return await call_next(request)

    # 4) Legacy header-based auth → inherently CSRF-immune
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        return await call_next(request)

    # 5) No cookie session → either unauthenticated (route handles it) or
    #    path-token authenticated (public shares). Either way, no cookie =
    #    no CSRF surface.
    if not request.cookies.get(ACCESS_TOKEN_COOKIE):
        return await call_next(request)

    # Now we have: unsafe method + /api/* + cookie session. CSRF check required.
    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get(CSRF_HEADER)
    # Constant-time compare to avoid timing oracle (token comparisons are usually
    # too fast for timing attacks to matter in practice, but it's free to be safe).
    import hmac as _hmac
    if not cookie_token or not header_token or not _hmac.compare_digest(cookie_token, header_token):
        logger.warning(
            f"[csrf] BLOCKED {method} {path} — cookie_present={bool(cookie_token)} "
            f"header_present={bool(header_token)} match={cookie_token == header_token if cookie_token and header_token else False}"
        )
        # Return a JSON 403 manually so CORS still wraps it
        return JSONResponse(
            status_code=403,
            content={"detail": "CSRF token missing or invalid. Refresh the page to renew your session."},
        )

    return await call_next(request)

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

    # iter55 — login rate-limiter MongoDB indexes (unique key + 30min TTL on
    # last_attempt_at so stale lockouts auto-clear without a sweeper job).
    try:
        from services.login_rate_limiter import ensure_login_attempts_indexes
        await ensure_login_attempts_indexes(db)
        logger.info("login_attempts indexes ensured")
    except Exception as e:
        logger.error(f"login_attempts index setup failed: {e}")
    logger.info(f"Chunk storage dir: {CHUNK_STORAGE_DIR}")
    logger.info(f"Server boot ID: {SERVER_BOOT_ID}")
    
    # iter77 — one-time owner-admin seed migration. Runs once per Mongo
    # database to promote the canonical app owner to admin without requiring
    # any UI env-var configuration (the Emergent deployment UI on the user's
    # plan doesn't expose the secrets panel after deploy). Marker stored in
    # `system_migrations` so a second startup is a no-op.
    asyncio.create_task(_seed_owner_admin_once())

    # Auto-resume interrupted processing from previous server instance
    asyncio.create_task(resume_interrupted_processing())
    # Periodic sweeper for permanently purging soft-deleted videos
    asyncio.create_task(deleted_video_sweeper())
    # One-shot cleanup of stale ffmpeg temp files left over from a crashed/killed previous boot
    asyncio.create_task(_cleanup_stale_temp_files())
    # iter64 follow-up — hourly pipeline-health check that alerts via Resend
    # when the final_failure rate spikes (gives us a heads-up before users
    # start reporting). De-duped + threshold-gated; see processing_alerts.py.
    asyncio.create_task(_processing_alerts_loop())
    # iter83 — background migration of persistent_filesystem chunks back to
    # object storage as soon as storage recovers. Cheap when idle (single
    # sparse Mongo query per tick).
    from services.storage import migrate_persistent_chunks_loop
    asyncio.create_task(migrate_persistent_chunks_loop())
    # iter86 — daily hard-purge of `dismissed_at` chunked_uploads older than 30 days
    # AND stale user_notifications older than 30 days. Soft-delete forever is
    # fine until tens of thousands accumulate; this caps the table size.
    asyncio.create_task(_dismissed_uploads_ttl_sweeper())
    # iter94 — weekly storage-growth audit so the admin UI can show
    # whether orphan accumulation is still climbing post-fix.
    asyncio.create_task(_storage_growth_audit_loop())
    # APScheduler — weekly Coach Pulse blast every Monday 08:00 UTC +
    # email-queue retry every 30 min for quota-deferred sends.
    start_coach_pulse_scheduler()


async def _processing_alerts_loop():
    """Run the pipeline-health check once an hour, forever. Wraps check_and_alert
    in a sleep loop so we don't need APScheduler for this one-line job."""
    from services.processing_alerts import check_and_alert
    # Stagger startup so we don't spam if the pod is restarting frequently
    await asyncio.sleep(120)
    while True:
        try:
            result = await check_and_alert()
            if result.get("action") == "alert_sent":
                logger.warning(f"Pipeline alert fired: {result}")
            elif result.get("action") not in ("skip_low_volume", "skip_below_threshold"):
                logger.info(f"Pipeline alert check: {result.get('action')}")
        except Exception as e:
            logger.exception(f"_processing_alerts_loop tick failed (will retry): {e}")
        await asyncio.sleep(3600)  # 1 hour


# iter86 — TTL sweeper tunables (module-level so tests can monkeypatch them).
DISMISSED_UPLOADS_TTL_DAYS = 30
USER_NOTIFICATIONS_TTL_DAYS = 30
TTL_SWEEPER_INTERVAL_SECS = 24 * 3600  # daily


async def _dismissed_uploads_ttl_sweeper():
    """Hard-purge `chunked_uploads` rows that were dismissed >30 days ago,
    and stale `user_notifications` rows >30 days old. Soft-deleting forever
    is fine until tens of thousands accumulate (banner perf, /me/notifications
    cursor cost). This bounds the table size.

    Runs daily. Startup stagger so a fresh boot doesn't immediately fire."""
    await asyncio.sleep(300)  # 5min startup stagger
    while True:
        try:
            now = datetime.now(timezone.utc)
            dismiss_cutoff = (now - timedelta(days=DISMISSED_UPLOADS_TTL_DAYS)).isoformat()
            notif_cutoff = (now - timedelta(days=USER_NOTIFICATIONS_TTL_DAYS)).isoformat()

            uploads_res = await db.chunked_uploads.delete_many({
                "dismissed_at": {"$exists": True, "$lt": dismiss_cutoff},
            })
            notifs_res = await db.user_notifications.delete_many({
                "created_at": {"$lt": notif_cutoff},
            })
            if uploads_res.deleted_count or notifs_res.deleted_count:
                logger.info(
                    f"[ttl-sweeper] purged {uploads_res.deleted_count} dismissed uploads "
                    f"(> {DISMISSED_UPLOADS_TTL_DAYS}d) + {notifs_res.deleted_count} stale "
                    f"notifications (> {USER_NOTIFICATIONS_TTL_DAYS}d)"
                )
        except Exception as e:
            logger.exception(f"[ttl-sweeper] tick failed (will retry tomorrow): {e}")
        await asyncio.sleep(TTL_SWEEPER_INTERVAL_SECS)


async def _cleanup_stale_temp_files():
    """Delete temp ffmpeg artifacts older than 5 min on boot AND every 5 min.

    When the pod is OOM-killed mid-ffmpeg, `finally` cleanup never runs and we
    leak hundreds of MBs of `tmpXXXX.mp4` files. This sweeper reclaims that
    space + logs the current disk usage so operators can spot trends.

    Aggressive 5-min staleness threshold + 5-min cadence: a healthy ffmpeg job
    either completes or fails well within 5 minutes for the 240p/8fps proxy.
    The combo means at any given moment we hold at most ~10 min of leaked
    temp files instead of the previous ~40 min worst case (30min cadence +
    10min staleness).
    """
    import time as _time
    import glob
    import shutil as _shutil
    cutoff = _time.time() - 5 * 60  # 5 minutes ago (was 10)
    patterns = [
        "/var/video_chunks/tmp*",
        "/var/video_chunks/close_ups/tmp*",
        "/var/video_chunks/reels/tmp*",
        "/tmp/tmp*.mp4",
        "/tmp/tmp*.png",
    ]
    reclaimed_bytes = 0
    reclaimed_count = 0
    for pattern in patterns:
        for path in glob.glob(pattern):
            try:
                st = os.stat(path)
                if not stat.S_ISREG(st.st_mode):
                    continue
                if st.st_mtime < cutoff:
                    size = st.st_size
                    os.unlink(path)
                    reclaimed_bytes += size
                    reclaimed_count += 1
            except (OSError, NameError):
                continue
    if reclaimed_count > 0:
        logger.info(
            "[disk-sweep] reclaimed %.1f MB across %d stale temp files",
            reclaimed_bytes / (1024 * 1024), reclaimed_count,
        )

    # Always log current disk usage so we have a trail when the pod gets killed
    try:
        total, used, free = _shutil.disk_usage("/var/video_chunks")
        pct = (used / total) * 100 if total > 0 else 0
        msg = (
            f"[disk-sweep] disk usage: {used/(1024**3):.1f}G / {total/(1024**3):.1f}G "
            f"({pct:.0f}%) — free {free/(1024**3):.1f}G"
        )
        if pct >= 80:
            logger.warning("%s — DISK PRESSURE", msg)
        else:
            logger.info(msg)
    except OSError:
        pass


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

        async def _reel_recap_job():
            try:
                from services.reel_recap import send_weekly_reel_recap
                result = await send_weekly_reel_recap(triggered_by="apscheduler")
                logger.info("[apscheduler] reel recap weekly: %s", result)
            except Exception as e:
                logger.error("[apscheduler] reel recap weekly crashed: %s", e)

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
            _cleanup_stale_temp_files,
            IntervalTrigger(minutes=5),
            id="ffmpeg_temp_cleanup",
            replace_existing=True,
            misfire_grace_time=300,
        )
        _scheduler.add_job(
            _scout_digest_job,
            CronTrigger(day_of_week="mon", hour=9, minute=0, timezone="UTC"),
            id="scout_digest_weekly",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        _scheduler.add_job(
            _reel_recap_job,
            CronTrigger(day_of_week="mon", hour=10, minute=0, timezone="UTC"),
            id="reel_recap_weekly",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        _scheduler.start()
        logger.info(
            "[apscheduler] scheduler started — coach_pulse_weekly (Mon 08:00 UTC) + email_queue_retry (every 30 min) + scout_digest_weekly (Mon 09:00 UTC) + reel_recap_weekly (Mon 10:00 UTC) + ffmpeg_temp_cleanup (every 30 min)"
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
