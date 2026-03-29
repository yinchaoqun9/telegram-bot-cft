"""
OpenAI Service - Handles Whisper transcription and GPT structured extraction.

- Whisper API: voice-to-text (with OGG/Opus -> MP3 conversion for Telegram)
- GPT: extract structured inventory data from transcription
- All operations support async via AsyncOpenAI.
"""

import io
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Whisper API supports: mp3, mp4, mpeg, mpga, m4a, wav, webm
# Telegram voice = OGG/Opus, which is NOT supported - must convert to MP3
SUPPORTED_WHISPER_FORMATS = {"mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm"}

# Prompt for extracting one or more inventory items from transcription.
# Supports multilingual input; output must be a pure JSON array.
EXTRACTION_PROMPT = """You are an information extraction engine.

The user speaks about one or more cat food inventory items in ANY language
(for example Chinese or English). Your job is to extract a structured list
of items from the transcription.

OUTPUT FORMAT (VERY IMPORTANT):
- You MUST return ONLY a JSON array.
- Each element of the array MUST be an object with exactly these keys:
  - "brand"   (string or null)
  - "flavor"  (string or null)
  - "best_by" (string or null, format YYYY-MM-DD)
  - "quantity"(integer or null)
- No extra keys, no wrapper object, no explanations, no markdown.

INTERPRETATION RULES:
- brand: the cat food brand name (e.g. "Royal Canin", "Fancy Feast").
- flavor: flavor or variant, usually near the brand (e.g. "chicken", "salmon").
- best_by: expiration or best-by date; normalize to YYYY-MM-DD when possible.
- quantity: number of units (cans/bags/etc.), convert words like "two" or "两"
  into an integer.
- If you are unsure about a field, set it to null.

MULTI-ITEM EXAMPLES (conceptual):
- Chinese:
  "第一种是 Fancy Feast 鸡肉口味，两罐，保质期 2025 年 6 月 1 号；
   第二种是 Purina 三文鱼口味，三罐，保质期也是 2025 年 6 月 1 号。"
  -> two array elements, one for each item.

- English:
  "I have two cans of Fancy Feast chicken, best by June 1st 2025,
   and three cans of Purina salmon, same best by date."
  -> two array elements.

Again: return ONLY a JSON array of item objects, nothing else."""


def _convert_ogg_to_mp3(audio_bytes: bytes) -> bytes:
    """
    Convert Telegram OGG/Opus audio to MP3 for Whisper API.

    Whisper does not support OGG/Opus. Telegram voice messages use OGG container
    with Opus codec. Requires pydub and ffmpeg.

    Args:
        audio_bytes: Raw OGG audio bytes

    Returns:
        MP3 bytes

    Raises:
        ImportError: If pydub not installed
        Exception: On conversion failure
    """
    try:
        from pydub import AudioSegment
    except ImportError as e:
        logger.error("pydub not installed - cannot convert OGG to MP3. Install: pip install pydub")
        raise ImportError(
            "pydub required for Telegram OGG voice. Install pydub and ffmpeg."
        ) from e

    try:
        ogg_io = io.BytesIO(audio_bytes)
        # Telegram voice: OGG container, Opus codec. Try from_ogg first.
        try:
            segment = AudioSegment.from_ogg(ogg_io)
        except Exception:
            ogg_io.seek(0)
            segment = AudioSegment.from_file(ogg_io, format="ogg")
        mp3_io = io.BytesIO()
        segment.export(mp3_io, format="mp3")
        return mp3_io.getvalue()
    except FileNotFoundError as e:
        if "ffmpeg" in str(e).lower() or "ffprobe" in str(e).lower():
            msg = "ffmpeg not found. Install ffmpeg for OGG conversion (e.g. brew install ffmpeg)"
            logger.error("%s: %s", msg, e)
            raise OpenAIServiceError(msg) from e
        raise
    except Exception as e:
        logger.exception("OGG to MP3 conversion failed: %s", e)
        raise OpenAIServiceError(f"Audio conversion failed: {e}") from e


def _prepare_audio_for_whisper(
    audio_bytes: bytes, filename: str = "voice.ogg"
) -> Tuple[io.BytesIO, str]:
    """
    Prepare audio bytes for Whisper API. Converts OGG/Opus to MP3 if needed.

    Returns:
        (file_like_object, effective_filename)
    """
    lower = filename.lower()
    if any(lower.endswith(ext) for ext in (".ogg", ".oga", ".opus")):
        logger.info("Converting OGG/Opus to MP3 for Whisper (Telegram voice format)")
        mp3_bytes = _convert_ogg_to_mp3(audio_bytes)
        audio_file = io.BytesIO(mp3_bytes)
        audio_file.name = "voice.mp3"
        return audio_file, "voice.mp3"
    # Already in supported format
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename
    return audio_file, filename


class OpenAIServiceError(Exception):
    """Raised on OpenAI API or processing errors."""

    pass


class OpenAIService:
    """Service for OpenAI Whisper and GPT APIs (async)."""

    def __init__(self, api_key: str):
        self.client = AsyncOpenAI(api_key=api_key)

    async def transcribe_audio(
        self, audio_bytes: bytes, filename: str = "voice.ogg"
    ) -> str:
        """
        Transcribe audio using Whisper API.

        Handles Telegram OGG/Opus by converting to MP3 before sending.
        Whisper supports: mp3, mp4, mpeg, mpga, m4a, wav, webm.

        Args:
            audio_bytes: Raw audio file bytes (OGG from Telegram)
            filename: Filename hint for format detection (default: voice.ogg)

        Returns:
            Transcribed text string

        Raises:
            OpenAIServiceError: On transcription failure
        """
        if not audio_bytes or len(audio_bytes) == 0:
            logger.warning("Empty audio bytes received")
            raise OpenAIServiceError("Empty audio file")

        try:
            audio_file, eff_filename = _prepare_audio_for_whisper(
                audio_bytes, filename
            )
        except Exception as e:
            logger.exception("Audio preparation failed: %s", e)
            raise OpenAIServiceError(f"Audio conversion failed: {e}") from e

        try:
            logger.debug(
                "Sending audio to Whisper (size=%d, format=%s)",
                len(audio_bytes),
                eff_filename,
            )
            response = await self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="text",
            )
        except Exception as e:
            logger.exception("Whisper API error: %s", e)
            raise OpenAIServiceError(f"Transcription failed: {e}") from e

        transcription = getattr(response, "text", None) or str(response)
        if not transcription or not transcription.strip():
            logger.warning("Whisper returned empty transcription")
            return ""

        logger.info("Transcription completed, length=%d chars", len(transcription))
        return transcription.strip()

    async def extract_inventory_data(self, transcription: str) -> List[Dict[str, Any]]:
        """
        Extract structured inventory data from transcription using GPT.

        Args:
            transcription: Raw transcription text from Whisper

        Returns:
            List of items, each with keys: brand, flavor, best_by, quantity

        Raises:
            ValueError: If GPT response is not valid JSON or missing fields
        """
        if not transcription or not transcription.strip():
            raise ValueError("Empty transcription")

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": EXTRACTION_PROMPT},
                    {"role": "user", "content": transcription},
                ],
                temperature=0,
            )
        except Exception as e:
            logger.exception("GPT API error: %s", e)
            raise OpenAIServiceError(f"Extraction failed: {e}") from e

        content = response.choices[0].message.content
        if not content:
            logger.error("GPT returned empty content")
            raise ValueError("GPT returned no content")

        content = content.strip()

        # Remove markdown code blocks if present
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            )

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON from GPT: %s", content[:200])
            raise ValueError(f"Failed to parse GPT response: {e}") from e

        # Normalize to a list of item dicts
        items: List[Dict[str, Any]] = []

        # If wrapped in { "items": [...] }
        if isinstance(data, dict) and "items" in data:
            data = data["items"]

        if isinstance(data, dict):
            # Single item object; wrap in list
            data = [data]

        if not isinstance(data, list):
            logger.error("GPT returned unsupported structure: %s", type(data))
            raise ValueError("Expected a JSON array or an object with 'items' key.")

        required = {"brand", "flavor", "best_by", "quantity"}
        for idx, raw in enumerate(data):
            if not isinstance(raw, dict):
                logger.warning("Skipping non-object item at index %d: %r", idx, raw)
                continue

            if not required.issubset(raw.keys()):
                logger.warning("Item %d missing keys. Got: %s", idx, list(raw.keys()))

            item = {
                "brand": raw.get("brand"),
                "flavor": raw.get("flavor"),
                "best_by": raw.get("best_by"),
                "quantity": raw.get("quantity"),
            }
            items.append(item)

        if not items:
            raise ValueError("No valid inventory items found in GPT response.")

        logger.debug("Extracted %d items from GPT response", len(items))
        return items
