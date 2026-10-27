#!/usr/bin/env python3
"""
Run the bot in polling mode for local development.

Use this when you don't have a public HTTPS URL for webhooks.
Telegram will be polled via getUpdates instead.

Usage:
    python run_polling.py

Requires .env with TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY.
"""

import asyncio
import logging
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

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


async def main() -> None:
    from main import (
        get_supabase,
        handle_callback_query,
        handle_fix_command,
        handle_pending_brand_fix_text,
        handle_used_command,
        process_voice_message,
    )
    from services.telegram_service import TelegramService, TelegramServiceError

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    tg = TelegramService(bot_token=token)

    # Remove webhook so Telegram sends updates to getUpdates
    ok = await tg.delete_webhook()
    if ok:
        logger.info("Webhook removed, using polling")
    else:
        logger.warning("Could not remove webhook (may already be unset)")

    offset = 0
    logger.info("Polling for updates... (Ctrl+C to stop)")

    while True:
        try:
            updates = await tg.get_updates(offset=offset, timeout=30)
        except TelegramServiceError as e:
            logger.error("getUpdates failed: %s", e)
            await asyncio.sleep(5)
            continue
        except Exception as e:
            # Network blips / httpx ReadTimeout on long-poll — keep running
            logger.warning("getUpdates network error (%s); retrying in 3s", e)
            await asyncio.sleep(3)
            continue

        for update in updates:
            offset = update["update_id"] + 1

            cq = update.get("callback_query")
            if cq:
                try:
                    await handle_callback_query(cq)
                except Exception:
                    logger.exception("callback_query handling failed (polling)")
                continue

            message = update.get("message") or update.get("edited_message")
            if not message:
                continue

            chat_id = message.get("chat", {}).get("id")
            user_id = message.get("from", {}).get("id")
            voice = message.get("voice")

            if not chat_id or not user_id:
                continue

            # Best-effort: persist mapping for reminders
            try:
                await get_supabase().upsert_telegram_user(
                    user_id=str(user_id), chat_id=int(chat_id)
                )
            except Exception as e:
                logger.warning("Failed to upsert telegram user mapping (polling): %s", e)

            if voice:
                file_id = voice.get("file_id")
                if file_id:
                    await process_voice_message(chat_id, user_id, file_id)
            else:
                text_raw = (message.get("text") or "").strip()
                text_lower = text_raw.lower()
                cmd0 = (
                    text_lower.split(maxsplit=1)[0].split("@")[0] if text_lower else ""
                )
                if text_lower in ("/start", "/help"):
                    from main import dashboard_public_url

                    dash = dashboard_public_url()
                    dash_line = (
                        f"\n\nWeb dashboard:\n{dash}/dashboard"
                        if dash
                        else "\n\nWeb dashboard: /dashboard on your bot host (Telegram Login)."
                    )
                    await tg.send_message(
                        chat_id,
                        "Send a voice message: brand, category (冻干/罐头/汤包/猫条/零食), flavor, best-by, quantity.\n\n"
                        "After saving: Fix (brand/qty/category) · Open −1 · Delete\n"
                        "/fix <id> · /open <id> · /used <id>."
                        + dash_line,
                        parse_mode=None,
                    )
                elif cmd0 in ("/used", "/open"):
                    await handle_used_command(chat_id, user_id, text_raw)
                elif cmd0 == "/fix":
                    await handle_fix_command(chat_id, user_id, text_raw)
                else:
                    await handle_pending_brand_fix_text(chat_id, user_id, text_raw)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped")
