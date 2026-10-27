"""
AssemblyAI pre-recorded speech-to-text (third-tier transcription backup).

Telegram voice notes are completed files → use async Universal-3.5 Pro
(`universal-3-5-pro`), NOT streaming Universal-3.6 Pro (`universal-3-6-pro`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Optional

from services.openai_service import _prepare_audio_for_whisper

logger = logging.getLogger(__name__)

DEFAULT_SPEECH_MODELS = ["universal-3-5-pro", "universal-2"]


class AssemblyAIServiceError(Exception):
    """Raised on AssemblyAI API or processing errors."""

    pass


class AssemblyAIService:
    """Upload + transcribe completed audio via AssemblyAI pre-recorded API."""

    def __init__(self, api_key: str, speech_models: Optional[list] = None):
        self._api_key = api_key
        self._speech_models = speech_models or list(DEFAULT_SPEECH_MODELS)

    def _transcribe_sync(self, mp3_bytes: bytes) -> str:
        from assemblyai.prerecorded.v2 import Transcriber, TranscriptionConfig

        config = TranscriptionConfig(
            speech_models=self._speech_models,
            language_detection=True,
        )
        transcriber = Transcriber(api_key=self._api_key)

        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(mp3_bytes)
                path = tmp.name
            transcript = transcriber.transcribe(path, config)
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

        status = getattr(transcript, "status", None)
        err = getattr(transcript, "error", None)
        text = getattr(transcript, "text", None) or ""
        if err or (status and str(status).lower() in ("error", "failed")):
            raise AssemblyAIServiceError(f"AssemblyAI failed: {err or status}")
        return (text or "").strip()

    async def transcribe_audio(
        self, audio_bytes: bytes, filename: str = "voice.ogg"
    ) -> str:
        if not audio_bytes:
            raise AssemblyAIServiceError("Empty audio file")
        try:
            audio_file, _eff = _prepare_audio_for_whisper(audio_bytes, filename)
            audio_file.seek(0)
            mp3_bytes = audio_file.read()
        except Exception as e:
            logger.exception("Audio preparation for AssemblyAI failed: %s", e)
            raise AssemblyAIServiceError(f"Audio conversion failed: {e}") from e

        try:
            text = await asyncio.to_thread(self._transcribe_sync, mp3_bytes)
        except AssemblyAIServiceError:
            raise
        except Exception as e:
            logger.exception("AssemblyAI transcription error: %s", e)
            raise AssemblyAIServiceError(f"Transcription failed: {e}") from e

        logger.info(
            "AssemblyAI transcription models=%s length=%d chars",
            self._speech_models,
            len(text),
        )
        return text
