"""
Google Gemini: audio transcription + structured inventory extraction.

Uses sync google.generativeai under asyncio.to_thread.
Audio: Telegram OGG -> MP3 via openai_service._prepare_audio_for_whisper (ffmpeg).
"""

import asyncio
import logging
from typing import Any, Dict, List

from services.inventory_json import parse_inventory_items_from_llm_text
from services.openai_service import EXTRACTION_PROMPT, _prepare_audio_for_whisper

logger = logging.getLogger(__name__)


class GeminiServiceError(Exception):
    """Raised on Gemini API or processing errors."""

    pass


class GeminiService:
    """Gemini transcription + extraction."""

    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model

    def _transcribe_sync(self, mp3_bytes: bytes) -> str:
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)
        model = genai.GenerativeModel(self._model)
        prompt = (
            "Transcribe the speech in this audio. Output only the spoken words, "
            "in the same language as the speaker. Do not translate. "
            "No preamble, labels, or quotation marks."
        )
        response = model.generate_content(
            [
                prompt,
                {"mime_type": "audio/mpeg", "data": mp3_bytes},
            ]
        )
        text = _gemini_response_text(response)
        return (text or "").strip()

    def _extract_sync(self, transcription: str) -> List[Dict[str, Any]]:
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)
        model = genai.GenerativeModel(
            self._model,
            system_instruction=EXTRACTION_PROMPT,
        )
        response = model.generate_content(
            transcription,
            generation_config={"temperature": 0},
        )
        content = _gemini_response_text(response)
        if not content:
            raise ValueError("Gemini returned empty content")
        return parse_inventory_items_from_llm_text(content)

    async def transcribe_audio(
        self, audio_bytes: bytes, filename: str = "voice.ogg"
    ) -> str:
        if not audio_bytes:
            raise GeminiServiceError("Empty audio file")
        try:
            audio_file, _eff = _prepare_audio_for_whisper(audio_bytes, filename)
            audio_file.seek(0)
            mp3_bytes = audio_file.read()
        except Exception as e:
            logger.exception("Audio preparation for Gemini failed: %s", e)
            raise GeminiServiceError(f"Audio conversion failed: {e}") from e

        try:
            text = await asyncio.to_thread(self._transcribe_sync, mp3_bytes)
        except Exception as e:
            logger.exception("Gemini transcription error: %s", e)
            raise GeminiServiceError(f"Transcription failed: {e}") from e

        logger.info("Gemini transcription length=%d chars", len(text))
        return text

    async def extract_inventory_data(self, transcription: str) -> List[Dict[str, Any]]:
        if not transcription or not transcription.strip():
            raise ValueError("Empty transcription")
        try:
            return await asyncio.to_thread(self._extract_sync, transcription.strip())
        except ValueError:
            raise
        except Exception as e:
            logger.exception("Gemini extraction error: %s", e)
            raise GeminiServiceError(f"Extraction failed: {e}") from e


def _gemini_response_text(response: Any) -> str:
    """Safely get text from GenerateContentResponse."""
    try:
        if getattr(response, "text", None):
            return response.text
    except Exception:
        pass
    parts: List[str] = []
    try:
        for cand in response.candidates or []:
            for part in getattr(cand.content, "parts", []) or []:
                if getattr(part, "text", None):
                    parts.append(part.text)
    except Exception:
        pass
    return "".join(parts).strip()
