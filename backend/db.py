"""Database connection and shared state"""
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
from dotenv import load_dotenv
import os

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

STORAGE_URL = "https://integrations.emergentagent.com/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "soccer-analysis"
JWT_SECRET = os.environ.get("JWT_SECRET")
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB per chunk
CHUNK_STORAGE_DIR = "/var/video_chunks"

# iter83: persistent fallback. /var/video_chunks lives on overlay and
# evaporates on pod restart (real production bug 2026-05-21 — 35 of 85
# chunks lost when the pod recycled mid-upload). /app is mounted on a
# real PV (/dev/nvme0n*) so files there survive restarts. We keep
# CHUNK_STORAGE_DIR as the legacy LARGE temp tier (used by post-finalize
# work that doesn't need to outlive a single request), but every chunk
# fallback from object-storage failure goes here instead.
PERSISTENT_CHUNK_DIR = "/app/.video_chunks"
# Refuse a new persistent-fallback write if /app is this close to full —
# /app is small (~7 GB free), so we leave a safety reserve so the rest of
# the app (logs, db, build artifacts) doesn't OOM on us.
PERSISTENT_CHUNK_FREE_MIN_BYTES = 500 * 1024 * 1024  # 500 MB

# SERVER_BOOT_ID/TIME moved to runtime.py — re-exported for backwards compatibility
# with any existing imports (tests or route modules).
from runtime import SERVER_BOOT_ID, SERVER_BOOT_TIME  # noqa: E402,F401
