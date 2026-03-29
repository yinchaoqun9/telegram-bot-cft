"""
Telegram Bot Backend - FastAPI Webhook Server

Receives Telegram webhook updates, processes voice notes through Whisper + GPT,
and stores structured inventory data in Supabase.
Uses async throughout for non-blocking I/O.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response

from services.openai_service import OpenAIService, OpenAIServiceError
from services.supabase_service import SupabaseService, SupabaseServiceError
from services.telegram_service import TelegramService, TelegramServiceError

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Reduce noisy HTTP client logs (can include sensitive URLs)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)

# Initialize services (lazy - will fail fast on first request if misconfigured)
_openai: Optional[OpenAIService] = None
_supabase: Optional[SupabaseService] = None
_telegram: Optional[TelegramService] = None


def get_openai() -> OpenAIService:
    """Get or create OpenAI service."""
    global _openai
    if _openai is None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError("OPENAI_API_KEY not set")
        _openai = OpenAIService(api_key=key)
    return _openai


def get_supabase() -> SupabaseService:
    """Get or create Supabase service."""
    global _supabase
    if _supabase is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
        _supabase = SupabaseService(url=url, service_key=key)
    return _supabase


def get_telegram() -> TelegramService:
    """Get or create Telegram service."""
    global _telegram
    if _telegram is None:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        _telegram = TelegramService(bot_token=token)
    return _telegram


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: validate env vars. Shutdown: nothing to clean."""
    try:
        get_openai()
        get_supabase()
        get_telegram()
        logger.info("All services initialized successfully")
    except RuntimeError as e:
        logger.warning("Service init warning (may fail at first request): %s", e)
    yield


app = FastAPI(
    title="Cat Inventory Telegram Bot",
    description="Webhook backend for voice-based cat food inventory tracking",
    version="1.0.0",
    lifespan=lifespan,
)


async def process_voice_message(
    chat_id: int, user_id: int, file_id: str
) -> None:
    """
    Full pipeline: download voice -> Whisper -> GPT extraction -> Supabase -> reply.
    All steps are async. Handles Telegram OGG/Opus via conversion to MP3.
    """
    tg = get_telegram()
    openai_svc = get_openai()
    supabase_svc = get_supabase()

    # Persist user -> chat mapping for future reminders (private chat scenario)
    try:
        await supabase_svc.upsert_telegram_user(user_id=str(user_id), chat_id=int(chat_id))
    except Exception as e:
        # Don't block core functionality if mapping fails
        logger.warning("Failed to upsert telegram user mapping: %s", e)

    # 1. Download voice file (async)
    try:
        audio_bytes = await tg.download_voice(file_id)
    except TelegramServiceError as e:
        logger.error("Telegram download failed: %s", e)
        await tg.send_error_message(chat_id, "Failed to download voice. Please try again.")
        return
    except Exception as e:
        logger.exception("Unexpected error downloading voice: %s", e)
        await tg.send_error_message(chat_id, "An error occurred. Please try again later.")
        return

    if not audio_bytes or len(audio_bytes) == 0:
        logger.warning("Empty voice file received")
        await tg.send_error_message(chat_id, "Voice file was empty. Please try again.")
        return

    # 2. Transcribe with Whisper (async, handles OGG->MP3 conversion)
    try:
        transcription = await openai_svc.transcribe_audio(
            audio_bytes, filename="voice.ogg"
        )
    except OpenAIServiceError as e:
        logger.error("Transcription failed: %s", e)
        await tg.send_error_message(
            chat_id, "Could not transcribe the voice message. Please try again."
        )
        return
    except Exception as e:
        logger.exception("Unexpected transcription error: %s", e)
        await tg.send_error_message(chat_id, "Transcription failed. Please try again.")
        return

    if not transcription or not transcription.strip():
        await tg.send_message(
            chat_id, "Could not transcribe the voice message. Please try again."
        )
        return

    # 3. Extract structured data with GPT (async) - may return multiple items
    try:
        raw_items = await openai_svc.extract_inventory_data(transcription)
    except ValueError as e:
        logger.warning("GPT extraction failed: %s", e)
        await tg.send_error_message(chat_id, str(e))
        return
    except OpenAIServiceError as e:
        logger.error("GPT extraction error: %s", e)
        await tg.send_error_message(
            chat_id, "Could not extract inventory data. Please try again."
        )
        return

    # Normalize items (types and empty filtering)
    items = []
    for raw in raw_items:
        brand = (str(raw.get("brand")) if raw.get("brand") is not None else "").strip()
        flavor = (
            str(raw.get("flavor")) if raw.get("flavor") is not None else ""
        ).strip()
        best_by = (
            str(raw.get("best_by")) if raw.get("best_by") is not None else ""
        ).strip()
        try:
            quantity = int(raw.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0

        # Skip items that are completely empty
        if not (brand or flavor or best_by or quantity):
            continue

        items.append(
            {
                "brand": brand,
                "flavor": flavor,
                "best_by": best_by,
                "quantity": quantity,
            }
        )

    if not items:
        await tg.send_error_message(
            chat_id,
            "Could not find any inventory items in your message. Please try again.",
        )
        return

    # 4. Insert into Supabase (async via thread pool) - batch insert
    try:
        await supabase_svc.insert_inventory_items(
            user_id=str(user_id),
            items=items,
        )
    except SupabaseServiceError as e:
        logger.exception("Supabase insert failed: %s", e)
        await tg.send_error_message(
            chat_id, "Failed to save inventory. Please try again."
        )
        return
    except Exception as e:
        logger.exception("Unexpected Supabase error: %s", e)
        await tg.send_error_message(chat_id, "Database error. Please try again later.")
        return

    # 5. Confirm to user (async) - handles single or multiple items
    try:
        await tg.send_saved_confirmation_multi(chat_id, items)
        logger.info(
            "Successfully processed %d items for user=%s chat=%s",
            len(items),
            user_id,
            chat_id,
        )
    except Exception as e:
        logger.exception("Failed to send confirmation to user: %s", e)


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    """
    Telegram webhook endpoint. Receives updates and processes voice messages.
    Returns 200 quickly; processing runs async to avoid Telegram timeout.
    """
    try:
        body = await request.json()
    except Exception as e:
        logger.warning("Invalid webhook body (not JSON): %s", e)
        return Response(status_code=400)

    # Telegram may send other update types; we only care about messages
    message = body.get("message") or body.get("edited_message")
    if not message:
        logger.debug("Ignoring non-message update type")
        return Response(status_code=200)

    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    voice = message.get("voice")

    if not chat_id or not user_id:
        logger.warning("Message missing chat_id or user_id")
        return Response(status_code=200)

    # Best-effort: persist mapping for reminders
    try:
        await get_supabase().upsert_telegram_user(user_id=str(user_id), chat_id=int(chat_id))
    except Exception as e:
        logger.warning("Failed to upsert telegram user mapping (webhook): %s", e)

    if voice:
        file_id = voice.get("file_id")
        if file_id:
            # Process in background to respond to Telegram within timeout
            # Telegram expects webhook response within ~60s
            asyncio.create_task(process_voice_message(chat_id, user_id, file_id))
            logger.info("Queued voice processing for chat_id=%s user_id=%s", chat_id, user_id)
        else:
            logger.warning("Voice message without file_id")
    else:
        # Non-voice message: help reply
        text = (message.get("text") or "").strip().lower()
        if text in ("/start", "/help"):
            tg = get_telegram()
            try:
                await tg.send_message(
                    chat_id,
                    "Send a voice message describing your cat food (brand, flavor, best-by date, quantity) to add it to your inventory.",
                )
            except Exception as e:
                logger.exception("Failed to send help message: %s", e)

    return Response(status_code=200)


@app.get("/health")
async def health() -> dict:
    """Health check for load balancers and monitoring."""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("ENV", "production") != "production",
    )
