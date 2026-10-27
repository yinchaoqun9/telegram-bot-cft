"""Unit tests for Gemini→OpenAI→AssemblyAI fallback pipeline (mocked services)."""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from services import ai_pipeline


class _Boom(Exception):
    pass


@pytest.mark.asyncio
async def test_transcribe_gemini_success(monkeypatch):
    monkeypatch.setenv("AI_TRANSCRIBE_PROVIDER", "gemini")
    gemini = AsyncMock()
    gemini.transcribe_audio = AsyncMock(return_value="hello from gemini")
    openai = AsyncMock()
    openai.transcribe_audio = AsyncMock(return_value="openai")
    aai = AsyncMock()
    aai.transcribe_audio = AsyncMock(return_value="assembly")

    text = await ai_pipeline.transcribe_preferred(
        b"audio", "a.ogg", openai, gemini, aai
    )
    assert text == "hello from gemini"
    gemini.transcribe_audio.assert_awaited_once()
    openai.transcribe_audio.assert_not_awaited()
    aai.transcribe_audio.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcribe_falls_back_to_openai(monkeypatch):
    monkeypatch.setenv("AI_TRANSCRIBE_PROVIDER", "gemini")
    gemini = AsyncMock()
    gemini.transcribe_audio = AsyncMock(side_effect=_Boom("gemini down"))
    openai = AsyncMock()
    openai.transcribe_audio = AsyncMock(return_value="gpt-transcribe ok")
    aai = AsyncMock()
    aai.transcribe_audio = AsyncMock(return_value="assembly")

    text = await ai_pipeline.transcribe_preferred(
        b"audio", "a.ogg", openai, gemini, aai
    )
    assert text == "gpt-transcribe ok"
    openai.transcribe_audio.assert_awaited_once()
    aai.transcribe_audio.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcribe_falls_back_to_assemblyai(monkeypatch):
    monkeypatch.setenv("AI_TRANSCRIBE_PROVIDER", "gemini")
    gemini = AsyncMock()
    gemini.transcribe_audio = AsyncMock(side_effect=_Boom("gemini down"))
    openai = AsyncMock()
    openai.transcribe_audio = AsyncMock(side_effect=_Boom("openai down"))
    aai = AsyncMock()
    aai.transcribe_audio = AsyncMock(return_value="assembly ok")

    text = await ai_pipeline.transcribe_preferred(
        b"audio", "a.ogg", openai, gemini, aai
    )
    assert text == "assembly ok"
    aai.transcribe_audio.assert_awaited_once()


@pytest.mark.asyncio
async def test_transcribe_all_fail_raises(monkeypatch):
    monkeypatch.setenv("AI_TRANSCRIBE_PROVIDER", "gemini")
    gemini = AsyncMock()
    gemini.transcribe_audio = AsyncMock(side_effect=_Boom("g"))
    openai = AsyncMock()
    openai.transcribe_audio = AsyncMock(side_effect=_Boom("o"))
    aai = AsyncMock()
    aai.transcribe_audio = AsyncMock(side_effect=_Boom("a"))

    with pytest.raises(RuntimeError, match="All transcription providers failed"):
        await ai_pipeline.transcribe_preferred(
            b"audio", "a.ogg", openai, gemini, aai
        )


@pytest.mark.asyncio
async def test_transcribe_gemini_missing_uses_openai(monkeypatch):
    monkeypatch.setenv("AI_TRANSCRIBE_PROVIDER", "gemini")
    openai = AsyncMock()
    openai.transcribe_audio = AsyncMock(return_value="only openai")

    text = await ai_pipeline.transcribe_preferred(b"audio", "a.ogg", openai, None, None)
    assert text == "only openai"


@pytest.mark.asyncio
async def test_extract_falls_back_to_openai(monkeypatch):
    monkeypatch.setenv("AI_EXTRACT_PROVIDER", "gemini")
    items: List[Dict[str, Any]] = [{"brand": "X"}]
    gemini = AsyncMock()
    gemini.extract_inventory_data = AsyncMock(side_effect=_Boom("extract fail"))
    openai = AsyncMock()
    openai.extract_inventory_data = AsyncMock(return_value=items)

    out = await ai_pipeline.extract_preferred("transcript", openai, gemini)
    assert out == items
    openai.extract_inventory_data.assert_awaited_once()
