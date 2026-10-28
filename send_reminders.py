#!/usr/bin/env python3
"""
Daily digest: expiring inventory grouped by window (0–7 days vs 8–15 days).

For each user in telegram_users with matching rows, sends one message with
optional inline "Used" buttons (see REMINDER_DIGEST_MAX_BUTTONS).

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
    cpre = f"[{cat}] " if cat else ""
    line = f"• {cpre}{brand} {flavor} — {best_by} — qty {qty}"
    if iid:
        line += f"\n  id: {iid}"
    return line


def _build_digest_text(
    within_7: List[Dict[str, Any]],
    within_8_15: List[Dict[str, Any]],
    window_days: int,
    button_cap: int,
    with_buttons: List[Dict[str, Any]],
) -> str:
    parts: List[str] = []
    if within_7:
        parts.append("⏰ Expiring within 7 days:")
        parts.extend(_format_item_line(r) for r in within_7)
    if within_8_15:
        if parts:
            parts.append("")
        parts.append(f"⏰ Expiring in 8–{window_days} days:")
        parts.extend(_format_item_line(r) for r in within_8_15)

    total_items = len(within_7) + len(within_8_15)
    if total_items > len(with_buttons):
        parts.append("")
        parts.append(
            f"Use buttons for the first {len(with_buttons)} items, or send:\n"
            "/used <item_id>\n"
            "(copy id from the line under each item above.)"
        )
    return "\n".join(parts)


def _items_for_buttons(
    within_7: List[Dict[str, Any]],
    within_8_15: List[Dict[str, Any]],
    cap: int,
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
        label = f"Used −1 {brand}".strip() if brand else "Used −1"
        if len(label) > 40:
            label = label[:37] + "…"
        keyboard.append([{"text": label, "callback_data": cb}])
    return ordered, keyboard


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
        if not within_7 and not within_8_15:
            continue

        with_buttons, keyboard = _items_for_buttons(within_7, within_8_15, btn_cap)
        text = _build_digest_text(
            within_7, within_8_15, window, btn_cap, with_buttons
        )

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
