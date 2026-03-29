"""
Supabase Service - Handles cat inventory storage.

Inserts structured inventory data into the 'cat_inventory' table.
Uses asyncio.to_thread for non-blocking execution (supabase-py is sync).
"""

import asyncio
import logging
from datetime import date
from typing import Any, Dict, List, Optional
from uuid import uuid4

from supabase import Client, create_client

logger = logging.getLogger(__name__)


class SupabaseServiceError(Exception):
    """Raised on Supabase operation failures."""

    pass


class SupabaseService:
    """Service for Supabase database operations."""

    def __init__(self, url: str, service_key: str):
        self.client: Client = create_client(url, service_key)

    def _insert_inventory_item_sync(
        self,
        user_id: str,
        brand: str,
        flavor: str,
        best_by: str,
        quantity: int,
    ) -> Dict[str, Any]:
        """Synchronous insert (called from thread pool)."""
        best_by_val = (best_by or "").strip() or None

        row = {
            "id": str(uuid4()),
            "user_id": str(user_id),
            "brand": brand or "",
            "flavor": flavor or "",
            "best_by": best_by_val,
            "quantity": quantity or 0,
        }

        try:
            result = self.client.table("cat_inventory").insert(row).execute()
        except Exception as e:
            logger.exception("Supabase insert error: %s", e)
            raise SupabaseServiceError(f"Database insert failed: {e}") from e

        if not result.data or len(result.data) == 0:
            logger.error("Supabase insert returned no data")
            raise SupabaseServiceError("Insert succeeded but no data returned")

        logger.info("Inserted inventory id=%s user_id=%s", row["id"], user_id)
        return result.data[0]

    def _insert_inventory_items_sync(
        self,
        user_id: str,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Synchronous batch insert of multiple items."""
        if not items:
            raise SupabaseServiceError("No items to insert")

        rows: List[Dict[str, Any]] = []
        for item in items:
            best_by_val = (item.get("best_by") or "").strip() or None
            row = {
                "id": str(uuid4()),
                "user_id": str(user_id),
                "brand": item.get("brand") or "",
                "flavor": item.get("flavor") or "",
                "best_by": best_by_val,
                "quantity": int(item.get("quantity") or 0),
            }
            rows.append(row)

        try:
            result = self.client.table("cat_inventory").insert(rows).execute()
        except Exception as e:
            logger.exception("Supabase batch insert error: %s", e)
            raise SupabaseServiceError(f"Database batch insert failed: {e}") from e

        if not result.data or len(result.data) == 0:
            logger.error("Supabase batch insert returned no data")
            raise SupabaseServiceError("Batch insert succeeded but no data returned")

        logger.info(
            "Inserted %d inventory items for user_id=%s", len(result.data), user_id
        )
        return result.data

    def _upsert_telegram_user_sync(self, user_id: str, chat_id: int) -> None:
        """
        Upsert Telegram user -> chat mapping.

        This enables proactive reminders in 1:1 chats.
        """
        row = {"user_id": str(user_id), "chat_id": int(chat_id)}
        try:
            # If your table has `updated_at` default/trigger, it will be handled server-side.
            self.client.table("telegram_users").upsert(row).execute()
        except Exception as e:
            logger.exception("Supabase upsert telegram_users error: %s", e)
            raise SupabaseServiceError(f"Failed to upsert telegram user: {e}") from e

    def _get_expiring_items_sync(
        self, target_date: str, offset_days: int, limit: int = 500
    ) -> List[Dict[str, Any]]:
        """
        Fetch inventory rows that expire on target_date and have NOT been reminded for offset_days.
        """
        try:
            # Need: join to telegram_users via user_id to get chat_id.
            # supabase-py doesn't do SQL joins easily; we do two-step fetch:
            # 1) fetch expiring rows
            inv = (
                self.client.table("cat_inventory")
                .select("id,user_id,brand,flavor,best_by,quantity,reminded_offsets")
                .eq("best_by", target_date)
                .limit(limit)
                .execute()
            )
        except Exception as e:
            logger.exception("Supabase fetch expiring inventory error: %s", e)
            raise SupabaseServiceError(f"Failed to query inventory: {e}") from e

        rows = inv.data or []
        if not rows:
            return []

        # Filter out rows that already contain offset_days in reminded_offsets
        filtered = []
        user_ids = set()
        for r in rows:
            reminded = r.get("reminded_offsets") or []
            if isinstance(reminded, list) and offset_days in reminded:
                continue
            filtered.append(r)
            user_ids.add(r.get("user_id"))

        if not filtered or not user_ids:
            return []

        try:
            users = (
                self.client.table("telegram_users")
                .select("user_id,chat_id")
                .in_("user_id", list(user_ids))
                .execute()
            )
        except Exception as e:
            logger.exception("Supabase fetch telegram_users error: %s", e)
            raise SupabaseServiceError(f"Failed to query telegram_users: {e}") from e

        mapping = {u["user_id"]: u.get("chat_id") for u in (users.data or [])}

        # Attach chat_id
        result: List[Dict[str, Any]] = []
        for r in filtered:
            chat_id = mapping.get(r.get("user_id"))
            if chat_id is None:
                continue
            r2 = dict(r)
            r2["chat_id"] = chat_id
            result.append(r2)

        return result

    def _mark_reminded_sync(self, item_id: str, offset_days: int) -> None:
        """Append offset_days to reminded_offsets for the given inventory item."""
        try:
            # We read current offsets then update; for low volume this is OK.
            current = (
                self.client.table("cat_inventory")
                .select("reminded_offsets")
                .eq("id", item_id)
                .limit(1)
                .execute()
            )
            data = (current.data or [{}])[0]
            offsets = data.get("reminded_offsets") or []
            if not isinstance(offsets, list):
                offsets = []
            if offset_days not in offsets:
                offsets.append(offset_days)
            self.client.table("cat_inventory").update(
                {"reminded_offsets": offsets}
            ).eq("id", item_id).execute()
        except Exception as e:
            logger.exception("Supabase mark reminded error: %s", e)
            raise SupabaseServiceError(f"Failed to mark reminded: {e}") from e

    async def insert_inventory_item(
        self,
        user_id: str,
        brand: str,
        flavor: str,
        best_by: str,
        quantity: int,
    ) -> Dict[str, Any]:
        """
        Insert an inventory item into cat_inventory table (async).

        Args:
            user_id: Telegram user ID as string
            brand: Cat food brand
            flavor: Flavor/variant
            best_by: Date string in YYYY-MM-DD format
            quantity: Number of items

        Returns:
            Inserted row data from Supabase

        Raises:
            SupabaseServiceError: On database errors
        """
        return await asyncio.to_thread(
            self._insert_inventory_item_sync,
            user_id,
            brand or "",
            flavor or "",
            best_by or "",
            quantity or 0,
        )

    async def insert_inventory_items(
        self,
        user_id: str,
        items: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Insert multiple inventory items into cat_inventory table (async).

        Args:
            user_id: Telegram user ID as string
            items: List of item dicts with brand, flavor, best_by, quantity

        Returns:
            List of inserted row data from Supabase

        Raises:
            SupabaseServiceError: On database errors
        """
        return await asyncio.to_thread(self._insert_inventory_items_sync, user_id, items)

    async def upsert_telegram_user(self, user_id: str, chat_id: int) -> None:
        """Async wrapper for upserting telegram_users mapping."""
        await asyncio.to_thread(self._upsert_telegram_user_sync, user_id, chat_id)

    async def get_expiring_items(
        self, target_date: date, offset_days: int, limit: int = 500
    ) -> List[Dict[str, Any]]:
        """Async wrapper to fetch expiring items for a given offset."""
        return await asyncio.to_thread(
            self._get_expiring_items_sync, target_date.isoformat(), offset_days, limit
        )

    async def mark_reminded(self, item_id: str, offset_days: int) -> None:
        """Async wrapper to mark an item as reminded for offset_days."""
        await asyncio.to_thread(self._mark_reminded_sync, item_id, offset_days)
