"""Runtime constants shared across route modules without creating circular imports.

SERVER_BOOT_ID changes on every backend restart. Route modules use it to let the
frontend detect restarts mid-processing (so the UI can re-poll video processing
status instead of assuming stale progress).
"""
import uuid
from datetime import datetime, timezone

SERVER_BOOT_ID: str = str(uuid.uuid4())
SERVER_BOOT_TIME: str = datetime.now(timezone.utc).isoformat()
