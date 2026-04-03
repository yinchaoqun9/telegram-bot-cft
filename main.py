"""
Telegram Bot Backend - FastAPI Webhook Server

Receives Telegram webhook updates, processes voice notes through Whisper + GPT,
and stores structured inventory data in Supabase.
Uses async throughout for non-blocking I/O.
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response

from services.ai_pipeline import extract_preferred, transcribe_preferred
from services.brand_catalog import get_brand_catalog
from services.brand_web_research import maybe_refine_brand_with_web_search
from services.gemini_service import GeminiService, GeminiServiceError
from services.product_category import normalize_category
from services.openai_service import OpenAIService, OpenAIServiceError
from services.supabase_service import SupabaseService, SupabaseServiceError
from services.telegram_service import TelegramService, TelegramServiceError

# Load environment variables
load_dotenv()

# Configure logging (stdout so Railway runtime logs always capture it)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)

# Reduce noisy HTTP client logs (can include sensitive URLs)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)

# Initialize services (lazy - will fail fast on first request if misconfigured)
_openai: Optional[OpenAIService] = None
_gemini: Optional[GeminiService] = None
_gemini_initialized: bool = False
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


def get_gemini() -> Optional[GeminiService]:
    """Optional Gemini client when GEMINI_API_KEY is set."""
    global _gemini, _gemini_initialized
    if _gemini_initialized:
        return _gemini
    _gemini_initialized = True
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash").strip()
    _gemini = GeminiService(api_key=key, model=model)
    return _gemini


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
    port = os.environ.get("PORT", "8000")
    logger.info("Application starting (PORT=%s)", port)
    try:
        get_openai()
        get_supabase()
        get_telegram()
        g = get_gemini()
        if g:
            logger.info("Gemini enabled (model=%s)", os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"))
        get_brand_catalog()
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


@app.middleware("http")
async def log_incoming_http(request: Request, call_next):
    """Log every HTTP request (proves traffic reaches this Railway service)."""
    logger.info("HTTP %s %s", request.method, request.url.path)
    response = await call_next(request)
    return response


async def process_voice_message(
    chat_id: int, user_id: int, file_id: str
) -> None:
    """
    Full pipeline: download voice -> Whisper -> GPT extraction -> Supabase -> reply.
    All steps are async. Handles Telegram OGG/Opus via conversion to MP3.
    """
    tg = get_telegram()
    openai_svc = get_openai()
    gemini_svc = get_gemini()
    supabase_svc = get_supabase()
    brand_cat = get_brand_catalog()

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

    # 2. Transcribe (Gemini preferred, else OpenAI Whisper)
    try:
        transcription = await transcribe_preferred(
            audio_bytes,
            "voice.ogg",
            openai_svc,
            gemini_svc,
        )
    except (OpenAIServiceError, GeminiServiceError) as e:
        err_text = str(e)
        logger.error(
            "Transcription failed: %s",
            err_text[:500] if len(err_text) > 500 else err_text,
        )
        # Railway / Linux images often lack ffmpeg -> OGG conversion fails
        if any(
            x in err_text.lower()
            for x in ("ffmpeg", "ffprobe", "audio conversion")
        ):
            await tg.send_error_message(
                chat_id,
                "Voice conversion failed (server needs ffmpeg). Ask admin to redeploy with Dockerfile or Nixpacks ffmpeg.",
            )
        else:
            await tg.send_error_message(
                chat_id,
                "Could not transcribe the voice message. Please try again.",
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

    # 3. Extract structured data (Gemini preferred, else GPT) - may return multiple items
    try:
        raw_items = await extract_preferred(
            transcription, openai_svc, gemini_svc
        )
    except ValueError as e:
        logger.warning("LLM extraction failed: %s", e)
        await tg.send_error_message(chat_id, str(e))
        return
    except (OpenAIServiceError, GeminiServiceError) as e:
        logger.error("LLM extraction error: %s", e)
        await tg.send_error_message(
            chat_id, "Could not extract inventory data. Please try again."
        )
        return

    # Normalize items (types and empty filtering)
    items = []
    for raw in raw_items:
        brand_raw = (
            str(raw.get("brand")) if raw.get("brand") is not None else ""
        ).strip()
        brand = await maybe_refine_brand_with_web_search(
            brand_cat,
            brand_raw,
            transcription,
            openai_svc,
            gemini_svc,
        )
        flavor = (
            str(raw.get("flavor")) if raw.get("flavor") is not None else ""
        ).strip()
        best_by = (
            str(raw.get("best_by")) if raw.get("best_by") is not None else ""
        ).strip()
        cat_raw = (
            str(raw.get("category")) if raw.get("category") is not None else ""
        ).strip()
        category = normalize_category(cat_raw, transcription)
        try:
            quantity = int(raw.get("quantity") or 0)
        except (TypeError, ValueError):
            quantity = 0

        # Skip items that are completely empty
        if not (brand or flavor or best_by or quantity or category):
            continue

        items.append(
            {
                "brand": brand,
                "flavor": flavor,
                "best_by": best_by,
                "quantity": quantity,
                "category": category,
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
        inserted_rows = await supabase_svc.insert_inventory_items(
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

    # 5. Confirm to user (async) - handles single or multiple items + delete buttons
    try:
        await tg.send_saved_confirmation_multi(chat_id, inserted_rows)
        logger.info(
            "Successfully processed %d items for user=%s chat=%s",
            len(items),
            user_id,
            chat_id,
        )
    except Exception as e:
        logger.exception("Failed to send confirmation to user: %s", e)


async def try_delete_saved_row(user_id: int, item_id: str) -> Tuple[bool, str]:
    """Delete entire inventory row (undo mistaken save)."""
    tid = (item_id or "").strip()
    if not tid:
        return False, "Missing item id."
    try:
        await get_supabase().delete_inventory_item(str(user_id), tid)
        return True, "Entry deleted."
    except SupabaseServiceError as e:
        return False, str(e) or "Could not delete."


async def try_decrement_inventory(user_id: int, item_id: str) -> Tuple[bool, str]:
    """Decrease quantity by 1 for user's item. Returns (success, user-facing detail)."""
    tid = (item_id or "").strip()
    if not tid:
        return False, "Missing item id."
    try:
        status = await get_supabase().decrement_item_quantity(
            str(user_id), tid, delta=1
        )
        if status == "deleted":
            return True, "Removed from inventory (quantity reached 0)."
        return True, "Quantity reduced by 1."
    except SupabaseServiceError as e:
        msg = str(e) or "Could not update item."
        return False, msg


async def handle_callback_query(callback: dict) -> None:
    """Inline keyboard: d:{item_id} delete row; u:{item_id} decrement qty."""
    cq_id = callback.get("id")
    from_user = callback.get("from") or {}
    user_id = from_user.get("id")
    data = (callback.get("data") or "").strip()
    if not cq_id or not user_id:
        return
    tg = get_telegram()
    if data.startswith("d:"):
        item_id = data[2:].strip()
        ok, detail = await try_delete_saved_row(int(user_id), item_id)
        try:
            await tg.answer_callback_query(
                cq_id,
                text=detail[:200],
                show_alert=not ok,
            )
        except Exception:
            logger.exception("answerCallbackQuery failed after delete")
        return
    if data.startswith("u:"):
        item_id = data[2:].strip()
        ok, detail = await try_decrement_inventory(int(user_id), item_id)
        try:
            await tg.answer_callback_query(
                cq_id,
                text=detail[:200],
                show_alert=not ok,
            )
        except Exception:
            logger.exception("answerCallbackQuery failed after decrement")
        return
    try:
        await tg.answer_callback_query(
            cq_id, text="Unknown action.", show_alert=True
        )
    except Exception:
        logger.exception("answerCallbackQuery failed")


async def handle_used_command(chat_id: int, user_id: int, text: str) -> None:
    """Parse /used <item_id> (supports /used@BotName)."""
    raw = (text or "").strip()
    parts = raw.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower() if parts else ""
    if cmd != "/used":
        return
    tg = get_telegram()
    if len(parts) < 2 or not parts[1].strip():
        try:
            await tg.send_message(
                chat_id,
                "Usage: /used <item_id>\nCopy the id from the daily digest message.",
                parse_mode=None,
            )
        except Exception as e:
            logger.exception("send_message failed: %s", e)
        return
    item_id = parts[1].strip()
    ok, detail = await try_decrement_inventory(user_id, item_id)
    try:
        await tg.send_message(
            chat_id,
            detail if ok else f"Could not update: {detail}",
            parse_mode=None,
        )
    except Exception as e:
        logger.exception("send_message failed: %s", e)


async def _voice_pipeline_guarded(chat_id: int, user_id: int, file_id: str) -> None:
    """
    Background tasks from asyncio.create_task() must not leak exceptions:
    otherwise uvicorn may only log 'Task exception was never retrieved' and
    the user gets no Telegram reply — easy to miss in Railway logs.
    """
    try:
        await process_voice_message(chat_id, user_id, file_id)
    except Exception:
        logger.exception(
            "Background voice pipeline crashed (chat_id=%s user_id=%s)",
            chat_id,
            user_id,
        )
        try:
            await get_telegram().send_error_message(
                chat_id,
                "Something went wrong while processing your voice. Please try again.",
            )
        except Exception:
            logger.exception(
                "Could not send error message after pipeline crash (chat_id=%s)",
                chat_id,
            )


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    """
    Telegram webhook endpoint. Receives updates and processes voice messages.
    Returns 200 quickly; processing runs async to avoid Telegram timeout.
    """
    logger.info("Webhook POST body read start")
    try:
        body = await request.json()
    except Exception as e:
        logger.warning("Invalid webhook body (not JSON): %s", e)
        return Response(status_code=400)

    logger.info(
        "Webhook parsed update_id=%s keys=%s",
        body.get("update_id"),
        list(body.keys()),
    )

    callback = body.get("callback_query")
    if callback:
        try:
            await handle_callback_query(callback)
        except Exception:
            logger.exception("handle_callback_query failed")
        return Response(status_code=200)

    # Telegram may send other update types; we only care about messages
    message = body.get("message") or body.get("edited_message")
    if not message:
        logger.info(
            "Webhook: no message/callback in update (ignored). update_id=%s",
            body.get("update_id"),
        )
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
            asyncio.create_task(
                _voice_pipeline_guarded(chat_id, user_id, file_id)
            )
            logger.info("Queued voice processing for chat_id=%s user_id=%s", chat_id, user_id)
        else:
            logger.warning("Voice message without file_id")
    else:
        # Non-voice message: commands
        text_raw = (message.get("text") or "").strip()
        text_lower = text_raw.lower()
        cmd0 = text_lower.split(maxsplit=1)[0].split("@")[0] if text_lower else ""
        tg = get_telegram()
        if text_lower in ("/start", "/help"):
            try:
                await tg.send_message(
                    chat_id,
                    "Send a voice message: brand, category (冻干/罐头/汤包/猫条/零食), flavor, best-by, quantity.\n\n"
                    "After saving, use Delete under the confirmation to remove a wrong row.\n"
                    "Daily digest: tap Used or /used <item_id>.",
                    parse_mode=None,
                )
            except Exception as e:
                logger.exception("Failed to send help message: %s", e)
        elif cmd0 == "/used":
            try:
                await handle_used_command(chat_id, user_id, text_raw)
            except Exception:
                logger.exception("handle_used_command failed")

    return Response(status_code=200)


@app.get("/health")
async def health() -> dict:
    """Health check for load balancers and monitoring."""
    logger.info("GET /health")
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    """Quick sanity check that the public URL hits this app."""
    return {"ok": True, "service": "telegram-bot-cft"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("ENV", "production") != "production",
    )
