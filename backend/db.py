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

# SERVER_BOOT_ID/TIME moved to runtime.py — re-exported for backwards compatibility
# with any existing imports (tests or route modules).
from runtime import SERVER_BOOT_ID, SERVER_BOOT_TIME  # noqa: E402,F401
