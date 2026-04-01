"""
Telegram Service - Handles Telegram Bot API interactions.

- Download voice files via getFile
- Send confirmation messages to users
- All operations are async for non-blocking I/O.
"""

import logging
from typing import Any, Dict, List, Optional, Union

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org/bot"


class TelegramServiceError(Exception):
    """Raised when Telegram API returns an error or request fails."""

    pass


class TelegramService:
    """Service for Telegram Bot API operations (async)."""

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"{TELEGRAM_API_BASE}{bot_token}"

    async def get_file_path(self, file_id: str) -> str:
        """
        Get the file path for downloading a Telegram file.

        Args:
            file_id: Telegram file_id from the voice message

        Returns:
            file_path to use with getFile download URL

        Raises:
            TelegramServiceError: On API errors
            httpx.HTTPStatusError: On HTTP errors
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/getFile", params={"file_id": file_id}
                )
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPStatusError as e:
                logger.error("Telegram getFile failed: status=%s body=%s", e.response.status_code, e.response.text)
                raise
            except Exception as e:
                logger.exception("Unexpected error in get_file_path: %s", e)
                raise TelegramServiceError(f"Failed to get file path: {e}") from e

        if not data.get("ok"):
            logger.error("Telegram API returned ok=false: %s", data)
            raise TelegramServiceError(f"Telegram API error: {data.get('description', data)}")

        file_path = data.get("result", {}).get("file_path")
        if not file_path:
            raise TelegramServiceError("Telegram response missing file_path")

        logger.debug("Got file path for file_id=%s: %s", file_id[:8], file_path)
        return file_path

    async def download_file(self, file_path: str) -> bytes:
        """
        Download a file from Telegram servers.

        Args:
            file_path: Path from getFile response

        Returns:
            Raw file bytes

        Raises:
            httpx.HTTPStatusError: On download errors
        """
        download_url = f"https://api.telegram.org/file/bot{self.bot_token}/{file_path}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.get(download_url)
                resp.raise_for_status()
                content = resp.content
                logger.debug("Downloaded file size=%d bytes", len(content))
                return content
            except httpx.HTTPStatusError as e:
                logger.error("Telegram file download failed: url=%s status=%s", download_url, e.response.status_code)
                raise
            except Exception as e:
                logger.exception("Unexpected error in download_file: %s", e)
                raise TelegramServiceError(f"Failed to download file: {e}") from e

    async def download_voice(self, file_id: str) -> bytes:
        """
        Convenience method: get file path and download voice file.

        Args:
            file_id: Telegram file_id from voice message

        Returns:
            Raw OGG/Opus audio bytes from Telegram
        """
        # Avoid logging file IDs at INFO (unnecessary in prod; can be noisy)
        logger.info("Downloading voice message")
        path = await self.get_file_path(file_id)
        return await self.download_file(path)

    async def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: Optional[str] = "HTML",
    ) -> Dict[str, Any]:
        """
        Send a text message to a chat.

        Args:
            chat_id: Telegram chat ID
            text: Message text
            reply_markup: Optional Telegram reply_markup (e.g. inline_keyboard)
            parse_mode: "HTML", "MarkdownV2", or None for plain text

        Returns:
            API response data

        Raises:
            httpx.HTTPStatusError: On API errors
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                payload: Dict[str, Any] = {
                    "chat_id": chat_id,
                    "text": text,
                }
                if parse_mode is not None:
                    payload["parse_mode"] = parse_mode
                if reply_markup is not None:
                    payload["reply_markup"] = reply_markup
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Telegram sendMessage failed: chat_id=%s status=%s body=%s",
                    chat_id,
                    e.response.status_code,
                    e.response.text,
                )
                raise
            except Exception as e:
                logger.exception("Unexpected error in send_message: %s", e)
                raise TelegramServiceError(f"Failed to send message: {e}") from e

    async def send_message_with_inline_keyboard(
        self,
        chat_id: Union[int, str],
        text: str,
        inline_keyboard: List[List[Dict[str, str]]],
        parse_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send message with inline keyboard (each inner list is a button row)."""
        return await self.send_message(
            chat_id,
            text,
            reply_markup={"inline_keyboard": inline_keyboard},
            parse_mode=parse_mode,
        )

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
        show_alert: bool = False,
    ) -> Dict[str, Any]:
        """Acknowledge an inline button press (stops loading spinner on client)."""
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    f"{self.base_url}/answerCallbackQuery",
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Telegram answerCallbackQuery failed: status=%s body=%s",
                    e.response.status_code,
                    e.response.text,
                )
                raise
            except Exception as e:
                logger.exception("Unexpected error in answer_callback_query: %s", e)
                raise TelegramServiceError(
                    f"Failed to answer callback query: {e}"
                ) from e

    async def send_error_message(
        self, chat_id: Union[int, str], error: str
    ) -> None:
        """Send a user-friendly error message. Logs but does not raise on failure."""
        try:
            await self.send_message(chat_id, f"❌ Error: {error}")
        except Exception as e:
            logger.exception(
                "Failed to send error message to chat_id=%s: %s", chat_id, e
            )

    async def send_saved_confirmation(
        self,
        chat_id: Union[int, str],
        brand: str,
        flavor: str,
        best_by: str,
        quantity: int,
    ) -> None:
        """Send confirmation that an inventory item was saved."""
        msg = f"Saved: {brand} {flavor}, expires {best_by}, quantity {quantity}"
        await self.send_message(chat_id, msg)

    async def send_saved_confirmation_multi(
        self,
        chat_id: Union[int, str],
        saved_rows: List[Dict[str, Any]],
    ) -> None:
        """
        Send confirmation for saved rows (must include Supabase `id` per row).
        Adds inline Delete buttons (callback_data d:{uuid}).
        """
        if not saved_rows:
            return

        footer = "\n\nUse Delete below to remove a mistaken entry."

        def _row_keyboard(rows: List[Dict[str, Any]]) -> List[List[Dict[str, str]]]:
            kb: List[List[Dict[str, str]]] = []
            for idx, row in enumerate(rows):
                iid = str(row.get("id") or "").strip()
                if not iid or len(f"d:{iid}".encode("utf-8")) > 64:
                    continue
                label = "Delete" if len(rows) == 1 else f"Delete #{idx + 1}"
                kb.append([{"text": label, "callback_data": f"d:{iid}"}])
            return kb

        if len(saved_rows) == 1:
            item = saved_rows[0]
            msg = (
                f"Saved: {item.get('brand', '') or ''} {item.get('flavor', '') or ''}, "
                f"expires {item.get('best_by', '') or ''}, quantity {int(item.get('quantity') or 0)}"
            )
            msg += footer
            kb = _row_keyboard(saved_rows)
            if kb:
                await self.send_message_with_inline_keyboard(
                    chat_id, msg, kb, parse_mode=None
                )
            else:
                await self.send_message(chat_id, msg, parse_mode=None)
            return

        lines = []
        for idx, item in enumerate(saved_rows, start=1):
            brand = item.get("brand", "") or ""
            flavor = item.get("flavor", "") or ""
            best_by = item.get("best_by", "") or ""
            qty = int(item.get("quantity") or 0)
            lines.append(
                f"{idx}) {brand} {flavor}, expires {best_by}, quantity {qty}"
            )

        msg = "Saved {count} items:\n{items}{footer}".format(
            count=len(saved_rows),
            items="\n".join(lines),
            footer=footer,
        )
        kb = _row_keyboard(saved_rows)
        if kb:
            await self.send_message_with_inline_keyboard(
                chat_id, msg, kb, parse_mode=None
            )
        else:
            await self.send_message(chat_id, msg, parse_mode=None)

    async def delete_webhook(self) -> bool:
        """Remove webhook so getUpdates can be used (for local polling)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{self.base_url}/deleteWebhook")
            data = resp.json()
        return data.get("ok", False)

    async def get_updates(self, offset: int = 0, timeout: int = 30) -> list:
        """
        Poll for updates (use when running locally without webhook).

        Returns:
            List of update objects
        """
        async with httpx.AsyncClient(timeout=timeout + 5) as client:
            resp = await client.get(
                f"{self.base_url}/getUpdates",
                params={"offset": offset, "timeout": timeout},
            )
            resp.raise_for_status()
            data = resp.json()

        if not data.get("ok"):
            raise TelegramServiceError(f"getUpdates failed: {data}")

        return data.get("result", [])
