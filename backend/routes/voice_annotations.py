"""Voice annotation — Whisper transcription + Gemini classification.

Flow:
1. Frontend POSTs an audio blob (webm/mp4/wav) + the timestamp
2. Backend transcribes via OpenAI Whisper (whisper-1)
3. Backend classifies the transcription as note / tactical / key_moment via Gemini
4. Backend persists as a regular annotation (compatible with existing AnnotationsSidebar)
5. Returns the annotation so the UI can append it to its list
"""
from __future__ import annotations
import os
import io
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel
from db import db
from routes.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
ALLOWED_TYPES = {"note", "tactical", "key_moment"}


class VoiceAnnotationResponse(BaseModel):
    id: str
    video_id: str
    timestamp: float
    annotation_type: str
    content: str
    transcript: str
    classification_confidence: Optional[float] = None
    created_at: str


async def _transcribe(audio_bytes: bytes, filename: str) -> str:
    """Run Whisper transcription in a worker thread (blocking SDK)."""
    from emergentintegrations.llm.openai import OpenAISpeechToText

    if not EMERGENT_KEY:
        raise HTTPException(status_code=503, detail="Whisper not configured (EMERGENT_LLM_KEY missing)")

    stt = OpenAISpeechToText(api_key=EMERGENT_KEY)
    file_obj = io.BytesIO(audio_bytes)
    file_obj.name = filename  # SDK uses the .name attr to detect format
    try:
        resp = await stt.transcribe(file=file_obj, model="whisper-1", response_format="json", language="en")
        return (resp.text or "").strip()
    except Exception as e:
        logger.error("whisper transcription failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Transcription failed: {str(e)[:140]}")


async def _classify(transcript: str) -> tuple[str, float]:
    """Classify transcript into note/tactical/key_moment via Gemini.

    Returns (annotation_type, confidence). Falls back to 'note' on any error.
    """
    if not transcript.strip():
        return "note", 0.0

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_KEY,
            session_id=f"voice-classify-{uuid.uuid4()}",
            system_message=(
                "You are a soccer coaching assistant. Classify a coach's voice annotation "
                "into one of three categories. Respond with ONLY valid JSON, no markdown.\n\n"
                "Categories:\n"
                "- 'tactical': formation, pressing, shape, transitions, set pieces, marking, build-up\n"
                "- 'key_moment': goal, save, foul, card, chance, turnover, big mistake, momentum shift\n"
                "- 'note': general observation, player effort, encouragement, anything else\n\n"
                'Output exactly: {"type": "tactical|key_moment|note", "confidence": 0.0-1.0}'
            ),
        ).with_model("gemini", "gemini-2.5-flash")
        msg = UserMessage(text=f'Classify this annotation: "{transcript}"')
        raw = await chat.send_message(msg)
        # Strip code fences if present
        cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(cleaned)
        atype = parsed.get("type", "note")
        if atype not in ALLOWED_TYPES:
            atype = "note"
        return atype, float(parsed.get("confidence", 0.5))
    except Exception as e:
        logger.info("classify fallback (note) — %s", e)
        return "note", 0.0


@router.post("/voice-annotations", response_model=VoiceAnnotationResponse)
async def create_voice_annotation(
    video_id: str = Form(...),
    timestamp: float = Form(...),
    audio: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    # Validate the user owns this video
    video = await db.videos.find_one(
        {"id": video_id, "user_id": current_user["id"]}, {"_id": 0, "id": 1}
    )
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    audio_bytes = await audio.read()
    if len(audio_bytes) < 1000:  # 1KB sanity floor
        raise HTTPException(status_code=400, detail="Audio file is empty or too short")
    if len(audio_bytes) > 25 * 1024 * 1024:  # Whisper hard limit
        raise HTTPException(status_code=413, detail="Audio file exceeds 25MB limit")

    # Determine extension from content-type so Whisper accepts it
    ct = (audio.content_type or "").lower()
    ext = "webm"
    if "mp4" in ct or "m4a" in ct:
        ext = "m4a"
    elif "wav" in ct:
        ext = "wav"
    elif "mpeg" in ct or "mp3" in ct:
        ext = "mp3"
    filename = f"voice.{ext}"

    transcript = await _transcribe(audio_bytes, filename)
    if not transcript:
        raise HTTPException(status_code=422, detail="No speech detected. Try recording again louder/closer to the mic.")

    atype, confidence = await _classify(transcript)

    doc = {
        "id": str(uuid.uuid4()),
        "video_id": video_id,
        "user_id": current_user["id"],
        "timestamp": float(timestamp),
        "annotation_type": atype,
        "content": transcript,
        "source": "voice",
        "transcript": transcript,
        "classification_confidence": confidence,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.annotations.insert_one(dict(doc))
    doc.pop("_id", None)
    doc.pop("user_id", None)
    return VoiceAnnotationResponse(**{k: doc[k] for k in (
        "id", "video_id", "timestamp", "annotation_type", "content",
        "transcript", "classification_confidence", "created_at",
    )})
