"""
OpenAI Service - Handles audio transcription and GPT structured extraction.

- Audio transcription: gpt-transcribe (whisper-1 deprecated, shutdown 2027-02-26)
- GPT: extract structured inventory data from transcription
- All operations support async via AsyncOpenAI.
"""

import io
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

from services.inventory_json import parse_inventory_items_from_llm_text

logger = logging.getLogger(__name__)

# Whisper API supports: mp3, mp4, mpeg, mpga, m4a, wav, webm
# Telegram voice = OGG/Opus, which is NOT supported - must convert to MP3
SUPPORTED_WHISPER_FORMATS = {"mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm"}

# Prompt for extracting one or more inventory items from transcription.
# Supports multilingual input; output must be a pure JSON array.
EXTRACTION_PROMPT = """You are an information extraction engine for a pet pantry
(cats and dogs: food, treats, litter, and medications).

The user speaks in ANY language (e.g. Chinese or English), in ANY order, and may
omit fields. Extract a structured list. Do NOT invent a rigid phrase template.

OUTPUT FORMAT (VERY IMPORTANT):
- Return ONLY a JSON array.
- Each element MUST be an object with exactly these keys:
  - "brand"    (string or null)
  - "flavor"   (string or null)
  - "category" (string or null) — per item, independently. Prefer labels in the
    SAME language as that item's wording:
    English: freeze-dried | can | broth pouch | lickable | treat | dry food | litter | meds
    Chinese: 冻干 | 罐头 | 汤包 | 猫条 | 零食 | 干粮 | 猫砂 | 药品
    If the type is unclear, use null — do NOT default to can/罐头. Prefer "can" (not "wet food").
  - "best_by"  (string or null, YYYY-MM-DD)
  - "quantity" (integer or null)
- No extra keys, no wrapper, no markdown, no explanations.

INTERPRETATION RULES (flexible speech):
- Speakers do NOT have to say brand then flavor then quantity then date.
  Partial utterances are valid (e.g. only a drug name, or only "two chicken cans").
- MULTI-ITEM: set category for EACH object from THAT object's cues only.
  Never copy freeze-dried/冻干 onto a different brand that was described as cans/湿粮.
  Example: "Two cans of Fancy Feast chicken … and one bag of Ziwi beef freeze dried"
  → item1 Fancy Feast category "can" (cans); item2 Ziwi category "freeze-dried".
- brand: maker / food brand / pharmacy brand if spoken (Royal Canin, 丸味, Zoetis).
  Copy uncommon names exactly. null if none.
- flavor:
  - Food: flavor or variant (chicken, 鸡肉, salmon).
  - Medication: put the DRUG / PRODUCT NAME (+ strength if said) here
    (e.g. "Apoquel 16mg", "甲状腺药", "gabapentin 100mg").
  - If only one product-like name is spoken and it is a medicine, put it in
    flavor and set category to meds/药品; brand may be null.
- category cues: can(s)/canned → can; freeze-dried/冻干 → freeze-dried;
  litter/猫砂; meds/药; lickable/猫条; kibble/dry food/干粮.
  Never force can when the user is talking about meds, litter, or dry food.
- best_by: expiry / best-by if mentioned; else null. Dates may apply to the
  nearest preceding item only.
- quantity: units (cans/bags/bottles/boxes). Words like "two"/"两" → integer.
  null if not said.
- Uncertain fields → null. Prefer a brand guess only when a brand-like name
  was clearly spoken for food.

EXAMPLES (conceptual):
- "Fancy Feast 鸡肉两罐，保质期 2025-06-01" → food row, category 罐头.
- "Two cans of Fancy Feast chicken, best by 2026-06-01" → category "can".
- "还有半瓶 Apoquel 十六毫克" → category 药品, flavor "Apoquel 16mg",
  quantity null or 1, brand null unless a maker was said.
- "买了猫砂一大袋" → category 猫砂.
- "丸味冻干还剩三袋" → brand 丸味, category 冻干, quantity 3.
- "two bags of Orijen dog food" → brand Orijen; category "dry food" if clear.

STRICT OUTPUT: ONLY a JSON array of item objects."""


def _convert_ogg_to_mp3_ffmpeg(audio_bytes: bytes) -> bytes:
    """Convert OGG/Opus → MP3 via ffmpeg CLI (no pydub / audioop needed)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError(
            "ffmpeg not found. Install ffmpeg for OGG conversion (e.g. brew install ffmpeg)"
        )

    in_path = out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as inp:
            inp.write(audio_bytes)
            in_path = inp.name
        out_fd, out_path = tempfile.mkstemp(suffix=".mp3")
        os.close(out_fd)

        proc = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                in_path,
                "-acodec",
                "libmp3lame",
                "-q:a",
                "4",
                out_path,
            ],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[-500:]
            raise RuntimeError(f"ffmpeg failed (code {proc.returncode}): {err}")
        with open(out_path, "rb") as f:
            mp3 = f.read()
        if not mp3:
            raise RuntimeError("ffmpeg produced empty MP3")
        return mp3
    finally:
        for path in (in_path, out_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def _convert_ogg_to_mp3_pydub(audio_bytes: bytes) -> bytes:
    """Fallback via pydub (needs audioop on older Python; audioop-lts on 3.13+)."""
    from pydub import AudioSegment

    ogg_io = io.BytesIO(audio_bytes)
    try:
        segment = AudioSegment.from_ogg(ogg_io)
    except Exception:
        ogg_io.seek(0)
        segment = AudioSegment.from_file(ogg_io, format="ogg")
    mp3_io = io.BytesIO()
    segment.export(mp3_io, format="mp3")
    return mp3_io.getvalue()


def _convert_ogg_to_mp3(audio_bytes: bytes) -> bytes:
    """
    Convert Telegram OGG/Opus audio to MP3 for STT APIs.

    Prefer ffmpeg CLI (works on Python 3.13+ where stdlib audioop was removed).
    Fall back to pydub if ffmpeg is unavailable.
    """
    # 1) ffmpeg — reliable path for local + Docker
    try:
        return _convert_ogg_to_mp3_ffmpeg(audio_bytes)
    except FileNotFoundError as e:
        logger.warning("ffmpeg CLI unavailable (%s); trying pydub", e)
        ffmpeg_missing = e
    except Exception as e:
        logger.warning("ffmpeg conversion failed (%s); trying pydub", e)
        ffmpeg_missing = e

    # 2) pydub fallback
    try:
        return _convert_ogg_to_mp3_pydub(audio_bytes)
    except ImportError as e:
        logger.error(
            "pydub/audioop unavailable. Install: pip install pydub audioop-lts; "
            "and ensure ffmpeg is on PATH."
        )
        raise OpenAIServiceError(
            "Audio conversion failed: need ffmpeg on PATH "
            "(or pydub + audioop-lts on Python 3.13+)."
        ) from e
    except FileNotFoundError as e:
        if "ffmpeg" in str(e).lower() or "ffprobe" in str(e).lower():
            raise OpenAIServiceError(
                "ffmpeg not found. Install ffmpeg for OGG conversion "
                "(e.g. brew install ffmpeg)"
            ) from e
        raise OpenAIServiceError(f"Audio conversion failed: {e}") from e
    except Exception as e:
        logger.exception("OGG to MP3 conversion failed: %s", e)
        raise OpenAIServiceError(
            f"Audio conversion failed: {e} (ffmpeg earlier: {ffmpeg_missing})"
        ) from e


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
                "Sending audio to OpenAI STT (size=%d, format=%s, model=%s)",
                len(audio_bytes),
                eff_filename,
                os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-transcribe"),
            )
            response = await self.client.audio.transcriptions.create(
                model=os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-transcribe").strip()
                or "gpt-transcribe",
                file=audio_file,
                response_format="text",
            )
        except Exception as e:
            logger.exception("OpenAI transcription API error: %s", e)
            raise OpenAIServiceError(f"Transcription failed: {e}") from e

        transcription = getattr(response, "text", None) or str(response)
        if not transcription or not transcription.strip():
            logger.warning("OpenAI STT returned empty transcription")
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

        return parse_inventory_items_from_llm_text(content)
