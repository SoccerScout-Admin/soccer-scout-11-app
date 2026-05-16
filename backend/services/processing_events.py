"""
Lightweight event logger for the video-processing pipeline.

Why this exists: iter63 introduced tiered auto-retry in `prepare_video_sample`
which silently downgrades scale on transient ffmpeg failures (OOM, timeout).
Without instrumentation we can't tell:
  - How often the retry actually saves a user from a failed upload
  - Whether one tier dominates (e.g., 95% of users succeed at tier 0 and the
    retry tier is essentially dead code)
  - When a pod-memory-limit bump is justified (high OOM rate → bump it)
  - Whether a specific failure mode is creeping up

Each call writes ONE document to `processing_events`. We intentionally keep
this collection append-only and cap-friendly (no updates, no large blobs).
Disk pressure is minimal: ~250 bytes per event, ~3 events per upload at most,
which is ~750 bytes/upload. Trivial.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from db import db

logger = logging.getLogger(__name__)


async def log_event(
    video_id: str,
    user_id: str,
    event_type: str,
    tier_idx: Optional[int] = None,
    tier_label: Optional[str] = None,
    failure_mode: Optional[str] = None,
    source_size_gb: Optional[float] = None,
    output_size_mb: Optional[float] = None,
    duration_seconds: Optional[float] = None,
    error_message: Optional[str] = None,
) -> None:
    """Insert one processing_events document.

    event_type values used today:
      - tier_attempt   — ffmpeg started for this tier
      - tier_succeeded — ffmpeg returned cleanly for this tier
      - tier_failed    — ffmpeg failed for this tier (retried OR final)
      - final_success  — overall prepare_video_sample succeeded
      - final_failure  — overall prepare_video_sample raised after all tiers

    failure_mode values: oom | timeout | moov_missing | invalid_data |
                         no_space | unknown | none

    Errors are SWALLOWED — instrumentation must never break the pipeline it
    instruments. A noisy log line is OK; a crashed encode because Mongo had
    a hiccup is not.
    """
    try:
        doc = {
            "id": str(uuid.uuid4()),
            "video_id": video_id,
            "user_id": user_id,
            "event_type": event_type,
            "tier_idx": tier_idx,
            "tier_label": tier_label,
            "failure_mode": failure_mode,
            "source_size_gb": round(source_size_gb, 2) if source_size_gb is not None else None,
            "output_size_mb": round(output_size_mb, 1) if output_size_mb is not None else None,
            "duration_seconds": round(duration_seconds, 1) if duration_seconds is not None else None,
            "error_message": error_message[:500] if error_message else None,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.processing_events.insert_one(doc)
    except Exception as e:
        # Pipeline must never break because logging failed.
        logger.warning(f"processing_events.log_event failed (non-fatal): {e}")
