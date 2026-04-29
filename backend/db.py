"""Database connection and shared state"""
from motor.motor_asyncio import AsyncIOMotorClient
from pathlib import Path
from dotenv import load_dotenv
import os
import uuid
from datetime import datetime, timezone

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
SERVER_BOOT_ID = str(uuid.uuid4())
SERVER_BOOT_TIME = datetime.now(timezone.utc).isoformat()
