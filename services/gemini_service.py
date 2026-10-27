"""
Google Gemini: dedicated STT (gemini-3.5-transcribe) + structured inventory extraction.

Transcription uses the Google Gen AI SDK Interactions / generateContent path.
Extraction uses a separate chat/flash model (transcription models are STT-only).
Audio: Telegram OGG -> MP3 via openai_service._prepare_audio_for_whisper (ffmpeg).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any, Dict, List, Optional

from services.inventory_json import parse_inventory_items_from_llm_text
from services.openai_service import EXTRACTION_PROMPT, _prepare_audio_for_whisper

logger = logging.getLogger(__name__)


class GeminiServiceError(Exception):
    """Raised on Gemini API or processing errors."""

    pass


class GeminiService:
    """Gemini transcription (3.5 Transcribe) + extraction (separate model)."""

    def __init__(
        self,
        api_key: str,
        *,
        extract_model: str,
        transcribe_model: str = "gemini-3.5-transcribe",
    ):
        self._api_key = api_key
        self._extract_model = extract_model
        self._transcribe_model = transcribe_model

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def model_name(self) -> str:
        """Backward-compatible: extract model id (used by brand refine)."""
        return self._extract_model

    @property
    def transcribe_model_name(self) -> str:
        return self._transcribe_model

    def _client(self):
        from google import genai

        return genai.Client(api_key=self._api_key)

    def _custom_vocabulary(self) -> List[str]:
        """Brand catalog terms as STT hints (cap ~100 for best results)."""
        try:
            from services.brand_catalog import get_brand_catalog

            cat = get_brand_catalog()
            # Prefer canonical names; catalog may expose choices via private attrs
            labels = list(getattr(cat, "_choices", []) or [])
            # Dedupe case-insensitively, keep order
            seen: set = set()
            out: List[str] = []
            for lab in labels:
                lk = lab.lower()
                if lk in seen or len(lab) < 2:
                    continue
                seen.add(lk)
                out.append(lab)
                if len(out) >= 100:
                    break
            return out
        except Exception:
            return []

    def _transcribe_sync(self, mp3_bytes: bytes) -> str:
        """
        Call gemini-3.5-transcribe via Interactions API (inline audio under 20MB).

        Fits Telegram voice notes: completed recording, zh/en inventory speech,
        optional brand vocabulary bias.
        """
        client = self._client()
        b64 = base64.b64encode(mp3_bytes).decode("utf-8")
        vocab = self._custom_vocabulary()

        transcription_config: Dict[str, Any] = {
            # Empty / omit = auto language detect (zh+en code-switch OK)
            "language_codes": [],
            "mode": {"type": "smart"},
        }
        if vocab:
            transcription_config["custom_vocabulary"] = vocab

        # Prefer Interactions API (official Transcribe docs)
        try:
            interaction = client.interactions.create(
                model=self._transcribe_model,
                input=[
                    {
                        "type": "audio",
                        "data": b64,
                        "mime_type": "audio/mp3",
                    }
                ],
                generation_config={"transcription_config": transcription_config},
            )
            text = getattr(interaction, "output_text", None) or ""
            if callable(text):
                text = text()
            return (text or "").strip()
        except Exception as interactions_err:
            logger.warning(
                "Gemini interactions.transcribe failed (%s); trying generate_content",
                interactions_err,
            )

        # Fallback: generateContent API (also documented for gemini-3.5-transcribe)
        from google.genai import types

        part = types.Part.from_bytes(data=mp3_bytes, mime_type="audio/mpeg")
        response = client.models.generate_content(
            model=self._transcribe_model,
            contents=[part],
        )
        text = getattr(response, "text", None) or ""
        return (text or "").strip()

    def _extract_sync(self, transcription: str) -> List[Dict[str, Any]]:
        """Inventory JSON extraction with a general Gemini chat/flash model."""
        import google.generativeai as genai

        genai.configure(api_key=self._api_key)
        model = genai.GenerativeModel(
            self._extract_model,
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

        logger.info(
            "Gemini transcription model=%s length=%d chars",
            self._transcribe_model,
            len(text),
        )
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
