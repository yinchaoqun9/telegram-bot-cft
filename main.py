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
from services.assemblyai_service import AssemblyAIService, AssemblyAIServiceError
from services.bot_i18n import t
from services.brand_catalog import get_brand_catalog
from services.brand_learning import apply_user_aliases, resolve_brand_with_user_learning
from services.brand_web_research import maybe_refine_brand_with_web_search
from services.gemini_service import GeminiService, GeminiServiceError
from services.product_category import normalize_category
from services.openai_service import OpenAIService, OpenAIServiceError
from services.supabase_service import SupabaseService, SupabaseServiceError
from services.telegram_service import TelegramService, TelegramServiceError
from dashboard_routes import router as dashboard_router

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
_assemblyai: Optional[AssemblyAIService] = None
_assemblyai_initialized: bool = False
_supabase: Optional[SupabaseService] = None
_telegram: Optional[TelegramService] = None

# user_id -> {item_id, old_brand, old_quantity, old_category} after tapping Fix
_pending_fix: dict = {}


def dashboard_public_url() -> str:
    """Optional public base URL for the inventory dashboard (shown in /start)."""
    raw = (os.environ.get("DASHBOARD_PUBLIC_URL") or "").strip().rstrip("/")
    # Avoid .../dashboard/dashboard if env already includes the path
    if raw.lower().endswith("/dashboard"):
        raw = raw[: -len("/dashboard")].rstrip("/")
    return raw


def dashboard_page_url() -> str:
    base = dashboard_public_url()
    return f"{base}/dashboard" if base else ""


async def resolve_lang(user_id: int | str) -> str:
    """Per-user UI language; default English. Does not alter stored inventory text."""
    try:
        lang = await get_supabase().get_user_lang(str(user_id))
        if isinstance(lang, str) and lang.strip():
            return lang
    except Exception:
        pass
    return "en"


async def build_welcome_message_for_user(
    user_id: int | str, *, is_start: bool = True
) -> str:
    """Localized /start and /help (default English; per-user lang)."""
    from services.bot_i18n import welcome_message

    lang = await resolve_lang(user_id)
    return welcome_message(
        lang, is_start=is_start, dashboard_url=dashboard_page_url()
    )


# Back-compat for imports / quick preview
def build_welcome_message(*, is_start: bool = True, lang: str = "en") -> str:
    from services.bot_i18n import welcome_message

    return welcome_message(
        lang, is_start=is_start, dashboard_url=dashboard_page_url()
    )


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
    # STT-only model (Interactions / generateContent transcribe API)
    transcribe_model = os.environ.get(
        "GEMINI_TRANSCRIBE_MODEL", "gemini-3.5-transcribe"
    ).strip() or "gemini-3.5-transcribe"
    # Inventory JSON extraction (must be a chat/flash model, not the STT model)
    extract_model = (
        os.environ.get("GEMINI_EXTRACT_MODEL")
        or os.environ.get("GEMINI_MODEL")
        or "gemini-2.0-flash"
    ).strip()
    _gemini = GeminiService(
        api_key=key,
        extract_model=extract_model,
        transcribe_model=transcribe_model,
    )
    return _gemini


def get_assemblyai() -> Optional[AssemblyAIService]:
    """Optional AssemblyAI client (third transcription backup)."""
    global _assemblyai, _assemblyai_initialized
    if _assemblyai_initialized:
        return _assemblyai
    _assemblyai_initialized = True
    key = os.environ.get("ASSEMBLYAI_API_KEY", "").strip()
    if not key:
        return None
    raw = os.environ.get("ASSEMBLYAI_SPEECH_MODELS", "").strip()
    models = None
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
    _assemblyai = AssemblyAIService(api_key=key, speech_models=models)
    return _assemblyai


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
            logger.info(
                "Gemini enabled (transcribe=%s extract=%s)",
                g.transcribe_model_name,
                g.model_name,
            )
        aai = get_assemblyai()
        if aai:
            logger.info("AssemblyAI transcription backup enabled")
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
app.include_router(dashboard_router)


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
    assemblyai_svc = get_assemblyai()
    supabase_svc = get_supabase()
    brand_cat = get_brand_catalog()
    lang = await resolve_lang(user_id)

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
        await tg.send_error_message(chat_id, t(lang, "err_download"))
        return
    except Exception as e:
        logger.exception("Unexpected error downloading voice: %s", e)
        await tg.send_error_message(chat_id, t(lang, "err_generic"))
        return

    if not audio_bytes or len(audio_bytes) == 0:
        logger.warning("Empty voice file received")
        await tg.send_error_message(chat_id, t(lang, "err_empty_voice"))
        return

    # 2. Transcribe: Gemini 3.5 Transcribe → OpenAI gpt-transcribe → AssemblyAI
    try:
        transcription = await transcribe_preferred(
            audio_bytes,
            "voice.ogg",
            openai_svc,
            gemini_svc,
            assemblyai_svc,
        )
    except (OpenAIServiceError, GeminiServiceError, AssemblyAIServiceError, RuntimeError) as e:
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
                t(lang, "err_ffmpeg"),
            )
        else:
            await tg.send_error_message(
                chat_id,
                t(lang, "err_transcribe"),
            )
        return
    except Exception as e:
        logger.exception("Unexpected transcription error: %s", e)
        await tg.send_error_message(chat_id, t(lang, "err_transcribe_failed"))
        return

    if not transcription or not transcription.strip():
        await tg.send_message(
            chat_id, t(lang, "err_empty_transcript")
        )
        return

    # 2b. Consume intents (open/used) skip inventory extraction
    from services.consume_intent import detect_consume_intent

    consume_action, consume_query = detect_consume_intent(transcription)
    if consume_action:
        try:
            await tg.send_message(
                chat_id,
                t(lang, "heard", text=transcription.strip()[:200]),
                parse_mode=None,
            )
        except Exception:
            logger.exception("failed to echo consume transcript")
        await apply_consume_match(chat_id, user_id, consume_action, consume_query)
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
            chat_id, t(lang, "err_extract")
        )
        return

    # Per-user learned aliases (training layer) — soft-fail if table missing
    try:
        user_aliases = await supabase_svc.list_user_brand_aliases(str(user_id))
    except Exception:
        user_aliases = []

    # Normalize items (types and empty filtering)
    items = []
    for raw in raw_items:
        brand_raw = (
            str(raw.get("brand")) if raw.get("brand") is not None else ""
        ).strip()
        brand = resolve_brand_with_user_learning(
            brand_cat, brand_raw, transcription, user_aliases
        )
        # Web fallback only when user has not already taught an alias
        if apply_user_aliases(brand_raw, user_aliases) is None:
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
        category = normalize_category(cat_raw, transcription, default="")
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
            t(lang, "err_no_items"),
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
            chat_id, t(lang, "err_save")
        )
        return
    except Exception as e:
        logger.exception("Unexpected Supabase error: %s", e)
        await tg.send_error_message(chat_id, t(lang, "err_db"))
        return

    # 5. Confirm to user (async) - handles single or multiple items + delete buttons
    try:
        await tg.send_saved_confirmation_multi(chat_id, inserted_rows, lang=lang)
        logger.info(
            "Successfully processed %d items for user=%s chat=%s",
            len(items),
            user_id,
            chat_id,
        )
        preview = ", ".join(
            (
                f"{(r.get('brand') or '').strip()} {(r.get('flavor') or '').strip()}".strip()
                or (r.get("category") or "item")
            )
            for r in inserted_rows[:3]
        )
        more = "" if len(inserted_rows) <= 3 else f" (+{len(inserted_rows) - 3} more)"
        await notify_household_partners(
            user_id,
            "partner_voice",
            n=len(inserted_rows),
            preview=preview,
            more=more,
        )
    except Exception as e:
        logger.exception("Failed to send confirmation to user: %s", e)


async def notify_household_partners(actor_user_id, msg_key: str, **kwargs) -> None:
    """
    Ping other household members who opted into change alerts.
    Each partner gets the message in *their* UI language.
    Expiry digests are always sent separately to every member (send_reminders).
    """
    try:
        partners = await get_supabase().partners_wanting_notify(str(actor_user_id))
    except Exception:
        logger.exception("partners_wanting_notify failed")
        return
    if not partners:
        return
    tg = get_telegram()
    for p in partners:
        chat_id = p.get("chat_id")
        if chat_id is None:
            continue
        plang = p.get("lang") or "en"
        text = t(plang, msg_key, **kwargs)
        try:
            await tg.send_message(int(chat_id), text, parse_mode=None)
        except Exception:
            logger.exception("partner notify failed chat_id=%s", chat_id)


async def try_delete_saved_row(user_id: int, item_id: str) -> Tuple[bool, str]:
    """Delete entire inventory row (undo mistaken save)."""
    lang = await resolve_lang(user_id)
    tid = (item_id or "").strip()
    if not tid:
        return False, t(lang, "missing_id")
    try:
        await get_supabase().delete_inventory_item(str(user_id), tid)
        await notify_household_partners(user_id, "partner_delete")
        lang = await resolve_lang(user_id)
        return True, t(lang, "deleted_ok")
    except SupabaseServiceError as e:
        return False, str(e) or "Could not delete."


async def try_decrement_inventory(user_id: int, item_id: str) -> Tuple[bool, str]:
    """Used: finish oldest open lot if any, else sealed qty −1."""
    lang = await resolve_lang(user_id)
    tid = (item_id or "").strip()
    if not tid:
        return False, t(lang, "missing_id")
    try:
        status = await get_supabase().decrement_item_quantity(
            str(user_id), tid, delta=1
        )
        await notify_household_partners(
            user_id, "partner_used", id=tid[:8]
        )
        if status == "finished_open":
            return True, t(lang, "used_finished_open")
        if status == "deleted":
            return True, t(lang, "used_deleted")
        return True, t(lang, "used_sealed")
    except SupabaseServiceError as e:
        msg = str(e) or "Could not update item."
        return False, msg


async def try_open_inventory(user_id: int, item_id: str) -> Tuple[bool, str]:
    """Open: sealed qty −1 + insert open_lots row."""
    lang = await resolve_lang(user_id)
    tid = (item_id or "").strip()
    if not tid:
        return False, t(lang, "missing_id")
    try:
        status = await get_supabase().open_item(str(user_id), tid, delta=1)
        await notify_household_partners(
            user_id, "partner_open", id=tid[:8]
        )
        if status == "deleted":
            return True, t(lang, "opened_last")
        return True, t(lang, "opened_ok")
    except SupabaseServiceError as e:
        return False, str(e) or "Could not update item."


def _item_label(row: dict) -> str:
    brand = (row.get("brand") or "").strip()
    flavor = (row.get("flavor") or "").strip()
    cat = (row.get("category") or "").strip()
    qty = int(row.get("quantity") or 0)
    open_n = int(row.get("open_lots_count") or (1 if row.get("has_open_lot") else 0))
    bits = [x for x in (brand, flavor) if x]
    name = " ".join(bits) or "item"
    cpre = f"[{cat}] " if cat else ""
    open_bit = f", open×{open_n}" if open_n else ""
    return f"{cpre}{name} (qty {qty}{open_bit})"


def _consume_pick_keyboard(
    action: str, candidates: list, *, lang: str = "en"
) -> tuple:
    """Build (text_lines_extra_unused, inline_keyboard) for open/used picks."""
    prefix = "o:" if action == "open" else "u:"
    verb = t(lang, "open_verb") if action == "open" else t(lang, "used_verb")
    keyboard = []
    for row in candidates:
        iid = str(row.get("id") or "")
        if not iid:
            continue
        brand = ((row.get("brand") or "") + " " + (row.get("flavor") or "")).strip()
        label = f"{verb} {brand}".strip()[:40] or verb
        cb = f"{prefix}{iid}"
        if len(cb.encode("utf-8")) > 64:
            continue
        keyboard.append([{"text": label, "callback_data": cb}])
    return keyboard


async def _send_consume_pick(
    chat_id: int, action: str, candidates: list, *, header: str, lang: str = "en"
) -> None:
    tg = get_telegram()
    keyboard = _consume_pick_keyboard(action, candidates, lang=lang)
    text = header + "\n" + "\n".join(f"• {_item_label(r)}" for r in candidates)
    if keyboard:
        await tg.send_message_with_inline_keyboard(
            chat_id, text, keyboard, parse_mode=None
        )
    else:
        await tg.send_message(chat_id, text, parse_mode=None)


async def apply_consume_match(
    chat_id: int, user_id: int, action: str, query: str
) -> bool:
    """
    Match pantry rows for open|used from voice/text.
    Returns True if a consume reply was sent (caller should skip inventory extract).
    Soft (no score hit) candidates never auto-apply — buttons only.
    """
    from services.inventory_match import score_item, suggest_consume_candidates

    tg = get_telegram()
    lang = await resolve_lang(user_id)
    items = await get_supabase().list_inventory_for_user(str(user_id))
    candidates, strict = suggest_consume_candidates(
        items, query, action=action, limit=3
    )
    if not candidates:
        qshow = query or action
        if not items:
            msg = t(lang, "consume_empty")
        elif action == "open":
            msg = t(lang, "consume_no_open", query=qshow)
        else:
            msg = t(lang, "consume_no_used", query=qshow)
        await tg.send_message(chat_id, msg, parse_mode=None)
        return True

    if not strict:
        qshow = (query or "").strip() or action
        await _send_consume_pick(
            chat_id,
            action,
            candidates,
            header=t(lang, "consume_soft_header", query=qshow),
            lang=lang,
        )
        return True

    top = candidates[0]
    # Auto-apply only for strict hits: single hit, or clear winner vs runner-up
    auto = len(candidates) == 1
    if not auto and len(candidates) >= 2:
        s0 = score_item(query, candidates[0])
        s1 = score_item(query, candidates[1])
        auto = bool(query.strip()) and s0 >= s1 + 25 and s0 >= 40

    if auto:
        iid = str(top.get("id") or "")
        if action == "open":
            ok, detail = await try_open_inventory(user_id, iid)
        else:
            ok, detail = await try_decrement_inventory(user_id, iid)
        label = _item_label(top)
        verb = t(lang, "open_verb") if action == "open" else t(lang, "used_verb")
        await tg.send_message(
            chat_id,
            t(lang, "consume_done", verb=verb, label=label, detail=detail)
            if ok
            else t(lang, "consume_fail", detail=detail),
            parse_mode=None,
        )
        return True

    act = t(lang, "action_open") if action == "open" else t(lang, "action_used")
    await _send_consume_pick(
        chat_id,
        action,
        candidates,
        header=t(lang, "consume_which", action=act),
        lang=lang,
    )
    return True


async def handle_consume_text(chat_id: int, user_id: int, text: str) -> bool:
    """If text is open/used intent, handle and return True."""
    from services.consume_intent import detect_consume_intent

    action, query = detect_consume_intent(text or "")
    if not action:
        return False
    return await apply_consume_match(chat_id, user_id, action, query)


def _sort_pantry_browse(items: list) -> list:
    """Open lots first, then soonest best_by, then higher qty."""

    def key(it: dict):
        has_open = 0 if it.get("has_open_lot") else 1
        bb = str(it.get("best_by") or "9999-99-99")
        return (has_open, bb, -(int(it.get("quantity") or 0)))

    return sorted(items, key=key)


def _open_used_row_buttons(r: dict, *, lang: str = "en") -> list:
    iid = str(r.get("id") or "")
    if not iid:
        return []
    brand = ((r.get("brand") or "") + " " + (r.get("flavor") or "")).strip()[:18]
    open_v = t(lang, "open_verb")
    used_v = t(lang, "used_verb")
    row_btns = []
    if int(r.get("quantity") or 0) > 0:
        cb_o = f"o:{iid}"
        if len(cb_o.encode("utf-8")) <= 64:
            label = f"{open_v} {brand}".strip()[:40] or open_v
            row_btns.append({"text": label, "callback_data": cb_o})
    cb_u = f"u:{iid}"
    if len(cb_u.encode("utf-8")) <= 64:
        label = f"{used_v} {brand}".strip()[:40] or used_v
        row_btns.append({"text": label, "callback_data": cb_u})
    return row_btns


async def handle_today_command(chat_id: int, user_id: int) -> None:
    """Suggest up to 3 eatable items for today (open lots first)."""
    from services.inventory_match import pick_eat_today

    tg = get_telegram()
    lang = await resolve_lang(user_id)
    items = await get_supabase().list_inventory_for_user(str(user_id))
    picks = pick_eat_today(items, limit=3)
    if not picks:
        if items:
            msg = t(lang, "today_empty_food")
        else:
            msg = t(lang, "today_empty")
        await tg.send_message(chat_id, msg, parse_mode=None)
        return
    lines = [t(lang, "today_header")]
    keyboard = []
    for r in picks:
        lines.append(f"• {_item_label(r)}")
        row_btns = _open_used_row_buttons(r, lang=lang)
        if row_btns:
            keyboard.append(row_btns)
    text = "\n".join(lines)
    if keyboard:
        await tg.send_message_with_inline_keyboard(
            chat_id, text, keyboard, parse_mode=None
        )
    else:
        await tg.send_message(chat_id, text, parse_mode=None)


async def handle_list_command(chat_id: int, user_id: int) -> None:
    """Browse pantry in Telegram (capped) with Open/Used buttons."""
    tg = get_telegram()
    lang = await resolve_lang(user_id)
    items = await get_supabase().list_inventory_for_user(str(user_id))
    if not items:
        await tg.send_message(
            chat_id,
            t(lang, "list_empty"),
            parse_mode=None,
        )
        return

    # Telegram keyboard practicality: ~12 rows with Open+Used
    cap = 12
    ordered = _sort_pantry_browse(items)
    shown = ordered[:cap]
    more = len(ordered) - len(shown)

    lines = [t(lang, "list_header", n=len(ordered))]
    keyboard = []
    for r in shown:
        lines.append(f"• {_item_label(r)}")
        row_btns = _open_used_row_buttons(r, lang=lang)
        if row_btns:
            keyboard.append(row_btns)

    if more > 0:
        dash = dashboard_page_url()
        extra = (
            t(lang, "list_more_dash", n=more, url=dash)
            if dash
            else t(lang, "list_more", n=more)
        )
        lines.append(extra)
    lines.append(t(lang, "list_footer"))

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3850] + "\n…"

    if keyboard:
        await tg.send_message_with_inline_keyboard(
            chat_id, text, keyboard, parse_mode=None
        )
    else:
        await tg.send_message(chat_id, text, parse_mode=None)


async def start_item_fix(user_id: int, item_id: str) -> str:
    """Arm pending Fix; next text auto-detects brand / quantity / category."""
    lang = await resolve_lang(user_id)
    tid = (item_id or "").strip()
    if not tid:
        return t(lang, "missing_id")
    row = await get_supabase().get_inventory_item(str(user_id), tid)
    if not row:
        return t(lang, "item_not_found")
    old_brand = (row.get("brand") or "").strip()
    old_qty = row.get("quantity")
    old_cat = (row.get("category") or "").strip()
    _pending_fix[str(user_id)] = {
        "item_id": tid,
        "old_brand": old_brand,
        "old_quantity": old_qty,
        "old_category": old_cat,
    }
    return t(
        lang,
        "fix_prompt",
        brand=old_brand or "—",
        qty=old_qty,
        cat=old_cat or "—",
    )


async def apply_parsed_fix(
    user_id: int,
    item_id: str,
    patch: dict,
    *,
    old_brand: str = "",
    field: str | None = None,
) -> Tuple[bool, str]:
    """Apply Fix patch (one or more fields); learn brand aliases when brand changes."""
    lang = await resolve_lang(user_id)
    tid = (item_id or "").strip()
    if not tid or not patch:
        return False, t(lang, "consume_fail", detail="nothing to update")
    # Legacy callers sometimes passed a single-field name; ignore if patch is full
    _ = field
    sb = get_supabase()
    try:
        existing = await sb.get_inventory_item(str(user_id), tid)
        if not existing:
            return False, t(lang, "item_not_found")
        if "brand" in patch and not old_brand:
            old_brand = (existing.get("brand") or "").strip()
        await sb.update_inventory_fields(str(user_id), tid, patch)
    except SupabaseServiceError as e:
        return False, str(e) or "Could not update."

    bits: list = []
    if "brand" in patch:
        nb = str(patch.get("brand") or "").strip()
        if old_brand and nb and old_brand.lower() != nb.lower():
            await sb.upsert_user_brand_alias(str(user_id), old_brand, nb)
        await sb.log_brand_correction(
            str(user_id),
            item_id=tid,
            old_value=old_brand,
            new_value=nb,
            field="brand",
        )
        bits.append(f"brand → {nb}")
    if "quantity" in patch:
        q = patch.get("quantity")
        await sb.log_brand_correction(
            str(user_id),
            item_id=tid,
            old_value=str(existing.get("quantity")),
            new_value=str(q),
            field="quantity",
        )
        bits.append(f"quantity → {q}")
    if "category" in patch:
        c = str(patch.get("category") or "")
        await sb.log_brand_correction(
            str(user_id),
            item_id=tid,
            old_value=str(existing.get("category") or ""),
            new_value=c,
            field="category",
        )
        bits.append(f"category → {c}")

    msg = t(lang, "fix_updated", bits=", ".join(bits))
    if "brand" in patch:
        msg += t(lang, "fix_learned")
    return True, msg


async def handle_pending_fix_text(chat_id: int, user_id: int, text: str) -> bool:
    """If user tapped Fix, parse next message as brand/qty/category. Returns True if consumed."""
    from services.fix_parse import parse_fix_patch

    pending = _pending_fix.pop(str(user_id), None)
    if not pending:
        return False
    raw = (text or "").strip()
    tg = get_telegram()
    lang = await resolve_lang(user_id)
    if raw.lower() in ("/cancel", "cancel"):
        try:
            await tg.send_message(chat_id, t(lang, "fix_cancelled"), parse_mode=None)
        except Exception:
            logger.exception("send_message failed")
        return True
    patch = parse_fix_patch(raw)
    if not patch:
        # re-arm so they can try again
        _pending_fix[str(user_id)] = pending
        try:
            await tg.send_message(
                chat_id,
                t(lang, "fix_parse_fail"),
                parse_mode=None,
            )
        except Exception:
            logger.exception("send_message failed")
        return True
    ok, detail = await apply_parsed_fix(
        user_id,
        pending.get("item_id") or "",
        patch,
        old_brand=pending.get("old_brand") or "",
    )
    try:
        await tg.send_message(
            chat_id,
            detail if ok else t(lang, "consume_fail", detail=detail),
            parse_mode=None,
        )
    except Exception:
        logger.exception("send_message failed after fix")
    return True


# Back-compat names used by imports
async def handle_pending_brand_fix_text(
    chat_id: int, user_id: int, text: str
) -> bool:
    return await handle_pending_fix_text(chat_id, user_id, text)


async def apply_user_language(chat_id: int, user_id: int, lang: str) -> None:
    from services.bot_i18n import language_set_confirm, normalize_lang

    tg = get_telegram()
    code = normalize_lang(lang)
    try:
        await get_supabase().upsert_telegram_user(
            user_id=str(user_id), chat_id=int(chat_id)
        )
        saved = await get_supabase().set_user_lang(str(user_id), code)
    except SupabaseServiceError as e:
        ulang = await resolve_lang(user_id)
        await tg.send_message(
            chat_id,
            t(ulang, "lang_need_sql", detail=str(e)),
            parse_mode=None,
        )
        return
    await tg.send_message(
        chat_id, language_set_confirm(saved), parse_mode=None
    )


async def handle_language_command(chat_id: int, user_id: int, text: str) -> None:
    """
    /language | /lang
    /language en | zh
    """
    from services.bot_i18n import language_prompt, normalize_lang

    tg = get_telegram()
    parts = (text or "").strip().split()
    arg = parts[1].lower() if len(parts) > 1 else ""
    if arg in ("en", "english", "eng"):
        await apply_user_language(chat_id, user_id, "en")
        return
    if arg in ("zh", "cn", "chinese", "中文"):
        await apply_user_language(chat_id, user_id, "zh")
        return

    try:
        lang = await get_supabase().get_user_lang(str(user_id))
    except Exception:
        lang = "en"
    keyboard = [
        [
            {"text": "English", "callback_data": "lang:en"},
            {"text": "中文", "callback_data": "lang:zh"},
        ]
    ]
    await tg.send_message_with_inline_keyboard(
        chat_id, language_prompt(lang), keyboard, parse_mode=None
    )


async def handle_callback_query(callback: dict) -> None:
    """Inline: d: delete; u:/o: open−1; f: start brand fix; lang: locale."""
    cq_id = callback.get("id")
    from_user = callback.get("from") or {}
    user_id = from_user.get("id")
    data = (callback.get("data") or "").strip()
    if not cq_id or not user_id:
        return
    tg = get_telegram()
    if data.startswith("lang:"):
        code = data.split(":", 1)[1].strip()
        chat = (callback.get("message") or {}).get("chat") or {}
        chat_id = chat.get("id")
        try:
            await tg.answer_callback_query(cq_id, text="OK", show_alert=False)
        except Exception:
            logger.exception("answerCallbackQuery failed after lang")
        if chat_id:
            await apply_user_language(int(chat_id), int(user_id), code)
        return
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
    if data.startswith("u:") or data.startswith("o:"):
        item_id = data[2:].strip()
        if data.startswith("o:"):
            ok, detail = await try_open_inventory(int(user_id), item_id)
        else:
            ok, detail = await try_decrement_inventory(int(user_id), item_id)
        try:
            await tg.answer_callback_query(
                cq_id,
                text=detail[:200],
                show_alert=not ok,
            )
        except Exception:
            logger.exception("answerCallbackQuery failed after open/used")
        return
    if data.startswith("f:"):
        item_id = data[2:].strip()
        detail = await start_item_fix(int(user_id), item_id)
        try:
            await tg.answer_callback_query(cq_id, text="Fix…", show_alert=False)
        except Exception:
            logger.exception("answerCallbackQuery failed after fix arm")
        # Message in chat is clearer than alert for the follow-up instruction
        chat = (callback.get("message") or {}).get("chat") or {}
        chat_id = chat.get("id")
        if chat_id:
            try:
                await tg.send_message(chat_id, detail, parse_mode=None)
            except Exception:
                logger.exception("send_message failed for fix prompt")
        return
    try:
        await tg.answer_callback_query(
            cq_id, text="Unknown action.", show_alert=True
        )
    except Exception:
        logger.exception("answerCallbackQuery failed")


async def handle_household_command(chat_id: int, user_id: int, text: str) -> None:
    """
    /household — status or create
    /join CODE — join shared pantry
    /leave — leave pantry
    /notify on|off — partner change alerts (digest always on for both)
    """
    from services.household_service import HouseholdError, free_max_members

    tg = get_telegram()
    lang = await resolve_lang(user_id)
    raw = (text or "").strip()
    parts = raw.split()
    cmd = parts[0].split("@")[0].lower() if parts else ""
    supa = get_supabase()

    try:
        if cmd == "/join":
            code = parts[1] if len(parts) > 1 else ""
            if not code:
                await tg.send_message(
                    chat_id,
                    t(lang, "hh_join_usage"),
                    parse_mode=None,
                )
                return
            summary = await supa.join_household(str(user_id), code)
            await tg.send_message(
                chat_id,
                t(
                    lang,
                    "hh_joined",
                    code=summary.get("invite_code"),
                    n=summary.get("member_count"),
                    max=summary.get("max_members"),
                ),
                parse_mode=None,
            )
            return

        if cmd == "/leave":
            msg = await supa.leave_household(str(user_id))
            await tg.send_message(chat_id, msg, parse_mode=None)
            return

        if cmd == "/notify":
            arg = (parts[1] if len(parts) > 1 else "").lower()
            if arg not in ("on", "off"):
                await tg.send_message(
                    chat_id,
                    t(lang, "hh_notify_usage"),
                    parse_mode=None,
                )
                return
            enabled = arg == "on"
            await supa.set_notify_partner(str(user_id), enabled)
            await tg.send_message(
                chat_id,
                t(lang, "hh_notify_on" if enabled else "hh_notify_off"),
                parse_mode=None,
            )
            return

        # /household
        summary = await supa.get_household_summary(str(user_id))
        if summary:
            alerts = t(
                lang,
                "hh_alerts_on"
                if summary.get("notify_partner_changes")
                else "hh_alerts_off",
            )
            await tg.send_message(
                chat_id,
                t(
                    lang,
                    "hh_status",
                    code=summary.get("invite_code"),
                    n=summary.get("member_count"),
                    max=summary.get("max_members"),
                    free=free_max_members(),
                    alerts=alerts,
                ),
                parse_mode=None,
            )
            return
        summary = await supa.create_household(str(user_id))
        await tg.send_message(
            chat_id,
            t(
                lang,
                "hh_created",
                code=summary.get("invite_code"),
            ),
            parse_mode=None,
        )
    except HouseholdError as e:
        await tg.send_message(chat_id, str(e), parse_mode=None)
    except SupabaseServiceError as e:
        await tg.send_message(
            chat_id, t(lang, "hh_error", detail=str(e)), parse_mode=None
        )
    except Exception as e:
        logger.exception("household command failed: %s", e)
        await tg.send_message(
            chat_id,
            t(lang, "hh_tables_missing"),
            parse_mode=None,
        )


async def handle_used_command(chat_id: int, user_id: int, text: str) -> None:
    """Parse /used or /open <item_id> (supports @BotName)."""
    raw = (text or "").strip()
    parts = raw.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower() if parts else ""
    if cmd not in ("/used", "/open"):
        return
    tg = get_telegram()
    lang = await resolve_lang(user_id)
    if len(parts) < 2 or not parts[1].strip():
        try:
            await tg.send_message(
                chat_id,
                t(lang, "open_used_usage", cmd=cmd),
                parse_mode=None,
            )
        except Exception as e:
            logger.exception("send_message failed: %s", e)
        return
    item_id = parts[1].strip()
    if cmd == "/open":
        ok, detail = await try_open_inventory(user_id, item_id)
    else:
        ok, detail = await try_decrement_inventory(user_id, item_id)
    try:
        await tg.send_message(
            chat_id,
            detail if ok else t(lang, "consume_fail", detail=detail),
            parse_mode=None,
        )
    except Exception as e:
        logger.exception("send_message failed: %s", e)


async def handle_fix_command(chat_id: int, user_id: int, text: str) -> None:
    """
    /fix <item_id> → then send correction
    /fix brand|quantity|category <item_id> <value…>
    """
    from services.fix_parse import parse_fix_patch

    raw = (text or "").strip()
    parts = raw.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower() if parts else ""
    if cmd != "/fix":
        return
    tg = get_telegram()
    lang = await resolve_lang(user_id)
    rest = parts[1].strip() if len(parts) > 1 else ""
    if not rest:
        try:
            await tg.send_message(
                chat_id,
                t(lang, "fix_usage"),
                parse_mode=None,
            )
        except Exception as e:
            logger.exception("send_message failed: %s", e)
        return
    tokens = rest.split(maxsplit=2)
    # /fix brand|quantity|category <uuid> <value…>
    if tokens[0].lower() in ("brand", "quantity", "category", "qty") and len(tokens) >= 3:
        kind = tokens[0].lower()
        if kind == "qty":
            kind = "quantity"
        item_id, value = tokens[1], tokens[2]
        patch = parse_fix_patch(f"{kind} {value}")
        if not patch:
            try:
                await tg.send_message(
                    chat_id, t(lang, "fix_parse_that"), parse_mode=None
                )
            except Exception as e:
                logger.exception("send_message failed: %s", e)
            return
        ok, detail = await apply_parsed_fix(user_id, item_id, patch)
        try:
            await tg.send_message(
                chat_id,
                detail if ok else t(lang, "consume_fail", detail=detail),
                parse_mode=None,
            )
        except Exception as e:
            logger.exception("send_message failed: %s", e)
        return
    # /fix <uuid> → arm pending
    if len(tokens) == 1:
        detail = await start_item_fix(user_id, tokens[0])
        try:
            await tg.send_message(chat_id, detail, parse_mode=None)
        except Exception as e:
            logger.exception("send_message failed: %s", e)
        return
    try:
        await tg.send_message(
            chat_id,
            t(lang, "fix_usage_short"),
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
            lang = await resolve_lang(user_id)
            await get_telegram().send_error_message(
                chat_id,
                t(lang, "pipeline_crash"),
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
        if cmd0 in ("/start", "/help"):
            try:
                await tg.send_message(
                    chat_id,
                    await build_welcome_message_for_user(
                        user_id, is_start=(cmd0 == "/start")
                    ),
                    parse_mode=None,
                )
            except Exception as e:
                logger.exception("Failed to send help message: %s", e)
        elif cmd0 in ("/language", "/lang"):
            try:
                await handle_language_command(chat_id, user_id, text_raw)
            except Exception:
                logger.exception("handle_language_command failed")
        elif cmd0 in ("/used", "/open"):
            try:
                await handle_used_command(chat_id, user_id, text_raw)
            except Exception:
                logger.exception("handle_used_command failed")
        elif cmd0 == "/today":
            try:
                await handle_today_command(chat_id, user_id)
            except Exception:
                logger.exception("handle_today_command failed")
        elif cmd0 in ("/list", "/pantry"):
            try:
                await handle_list_command(chat_id, user_id)
            except Exception:
                logger.exception("handle_list_command failed")
        elif cmd0 in ("/household", "/join", "/leave", "/notify"):
            try:
                await handle_household_command(chat_id, user_id, text_raw)
            except Exception:
                logger.exception("handle_household_command failed")
        elif cmd0 == "/fix":
            try:
                await handle_fix_command(chat_id, user_id, text_raw)
            except Exception:
                logger.exception("handle_fix_command failed")
        elif cmd0 in ("/dashboard", "dashboard"):
            try:
                lang = await resolve_lang(user_id)
                dash = dashboard_page_url()
                if dash:
                    await tg.send_message(
                        chat_id,
                        t(lang, "dashboard_link", url=dash),
                        parse_mode=None,
                    )
                else:
                    await tg.send_message(
                        chat_id,
                        t(lang, "dashboard_missing"),
                        parse_mode=None,
                    )
            except Exception:
                logger.exception("dashboard hint failed")
        else:
            try:
                if await handle_consume_text(chat_id, user_id, text_raw):
                    pass
                elif await handle_pending_brand_fix_text(chat_id, user_id, text_raw):
                    pass
                elif text_raw.startswith("/"):
                    lang = await resolve_lang(user_id)
                    await tg.send_message(
                        chat_id,
                        t(lang, "unknown_cmd"),
                        parse_mode=None,
                    )
            except Exception:
                logger.exception("pending fix / consume text failed")

    return Response(status_code=200)


@app.get("/health")
async def health() -> dict:
    """Health check for load balancers and monitoring."""
    logger.info("GET /health")
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    """Quick sanity check that the public URL hits this app."""
    return {
        "ok": True,
        "service": "telegram-bot-cft",
        "dashboard": "/dashboard",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=os.environ.get("ENV", "production") != "production",
    )
