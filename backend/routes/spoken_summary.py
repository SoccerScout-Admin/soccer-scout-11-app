"""Post-game spoken summary + auto-highlight-reel from voice key_moments.

Flow A — Spoken Summary:
  1. POST /api/matches/{match_id}/spoken-summary  (multipart audio)
     → Whisper transcribes. Saves the raw transcript to match.insights.summary.
     Returns { transcript, polished?: null }.
  2. POST /api/matches/{match_id}/spoken-summary/polish
     → Re-runs the existing transcript through Gemini for a 2-3 paragraph polish.
     Saves polished version as match.insights.summary, keeps raw transcript at
     match.insights.spoken_transcript so coaches can revert.

Flow B — Auto-reel:
  POST /api/matches/{match_id}/auto-reel
     → Finds all annotations for this match's video where source='voice' and
       annotation_type='key_moment'. Creates a clip per annotation (±5s window),
       bundles them in a clip_collection, returns the share_token.
"""
from __future__ import annotations
import os
import io
import re
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from pydantic import BaseModel, Field
from db import db
from routes.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


def _emergent_key() -> Optional[str]:
    return os.environ.get("EMERGENT_LLM_KEY")


# -------- Spoken summary --------

class SpokenSummaryResponse(BaseModel):
    transcript: str
    summary: str
    is_polished: bool = False


async def _whisper_transcribe(audio_bytes: bytes, filename: str) -> str:
    from emergentintegrations.llm.openai import OpenAISpeechToText

    key = _emergent_key()
    if not key:
        raise HTTPException(status_code=503, detail="Whisper not configured (EMERGENT_LLM_KEY missing)")
    stt = OpenAISpeechToText(api_key=key)
    fobj = io.BytesIO(audio_bytes)
    fobj.name = filename
    try:
        resp = await stt.transcribe(file=fobj, model="whisper-1", response_format="json", language="en")
        return (resp.text or "").strip()
    except Exception as e:
        logger.error("whisper transcription failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Transcription failed: {str(e)[:140]}")


@router.post("/matches/{match_id}/spoken-summary", response_model=SpokenSummaryResponse)
async def create_spoken_summary(
    match_id: str,
    audio: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    audio_bytes = await audio.read()
    if len(audio_bytes) < 1000:
        raise HTTPException(status_code=400, detail="Audio too short (need ≥1 second)")
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio exceeds 25MB limit")

    ct = (audio.content_type or "").lower()
    ext = "webm"
    if "mp4" in ct or "m4a" in ct:
        ext = "m4a"
    elif "wav" in ct:
        ext = "wav"
    elif "mpeg" in ct or "mp3" in ct:
        ext = "mp3"

    transcript = await _whisper_transcribe(audio_bytes, f"summary.{ext}")
    if not transcript:
        raise HTTPException(status_code=422, detail="No speech detected. Try again louder.")

    # Persist as the match's insights.summary (raw, unpolished)
    existing_insights = match.get("insights") or {}
    existing_insights["summary"] = transcript
    existing_insights["spoken_transcript"] = transcript
    existing_insights["summary_source"] = "spoken_raw"
    existing_insights["summary_recorded_at"] = datetime.now(timezone.utc).isoformat()

    await db.matches.update_one(
        {"id": match_id},
        {"$set": {"insights": existing_insights}},
    )
    return SpokenSummaryResponse(transcript=transcript, summary=transcript, is_polished=False)


@router.post("/matches/{match_id}/spoken-summary/polish", response_model=SpokenSummaryResponse)
async def polish_spoken_summary(
    match_id: str,
    current_user: dict = Depends(get_current_user),
):
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")

    insights = match.get("insights") or {}
    transcript = insights.get("spoken_transcript")
    if not transcript:
        raise HTTPException(status_code=400, detail="No spoken transcript to polish — record one first")

    key = _emergent_key()
    if not key:
        raise HTTPException(status_code=503, detail="Polish not configured (EMERGENT_LLM_KEY missing)")

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=key,
            session_id=f"polish-{match_id}",
            system_message=(
                "You are a soccer coaching assistant. Turn a coach's rough spoken match recap "
                "into a clean, professional 2-3 paragraph summary. Preserve every concrete observation, "
                "fix grammar, remove filler words ('um', 'like', 'you know'), and keep the coach's voice. "
                "Output plain text only — no markdown, no headers, no lists."
            ),
        ).with_model("gemini", "gemini-2.5-flash")
        msg = UserMessage(text=f"Polish this match recap:\n\n{transcript}")
        polished = (await chat.send_message(msg)).strip()
    except Exception as e:
        logger.warning("polish fallback: %s — %s", type(e).__name__, str(e)[:120])
        raise HTTPException(status_code=502, detail="AI polish failed — original transcript kept as summary")

    # Strip any code-fences just in case
    polished = re.sub(r"^```(?:text)?\s*|\s*```$", "", polished, flags=re.MULTILINE).strip()
    if not polished:
        raise HTTPException(status_code=502, detail="AI polish returned empty text")

    insights["summary"] = polished
    insights["summary_source"] = "spoken_polished"
    insights["summary_polished_at"] = datetime.now(timezone.utc).isoformat()
    await db.matches.update_one({"id": match_id}, {"$set": {"insights": insights}})
    return SpokenSummaryResponse(transcript=transcript, summary=polished, is_polished=True)


# -------- Auto-reel from voice key_moments --------

class AutoReelInput(BaseModel):
    pre_seconds: float = Field(default=5.0, ge=0.0, le=30.0)
    post_seconds: float = Field(default=5.0, ge=0.0, le=30.0)
    title: Optional[str] = None


class AutoReelResponse(BaseModel):
    collection_id: str
    share_token: str
    clip_count: int
    title: str
    skipped_existing: int = 0


@router.post("/matches/{match_id}/auto-reel", response_model=AutoReelResponse)
async def create_auto_reel(
    match_id: str,
    body: AutoReelInput,
    current_user: dict = Depends(get_current_user),
):
    match = await db.matches.find_one({"id": match_id, "user_id": current_user["id"]}, {"_id": 0})
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    video_id = match.get("video_id")
    if not video_id:
        raise HTTPException(status_code=400, detail="Match has no video attached")

    # Find voice key_moments
    key_moments = await db.annotations.find(
        {"video_id": video_id, "user_id": current_user["id"],
         "source": "voice", "annotation_type": "key_moment"},
        {"_id": 0},
    ).sort("timestamp", 1).to_list(100)

    if not key_moments:
        raise HTTPException(status_code=400, detail="No voice-tagged key_moments found for this match. Use the Live Coaching mic to tag highlights first.")

    # Get the video duration so we can clamp clip windows
    video = await db.videos.find_one({"id": video_id}, {"_id": 0, "duration": 1})
    duration = (video or {}).get("duration") or 1e9

    # Build one clip per key_moment, ±N seconds window
    created_clip_ids: list[str] = []
    skipped_existing = 0
    now = datetime.now(timezone.utc).isoformat()

    for ann in key_moments:
        ts = float(ann["timestamp"])
        start = max(0.0, ts - body.pre_seconds)
        end = min(float(duration), ts + body.post_seconds)
        # Skip if a near-identical clip already exists (same start ±0.5s + same source flag)
        existing = await db.clips.find_one({
            "video_id": video_id,
            "user_id": current_user["id"],
            "source": "auto_reel",
            "start_time": {"$gte": start - 0.5, "$lte": start + 0.5},
        }, {"_id": 0, "id": 1})
        if existing:
            created_clip_ids.append(existing["id"])
            skipped_existing += 1
            continue

        clip_id = str(uuid.uuid4())
        title = (ann.get("content") or "Highlight")[:80]
        clip = {
            "id": clip_id,
            "video_id": video_id,
            "user_id": current_user["id"],
            "match_id": match_id,
            "start_time": start,
            "end_time": end,
            "title": title,
            "description": "Auto-generated from voice key_moment",
            "clip_type": "highlight",
            "source": "auto_reel",
            "source_annotation_id": ann["id"],
            "player_ids": [],
            "created_at": now,
        }
        await db.clips.insert_one(clip)
        created_clip_ids.append(clip_id)

    if not created_clip_ids:
        raise HTTPException(status_code=500, detail="Failed to build clips")

    title = body.title or f"{match.get('team_home','Home')} vs {match.get('team_away','Away')} — Voice Highlights"
    coll = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "title": title,
        "clip_ids": created_clip_ids,
        "share_token": str(uuid.uuid4())[:12],
        "source": "auto_reel",
        "match_id": match_id,
        "created_at": now,
    }
    await db.clip_collections.insert_one(coll)

    return AutoReelResponse(
        collection_id=coll["id"],
        share_token=coll["share_token"],
        clip_count=len(created_clip_ids),
        title=title,
        skipped_existing=skipped_existing,
    )
