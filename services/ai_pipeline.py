"""
AI transcription + extraction with provider preference (Gemini first, OpenAI fallback).
"""

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from services.gemini_service import GeminiService
    from services.openai_service import OpenAIService

logger = logging.getLogger(__name__)


def _transcribe_provider() -> str:
    return os.environ.get("AI_TRANSCRIBE_PROVIDER", "gemini").strip().lower()


def _extract_provider() -> str:
    return os.environ.get("AI_EXTRACT_PROVIDER", "gemini").strip().lower()


async def transcribe_preferred(
    audio_bytes: bytes,
    filename: str,
    openai_svc: "OpenAIService",
    gemini_svc: Optional["GeminiService"],
) -> str:
    """Transcribe: prefer Gemini when configured and AI_TRANSCRIBE_PROVIDER=gemini."""
    want = _transcribe_provider()
    if want == "gemini" and gemini_svc is not None:
        try:
            return await gemini_svc.transcribe_audio(audio_bytes, filename)
        except Exception as e:
            logger.warning("Gemini transcribe failed, falling back to OpenAI Whisper: %s", e)
    elif want == "gemini" and gemini_svc is None:
        logger.warning("AI_TRANSCRIBE_PROVIDER=gemini but GEMINI_API_KEY missing; using OpenAI")

    return await openai_svc.transcribe_audio(audio_bytes, filename)


async def extract_preferred(
    transcription: str,
    openai_svc: "OpenAIService",
    gemini_svc: Optional["GeminiService"],
) -> List[Dict[str, Any]]:
    """Extract JSON items: prefer Gemini when configured and AI_EXTRACT_PROVIDER=gemini."""
    want = _extract_provider()
    if want == "gemini" and gemini_svc is not None:
        try:
            return await gemini_svc.extract_inventory_data(transcription)
        except Exception as e:
            logger.warning("Gemini extract failed, falling back to OpenAI GPT: %s", e)
    elif want == "gemini" and gemini_svc is None:
        logger.warning("AI_EXTRACT_PROVIDER=gemini but GEMINI_API_KEY missing; using OpenAI")

    return await openai_svc.extract_inventory_data(transcription)
