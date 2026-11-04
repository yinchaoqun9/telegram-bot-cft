#!/usr/bin/env python3
"""
Daily digest: expiring inventory grouped by window (0–7 days vs 8–15 days).

When nothing is in the expiry windows, send an optional “eat today” top-3
of eatable pantry items (open lots first).

For each user in telegram_users with matching rows, sends one message with
optional inline "Used"/"Open" buttons (see REMINDER_DIGEST_MAX_BUTTONS).

Household members each receive the same shared-pantry digest (always on).
Partner alerts for voice/Open/Used are separate and opt-in via /notify.

Run manually:
    python send_reminders.py

Schedule (e.g. daily 09:00 server time):
    0 9 * * * cd /app && python send_reminders.py
"""

import asyncio
import logging
import os
from datetime import date
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv

from services.bot_i18n import lang_from_user_row, t
from services.inventory_match import pick_eat_today
from services.supabase_service import SupabaseService
from services.telegram_service import TelegramService

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)


def _window_days() -> int:
    try:
        return max(7, int(os.environ.get("REMINDER_MAX_DAYS", "15")))
    except ValueError:
        return 15


def _max_buttons() -> int:
    try:
        return max(1, min(100, int(os.environ.get("REMINDER_DIGEST_MAX_BUTTONS", "18"))))
    except ValueError:
        return 18


def _format_item_line(r: Dict[str, Any]) -> str:
    brand = (r.get("brand") or "").strip()
    flavor = (r.get("flavor") or "").strip()
    cat = (r.get("category") or "").strip()
    best_by = r.get("best_by") or ""
    qty = int(r.get("quantity") or 0)
    iid = str(r.get("id") or "")
    open_n = int(r.get("open_lots_count") or (1 if r.get("has_open_lot") else 0))
    cpre = f"[{cat}] " if cat else ""
    open_bit = f" · open×{open_n}" if open_n else ""
    line = f"• {cpre}{brand} {flavor} — {best_by} — qty {qty}{open_bit}"
    if iid:
        line += f"\n  id: {iid}"
    return line


def _build_digest_text(
    within_7: List[Dict[str, Any]],
    within_8_15: List[Dict[str, Any]],
    window_days: int,
    button_cap: int,
    with_buttons: List[Dict[str, Any]],
    *,
    lang: str = "en",
) -> str:
    parts: List[str] = []
    if within_7:
        parts.append(t(lang, "digest_7"))
        parts.extend(_format_item_line(r) for r in within_7)
    if within_8_15:
        if parts:
            parts.append("")
        parts.append(t(lang, "digest_8n", n=window_days))
        parts.extend(_format_item_line(r) for r in within_8_15)

    total_items = len(within_7) + len(within_8_15)
    if total_items > len(with_buttons):
        parts.append("")
        parts.append(t(lang, "digest_buttons_hint", n=len(with_buttons)))
    return "\n".join(parts)


def _items_for_buttons(
    within_7: List[Dict[str, Any]],
    within_8_15: List[Dict[str, Any]],
    cap: int,
    *,
    lang: str = "en",
) -> Tuple[List[Dict[str, Any]], List[List[Dict[str, str]]]]:
    """Ordered list of rows that get a button + inline_keyboard rows (one button each)."""
    ordered: List[Dict[str, Any]] = []
    for r in within_7:
        if len(ordered) >= cap:
            break
        ordered.append(r)
    for r in within_8_15:
        if len(ordered) >= cap:
            break
        ordered.append(r)

    keyboard: List[List[Dict[str, str]]] = []
    for r in ordered:
        iid = str(r.get("id") or "")
        if not iid:
            continue
        cb = f"u:{iid}"
        if len(cb.encode("utf-8")) > 64:
            logger.warning("callback_data too long for item id=%s, skipping button", iid[:8])
            continue
        brand = ((r.get("brand") or "") + " " + (r.get("flavor") or "")).strip()[:24]
        used = t(lang, "used_verb")
        label = f"{used} −1 {brand}".strip() if brand else f"{used} −1"
        if len(label) > 40:
            label = label[:37] + "…"
        keyboard.append([{"text": label, "callback_data": cb}])
    return ordered, keyboard


def _build_eat_today(
    picks: List[Dict[str, Any]],
    *,
    lang: str = "en",
) -> Tuple[str, List[List[Dict[str, str]]]]:
    lines = [t(lang, "eat_today_intro")]
    keyboard: List[List[Dict[str, str]]] = []
    open_v = t(lang, "open_verb")
    used_v = t(lang, "used_verb")
    for r in picks:
        lines.append(_format_item_line(r))
        iid = str(r.get("id") or "")
        if not iid:
            continue
        brand = ((r.get("brand") or "") + " " + (r.get("flavor") or "")).strip()[:18]
        row_btns: List[Dict[str, str]] = []
        if int(r.get("quantity") or 0) > 0:
            cb_o = f"o:{iid}"
            if len(cb_o.encode("utf-8")) <= 64:
                label = f"{open_v} {brand}".strip()[:40] or open_v
                row_btns.append({"text": label, "callback_data": cb_o})
        cb_u = f"u:{iid}"
        if len(cb_u.encode("utf-8")) <= 64:
            label = f"{used_v} {brand}".strip()[:40] or used_v
            row_btns.append({"text": label, "callback_data": cb_u})
        if row_btns:
            keyboard.append(row_btns)
    lines.append(t(lang, "eat_today_footer"))
    return "\n".join(lines), keyboard


async def main() -> None:
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not supabase_url or not supabase_key or not tg_token:
        raise RuntimeError("Missing SUPABASE_URL, SUPABASE_SERVICE_KEY, or TELEGRAM_BOT_TOKEN")

    supa = SupabaseService(url=supabase_url, service_key=supabase_key)
    tg = TelegramService(bot_token=tg_token)

    today = date.today()
    window = _window_days()
    btn_cap = _max_buttons()

    users = await supa.list_telegram_users()
    total_sent = 0

    for u in users:
        uid = str(u.get("user_id") or "")
        chat_id = u.get("chat_id")
        if not uid or chat_id is None:
            continue

        within_7, within_8_15 = await supa.get_digest_buckets_for_user(
            uid, today, window_days=window
        )
        lang = lang_from_user_row(u)
        if within_7 or within_8_15:
            with_buttons, keyboard = _items_for_buttons(
                within_7, within_8_15, btn_cap, lang=lang
            )
            text = _build_digest_text(
                within_7, within_8_15, window, btn_cap, with_buttons, lang=lang
            )
        else:
            try:
                items = await supa.list_inventory_for_user(uid)
            except Exception as e:
                logger.warning("list inventory for eat-today failed user=%s: %s", uid, e)
                continue
            picks = pick_eat_today(items, limit=3)
            if not picks:
                continue
            text, keyboard = _build_eat_today(picks, lang=lang)

        try:
            if keyboard:
                await tg.send_message_with_inline_keyboard(
                    int(chat_id), text, keyboard, parse_mode=None
                )
            else:
                await tg.send_message(int(chat_id), text, parse_mode=None)
            total_sent += 1
        except Exception as e:
            logger.exception("Failed digest for user_id=%s: %s", uid, e)

    logger.info("Reminder digest done. messages_sent=%d", total_sent)


if __name__ == "__main__":
    asyncio.run(main())
