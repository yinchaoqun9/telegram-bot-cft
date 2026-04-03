"""
Supabase Service - Handles cat inventory storage.

Inserts structured inventory data into the 'cat_inventory' table.
Uses asyncio.to_thread for non-blocking execution (supabase-py is sync).
"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from supabase import Client, create_client

logger = logging.getLogger(__name__)


class SupabaseServiceError(Exception):
    """Raised on Supabase operation failures."""

    pass


def _coerce_best_by_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


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
            "category": "",
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
                "category": (item.get("category") or "") or "",
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

    def _list_telegram_users_sync(self) -> List[Dict[str, Any]]:
        try:
            result = (
                self.client.table("telegram_users")
                .select("user_id,chat_id")
                .execute()
            )
        except Exception as e:
            logger.exception("Supabase list telegram_users error: %s", e)
            raise SupabaseServiceError(f"Failed to list telegram users: {e}") from e
        return result.data or []

    def _get_digest_buckets_for_user_sync(
        self, user_id: str, today: date, window_days: int = 15
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Rows with quantity > 0 and today <= best_by <= today+window_days.
        Split into within_7 (0..7 days) and within_8_15 (8..window_days).
        """
        end = today + timedelta(days=window_days)
        try:
            inv = (
                self.client.table("cat_inventory")
                .select("id,user_id,brand,flavor,category,best_by,quantity")
                .eq("user_id", str(user_id))
                .gt("quantity", 0)
                .gte("best_by", today.isoformat())
                .lte("best_by", end.isoformat())
                .limit(500)
                .execute()
            )
        except Exception as e:
            logger.exception("Supabase digest query error: %s", e)
            raise SupabaseServiceError(f"Failed to query digest inventory: {e}") from e

        within_7: List[Dict[str, Any]] = []
        within_8_15: List[Dict[str, Any]] = []
        for r in inv.data or []:
            bd = _coerce_best_by_date(r.get("best_by"))
            if bd is None:
                continue
            days_left = (bd - today).days
            if days_left < 0:
                continue
            if 0 <= days_left <= 7:
                within_7.append(dict(r))
            elif 8 <= days_left <= window_days:
                within_8_15.append(dict(r))
        return within_7, within_8_15

    def _decrement_item_quantity_sync(
        self, user_id: str, item_id: str, delta: int = 1
    ) -> str:
        """
        Decrease quantity by delta for row owned by user_id. Delete row if qty <= 0.

        Returns:
            'deleted' or 'updated'

        Raises:
            SupabaseServiceError: If row missing or not owned by user.
        """
        if delta < 1:
            raise SupabaseServiceError("Invalid delta")
        try:
            current = (
                self.client.table("cat_inventory")
                .select("id,user_id,quantity")
                .eq("id", item_id)
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.exception("Supabase decrement fetch error: %s", e)
            raise SupabaseServiceError(f"Failed to fetch item: {e}") from e

        row = (current.data or [None])[0]
        if not row or str(row.get("user_id")) != str(user_id):
            raise SupabaseServiceError("Item not found")

        qty = int(row.get("quantity") or 0)
        new_qty = max(0, qty - delta)
        uid = str(user_id)
        try:
            if new_qty <= 0:
                self.client.table("cat_inventory").delete().eq(
                    "id", item_id
                ).eq("user_id", uid).execute()
                return "deleted"
            self.client.table("cat_inventory").update({"quantity": new_qty}).eq(
                "id", item_id
            ).eq("user_id", uid).execute()
            return "updated"
        except Exception as e:
            logger.exception("Supabase decrement update error: %s", e)
            raise SupabaseServiceError(f"Failed to update item: {e}") from e

    def _delete_inventory_item_sync(self, user_id: str, item_id: str) -> None:
        """Delete a row if owned by user_id."""
        uid = str(user_id)
        tid = (item_id or "").strip()
        if not tid:
            raise SupabaseServiceError("Item not found")
        try:
            cur = (
                self.client.table("cat_inventory")
                .select("id")
                .eq("id", tid)
                .eq("user_id", uid)
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.exception("Supabase delete fetch error: %s", e)
            raise SupabaseServiceError(f"Failed to fetch item: {e}") from e
        if not (cur.data or []):
            raise SupabaseServiceError("Item not found")
        try:
            self.client.table("cat_inventory").delete().eq("id", tid).eq(
                "user_id", uid
            ).execute()
        except Exception as e:
            logger.exception("Supabase delete error: %s", e)
            raise SupabaseServiceError(f"Failed to delete item: {e}") from e

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

    async def list_telegram_users(self) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._list_telegram_users_sync)

    async def get_digest_buckets_for_user(
        self, user_id: str, today: date, window_days: int = 15
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        return await asyncio.to_thread(
            self._get_digest_buckets_for_user_sync, user_id, today, window_days
        )

    async def decrement_item_quantity(
        self, user_id: str, item_id: str, delta: int = 1
    ) -> str:
        return await asyncio.to_thread(
            self._decrement_item_quantity_sync, user_id, item_id, delta
        )

    async def delete_inventory_item(self, user_id: str, item_id: str) -> None:
        await asyncio.to_thread(self._delete_inventory_item_sync, user_id, item_id)
