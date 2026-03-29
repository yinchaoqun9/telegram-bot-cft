#!/usr/bin/env python3
"""
Daily reminder job (private chat).

Sends reminders to users when items are expiring in N days (default: 7, 3, 1).

How it works:
- Looks for rows in cat_inventory where best_by == today + offset_days
- Skips rows already reminded for that offset (reminded_offsets contains offset)
- Looks up chat_id from telegram_users mapping
- Sends Telegram message and marks reminded_offsets

Run manually:
    python send_reminders.py

Schedule (examples):
    - cron daily at 09:00: 0 9 * * * /path/to/python /path/to/send_reminders.py
"""

import asyncio
import logging
import os
from datetime import date, timedelta

from dotenv import load_dotenv

from services.supabase_service import SupabaseService
from services.telegram_service import TelegramService

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Reduce noisy HTTP client logs (can include sensitive URLs)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)


def _parse_offsets() -> list[int]:
    raw = os.environ.get("REMINDER_OFFSETS_DAYS", "7,3,1")
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return sorted(set(out), reverse=True)


async def main() -> None:
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")

    if not supabase_url or not supabase_key or not tg_token:
        raise RuntimeError("Missing SUPABASE_URL, SUPABASE_SERVICE_KEY, or TELEGRAM_BOT_TOKEN")

    supa = SupabaseService(url=supabase_url, service_key=supabase_key)
    tg = TelegramService(bot_token=tg_token)

    offsets = _parse_offsets()
    today = date.today()

    total_sent = 0
    for offset in offsets:
        target = today + timedelta(days=offset)
        rows = await supa.get_expiring_items(target_date=target, offset_days=offset, limit=500)
        if not rows:
            continue

        for r in rows:
            chat_id = r.get("chat_id")
            item_id = r.get("id")
            brand = r.get("brand") or ""
            flavor = r.get("flavor") or ""
            best_by = r.get("best_by") or ""
            qty = int(r.get("quantity") or 0)

            msg = (
                f"⏰ Reminder: {brand} {flavor} expires in {offset} day(s) "
                f"on {best_by}. Quantity: {qty}"
            )

            try:
                await tg.send_message(chat_id, msg)
                await supa.mark_reminded(item_id=item_id, offset_days=offset)
                total_sent += 1
            except Exception as e:
                logger.exception("Failed sending reminder for item_id=%s: %s", item_id, e)

    logger.info("Reminder job done. sent=%d", total_sent)


if __name__ == "__main__":
    asyncio.run(main())

