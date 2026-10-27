"""
AI transcription + extraction with provider preference.

Transcription chain (default): Gemini 3.5 Transcribe → OpenAI gpt-transcribe → AssemblyAI.
Extraction: Gemini extract model → OpenAI GPT.
"""

import logging
import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from services.assemblyai_service import AssemblyAIService
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
    assemblyai_svc: Optional["AssemblyAIService"] = None,
) -> str:
    """
    Transcribe completed voice note.

    Order when AI_TRANSCRIBE_PROVIDER=gemini (default):
      1) Gemini gemini-3.5-transcribe
      2) OpenAI gpt-transcribe
      3) AssemblyAI universal-3-5-pro (if ASSEMBLYAI_API_KEY set)
    """
    want = _transcribe_provider()
    errors: List[str] = []

    if want == "gemini" and gemini_svc is not None:
        try:
            return await gemini_svc.transcribe_audio(audio_bytes, filename)
        except Exception as e:
            msg = f"Gemini: {e}"
            errors.append(msg)
            logger.warning("Gemini transcribe failed, trying OpenAI: %s", e)
    elif want == "gemini" and gemini_svc is None:
        logger.warning("AI_TRANSCRIBE_PROVIDER=gemini but GEMINI_API_KEY missing; trying OpenAI")

    if want in ("gemini", "openai", ""):
        try:
            return await openai_svc.transcribe_audio(audio_bytes, filename)
        except Exception as e:
            msg = f"OpenAI: {e}"
            errors.append(msg)
            logger.warning("OpenAI transcribe failed, trying AssemblyAI: %s", e)

    if want == "assemblyai" and assemblyai_svc is not None:
        return await assemblyai_svc.transcribe_audio(audio_bytes, filename)

    if assemblyai_svc is not None:
        try:
            return await assemblyai_svc.transcribe_audio(audio_bytes, filename)
        except Exception as e:
            msg = f"AssemblyAI: {e}"
            errors.append(msg)
            logger.warning("AssemblyAI transcribe failed: %s", e)

    detail = "; ".join(errors) if errors else "no transcription provider available"
    raise RuntimeError(f"All transcription providers failed: {detail}")


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
