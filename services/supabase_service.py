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

        membership = self._membership_for_user_sync(str(user_id))
        household_id = (membership or {}).get("household_id")

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
            if household_id:
                row["household_id"] = household_id
            rows.append(row)

        try:
            result = self.client.table("cat_inventory").insert(rows).execute()
        except Exception as e:
            # Older DBs without household_id column
            if household_id:
                logger.warning("insert with household_id failed (%s); retrying without", e)
                for row in rows:
                    row.pop("household_id", None)
                try:
                    result = self.client.table("cat_inventory").insert(rows).execute()
                except Exception as e2:
                    logger.exception("Supabase batch insert error: %s", e2)
                    raise SupabaseServiceError(
                        f"Database batch insert failed: {e2}"
                    ) from e2
            else:
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

    def _membership_for_user_sync(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            result = (
                self.client.table("household_members")
                .select(
                    "household_id,user_id,role,notify_partner_changes,joined_at"
                )
                .eq("user_id", str(user_id))
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.warning("household_members lookup failed: %s", e)
            return None
        rows = result.data or []
        return rows[0] if rows else None

    def _user_can_access_item_sync(
        self, user_id: str, row: Dict[str, Any]
    ) -> bool:
        if not row:
            return False
        if str(row.get("user_id")) == str(user_id):
            return True
        hid = row.get("household_id")
        if not hid:
            return False
        membership = self._membership_for_user_sync(str(user_id))
        return bool(membership and str(membership.get("household_id")) == str(hid))

    def _split_digest_rows(
        self, rows: List[Dict[str, Any]], today: date, window_days: int
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        within_7: List[Dict[str, Any]] = []
        within_8_15: List[Dict[str, Any]] = []
        for r in rows:
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

    def _get_digest_buckets_for_user_sync(
        self, user_id: str, today: date, window_days: int = 15
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Household-aware digest buckets (every member gets the shared pantry)."""
        end = today + timedelta(days=window_days)
        membership = self._membership_for_user_sync(str(user_id))
        household_id = (membership or {}).get("household_id")
        try:
            q = (
                self.client.table("cat_inventory")
                .select(
                    "id,user_id,brand,flavor,category,best_by,quantity,household_id"
                )
                .gt("quantity", 0)
                .gte("best_by", today.isoformat())
                .le("best_by", end.isoformat())
                .limit(500)
            )
            if household_id:
                q = q.eq("household_id", household_id)
            else:
                q = q.eq("user_id", str(user_id))
            inv = q.execute()
        except Exception as e:
            logger.warning("digest query with household failed (%s); falling back", e)
            try:
                inv = (
                    self.client.table("cat_inventory")
                    .select("id,user_id,brand,flavor,category,best_by,quantity")
                    .eq("user_id", str(user_id))
                    .gt("quantity", 0)
                    .gte("best_by", today.isoformat())
                    .le("best_by", end.isoformat())
                    .limit(500)
                    .execute()
                )
            except Exception as e2:
                logger.exception("Supabase digest query error: %s", e2)
                raise SupabaseServiceError(
                    f"Failed to query digest inventory: {e2}"
                ) from e2
        return self._split_digest_rows(inv.data or [], today, window_days)

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
                .select("id,user_id,quantity,opened_at,household_id")
                .eq("id", item_id)
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.exception("Supabase decrement fetch error: %s", e)
            raise SupabaseServiceError(f"Failed to fetch item: {e}") from e

        row = (current.data or [None])[0]
        if not row or not self._user_can_access_item_sync(str(user_id), row):
            raise SupabaseServiceError("Item not found")

        qty = int(row.get("quantity") or 0)
        new_qty = max(0, qty - delta)
        try:
            if new_qty <= 0:
                self.client.table("cat_inventory").delete().eq("id", item_id).execute()
                return "deleted"
            self.client.table("cat_inventory").update(
                {"quantity": new_qty, "last_acted_by": str(user_id)}
            ).eq("id", item_id).execute()
            return "updated"
        except Exception as e:
            try:
                if new_qty <= 0:
                    self.client.table("cat_inventory").delete().eq(
                        "id", item_id
                    ).execute()
                    return "deleted"
                self.client.table("cat_inventory").update(
                    {"quantity": new_qty}
                ).eq("id", item_id).execute()
                return "updated"
            except Exception as e2:
                logger.exception("Supabase decrement update error: %s", e2)
                raise SupabaseServiceError(f"Failed to update item: {e2}") from e2

    def _open_item_sync(self, user_id: str, item_id: str, delta: int = 1) -> str:
        """
        Mark lot as opened (set opened_at if missing) and decrement quantity.
        Delete row if qty <= 0. Returns 'deleted' or 'updated'.
        """
        if delta < 1:
            raise SupabaseServiceError("Invalid delta")
        try:
            current = (
                self.client.table("cat_inventory")
                .select("id,user_id,quantity,opened_at,household_id")
                .eq("id", item_id)
                .limit(1)
                .execute()
            )
        except Exception as e:
            # Column may be missing on older DBs — fall back to decrement only
            logger.warning("open_item select failed (%s); falling back to decrement", e)
            return self._decrement_item_quantity_sync(user_id, item_id, delta)

        row = (current.data or [None])[0]
        if not row or not self._user_can_access_item_sync(str(user_id), row):
            raise SupabaseServiceError("Item not found")

        qty = int(row.get("quantity") or 0)
        new_qty = max(0, qty - delta)
        from datetime import timezone

        patch: Dict[str, Any] = {"last_acted_by": str(user_id)}
        if not row.get("opened_at"):
            patch["opened_at"] = datetime.now(timezone.utc).isoformat()
        try:
            if new_qty <= 0:
                self.client.table("cat_inventory").delete().eq("id", item_id).execute()
                return "deleted"
            patch["quantity"] = new_qty
            self.client.table("cat_inventory").update(patch).eq("id", item_id).execute()
            return "updated"
        except Exception as e:
            patch.pop("last_acted_by", None)
            try:
                if new_qty <= 0:
                    self.client.table("cat_inventory").delete().eq(
                        "id", item_id
                    ).execute()
                    return "deleted"
                patch["quantity"] = new_qty
                self.client.table("cat_inventory").update(patch).eq(
                    "id", item_id
                ).execute()
                return "updated"
            except Exception as e2:
                logger.exception("Supabase open_item update error: %s", e2)
                raise SupabaseServiceError(f"Failed to open item: {e2}") from e2
    def _delete_inventory_item_sync(self, user_id: str, item_id: str) -> None:
        """Delete a row if accessible to user (owner or household member)."""
        tid = (item_id or "").strip()
        if not tid:
            raise SupabaseServiceError("Item not found")
        try:
            cur = (
                self.client.table("cat_inventory")
                .select("id,user_id,household_id")
                .eq("id", tid)
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.exception("Supabase delete fetch error: %s", e)
            raise SupabaseServiceError(f"Failed to fetch item: {e}") from e
        row = (cur.data or [None])[0]
        if not row or not self._user_can_access_item_sync(str(user_id), row):
            raise SupabaseServiceError("Item not found")
        try:
            self.client.table("cat_inventory").delete().eq("id", tid).execute()
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

    async def open_item(self, user_id: str, item_id: str, delta: int = 1) -> str:
        return await asyncio.to_thread(self._open_item_sync, user_id, item_id, delta)
    async def delete_inventory_item(self, user_id: str, item_id: str) -> None:
        await asyncio.to_thread(self._delete_inventory_item_sync, user_id, item_id)

    def _list_inventory_for_user_sync(
        self, user_id: str, *, include_zero: bool = False
    ) -> List[Dict[str, Any]]:
        """Inventory for user, or shared household pantry when joined."""
        membership = self._membership_for_user_sync(str(user_id))
        household_id = (membership or {}).get("household_id")
        cols = (
            "id,user_id,brand,flavor,category,best_by,quantity,"
            "opened_at,created_at,household_id,last_acted_by"
        )
        try:
            q = (
                self.client.table("cat_inventory")
                .select(cols)
                .order("best_by", desc=False)
                .limit(1000)
            )
            if household_id:
                q = q.eq("household_id", household_id)
            else:
                q = q.eq("user_id", str(user_id))
            if not include_zero:
                q = q.gt("quantity", 0)
            result = q.execute()
        except Exception as e:
            logger.warning("list inventory household/opened failed (%s); retrying", e)
            try:
                q = (
                    self.client.table("cat_inventory")
                    .select(
                        "id,user_id,brand,flavor,category,best_by,quantity,created_at"
                    )
                    .eq("user_id", str(user_id))
                    .order("best_by", desc=False)
                    .limit(1000)
                )
                if not include_zero:
                    q = q.gt("quantity", 0)
                result = q.execute()
            except Exception as e2:
                logger.exception("Supabase list inventory error: %s", e2)
                raise SupabaseServiceError(f"Failed to list inventory: {e2}") from e2
        return result.data or []

    async def list_inventory_for_user(
        self, user_id: str, *, include_zero: bool = False
    ) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(
            self._list_inventory_for_user_sync, user_id, include_zero=include_zero
        )

    def _get_inventory_item_sync(
        self, user_id: str, item_id: str
    ) -> Optional[Dict[str, Any]]:
        try:
            result = (
                self.client.table("cat_inventory")
                .select(
                    "id,user_id,brand,flavor,category,best_by,quantity,"
                    "opened_at,household_id,last_acted_by"
                )
                .eq("id", item_id)
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.warning("get item with household failed (%s); retrying", e)
            try:
                result = (
                    self.client.table("cat_inventory")
                    .select("id,user_id,brand,flavor,category,best_by,quantity")
                    .eq("id", item_id)
                    .limit(1)
                    .execute()
                )
            except Exception as e2:
                logger.exception("Supabase get item error: %s", e2)
                raise SupabaseServiceError(f"Failed to fetch item: {e2}") from e2
        rows = result.data or []
        if not rows:
            return None
        row = rows[0]
        if not self._user_can_access_item_sync(str(user_id), row):
            return None
        return row

    def _update_inventory_fields_sync(
        self, user_id: str, item_id: str, fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        allowed = {"brand", "flavor", "category", "best_by", "quantity", "opened_at"}
        patch = {k: v for k, v in fields.items() if k in allowed}
        if not patch:
            raise SupabaseServiceError("No valid fields to update")
        if "best_by" in patch:
            bb = (str(patch["best_by"] or "").strip() or None)
            patch["best_by"] = bb
        existing = self._get_inventory_item_sync(str(user_id), item_id)
        if not existing:
            raise SupabaseServiceError("Item not found")
        try:
            result = (
                self.client.table("cat_inventory")
                .update(patch)
                .eq("id", item_id)
                .execute()
            )
        except Exception as e:
            logger.exception("Supabase update item error: %s", e)
            raise SupabaseServiceError(f"Failed to update item: {e}") from e
        if not result.data:
            raise SupabaseServiceError("Item not found")
        return result.data[0]

    def _list_user_brand_aliases_sync(self, user_id: str) -> List[Dict[str, str]]:
        try:
            result = (
                self.client.table("user_brand_aliases")
                .select("alias,canonical")
                .eq("user_id", str(user_id))
                .limit(500)
                .execute()
            )
        except Exception as e:
            # Table may not exist yet — training layer optional until SQL is applied
            logger.warning("user_brand_aliases unavailable: %s", e)
            return []
        out: List[Dict[str, str]] = []
        for row in result.data or []:
            a = (row.get("alias") or "").strip()
            c = (row.get("canonical") or "").strip()
            if a and c:
                out.append({"alias": a, "canonical": c})
        return out

    def _upsert_user_brand_alias_sync(
        self, user_id: str, alias: str, canonical: str
    ) -> None:
        a = (alias or "").strip()
        c = (canonical or "").strip()
        if not a or not c or a.lower() == c.lower():
            return
        row = {
            "user_id": str(user_id),
            "alias": a,
            "canonical": c,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        try:
            self.client.table("user_brand_aliases").upsert(row).execute()
        except Exception as e:
            logger.warning("Failed to upsert user_brand_aliases: %s", e)

    def _log_brand_correction_sync(
        self,
        user_id: str,
        *,
        item_id: Optional[str],
        old_value: str,
        new_value: str,
        field: str = "brand",
    ) -> None:
        row = {
            "id": str(uuid4()),
            "user_id": str(user_id),
            "item_id": item_id,
            "field": field,
            "old_value": old_value or "",
            "new_value": new_value or "",
        }
        try:
            self.client.table("brand_corrections").insert(row).execute()
        except Exception as e:
            logger.warning("Failed to log brand_corrections: %s", e)

    async def get_inventory_item(
        self, user_id: str, item_id: str
    ) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(
            self._get_inventory_item_sync, user_id, item_id
        )

    async def update_inventory_fields(
        self, user_id: str, item_id: str, fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._update_inventory_fields_sync, user_id, item_id, fields
        )

    async def list_user_brand_aliases(self, user_id: str) -> List[Dict[str, str]]:
        return await asyncio.to_thread(self._list_user_brand_aliases_sync, user_id)

    async def upsert_user_brand_alias(
        self, user_id: str, alias: str, canonical: str
    ) -> None:
        await asyncio.to_thread(
            self._upsert_user_brand_alias_sync, user_id, alias, canonical
        )

    async def log_brand_correction(
        self,
        user_id: str,
        *,
        item_id: Optional[str],
        old_value: str,
        new_value: str,
        field: str = "brand",
    ) -> None:
        await asyncio.to_thread(
            self._log_brand_correction_sync,
            user_id,
            item_id=item_id,
            old_value=old_value,
            new_value=new_value,
            field=field,
        )


    # --- Household sharing -------------------------------------------------

    def _list_household_members_sync(self, household_id: str) -> List[Dict[str, Any]]:
        try:
            result = (
                self.client.table("household_members")
                .select(
                    "household_id,user_id,role,notify_partner_changes,joined_at"
                )
                .eq("household_id", str(household_id))
                .execute()
            )
        except Exception as e:
            logger.warning("list household members failed: %s", e)
            return []
        return result.data or []

    def _get_household_sync(self, household_id: str) -> Optional[Dict[str, Any]]:
        try:
            result = (
                self.client.table("households")
                .select("id,name,invite_code,created_by,created_at")
                .eq("id", str(household_id))
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.warning("get household failed: %s", e)
            return None
        rows = result.data or []
        return rows[0] if rows else None

    def _get_household_by_invite_sync(self, code: str) -> Optional[Dict[str, Any]]:
        code = (code or "").strip().upper()
        if not code:
            return None
        try:
            result = (
                self.client.table("households")
                .select("id,name,invite_code,created_by,created_at")
                .eq("invite_code", code)
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.warning("invite lookup failed: %s", e)
            return None
        rows = result.data or []
        return rows[0] if rows else None

    def _attach_user_inventory_to_household_sync(
        self, user_id: str, household_id: str
    ) -> None:
        try:
            self.client.table("cat_inventory").update(
                {"household_id": str(household_id)}
            ).eq("user_id", str(user_id)).is_("household_id", "null").execute()
        except Exception as e:
            logger.warning("attach inventory to household failed: %s", e)

    def _create_household_sync(
        self, user_id: str, name: str = "Pet Pantry"
    ) -> Dict[str, Any]:
        from services.household_service import (
            HouseholdError,
            hard_max_members,
            make_invite_code,
            summarize_household,
        )

        existing = self._membership_for_user_sync(str(user_id))
        if existing:
            raise HouseholdError("You are already in a household. /leave first.")

        hid = str(uuid4())
        code = make_invite_code()
        for _ in range(5):
            if not self._get_household_by_invite_sync(code):
                break
            code = make_invite_code()
        row = {
            "id": hid,
            "name": (name or "Pet Pantry").strip() or "Pet Pantry",
            "invite_code": code,
            "created_by": str(user_id),
        }
        try:
            self.client.table("households").insert(row).execute()
            self.client.table("household_members").insert(
                {
                    "household_id": hid,
                    "user_id": str(user_id),
                    "role": "owner",
                    "notify_partner_changes": False,
                }
            ).execute()
        except Exception as e:
            logger.exception("create household failed: %s", e)
            raise SupabaseServiceError(f"Failed to create household: {e}") from e

        self._attach_user_inventory_to_household_sync(str(user_id), hid)
        household = self._get_household_sync(hid) or row
        members = self._list_household_members_sync(hid)
        return summarize_household(household, members, str(user_id))

    def _join_household_sync(self, user_id: str, invite_code: str) -> Dict[str, Any]:
        from services.household_service import (
            HouseholdError,
            hard_max_members,
            summarize_household,
        )

        if self._membership_for_user_sync(str(user_id)):
            raise HouseholdError("You are already in a household. /leave first.")
        household = self._get_household_by_invite_sync(invite_code)
        if not household:
            raise HouseholdError("Invalid invite code.")
        hid = str(household["id"])
        members = self._list_household_members_sync(hid)
        if len(members) >= hard_max_members():
            raise HouseholdError(
                f"This pantry is full (free plan: {hard_max_members()} people). "
                "Larger households will need a paid plan."
            )
        try:
            self.client.table("household_members").insert(
                {
                    "household_id": hid,
                    "user_id": str(user_id),
                    "role": "member",
                    "notify_partner_changes": False,
                }
            ).execute()
        except Exception as e:
            logger.exception("join household failed: %s", e)
            raise SupabaseServiceError(f"Failed to join household: {e}") from e
        self._attach_user_inventory_to_household_sync(str(user_id), hid)
        members = self._list_household_members_sync(hid)
        return summarize_household(household, members, str(user_id))

    def _leave_household_sync(self, user_id: str) -> str:
        from services.household_service import HouseholdError

        membership = self._membership_for_user_sync(str(user_id))
        if not membership:
            raise HouseholdError("You are not in a household.")
        hid = str(membership["household_id"])
        role = membership.get("role") or "member"
        try:
            self.client.table("household_members").delete().eq(
                "household_id", hid
            ).eq("user_id", str(user_id)).execute()
        except Exception as e:
            raise SupabaseServiceError(f"Failed to leave household: {e}") from e

        # Detach this user's rows back to personal (keep data)
        try:
            self.client.table("cat_inventory").update({"household_id": None}).eq(
                "user_id", str(user_id)
            ).eq("household_id", hid).execute()
        except Exception as e:
            logger.warning("detach inventory on leave failed: %s", e)

        remaining = self._list_household_members_sync(hid)
        if not remaining:
            try:
                self.client.table("households").delete().eq("id", hid).execute()
            except Exception as e:
                logger.warning("delete empty household failed: %s", e)
        elif role == "owner" and remaining:
            # promote first remaining member
            try:
                self.client.table("household_members").update({"role": "owner"}).eq(
                    "household_id", hid
                ).eq("user_id", str(remaining[0]["user_id"])).execute()
            except Exception as e:
                logger.warning("promote owner failed: %s", e)
        return "Left the shared pantry."

    def _set_notify_partner_sync(self, user_id: str, enabled: bool) -> bool:
        from services.household_service import HouseholdError

        membership = self._membership_for_user_sync(str(user_id))
        if not membership:
            raise HouseholdError("Join a household first (/household).")
        try:
            self.client.table("household_members").update(
                {"notify_partner_changes": bool(enabled)}
            ).eq("household_id", membership["household_id"]).eq(
                "user_id", str(user_id)
            ).execute()
        except Exception as e:
            raise SupabaseServiceError(f"Failed to update notify setting: {e}") from e
        return bool(enabled)

    def _get_household_summary_sync(self, user_id: str) -> Optional[Dict[str, Any]]:
        from services.household_service import summarize_household

        membership = self._membership_for_user_sync(str(user_id))
        if not membership:
            return None
        hid = str(membership["household_id"])
        household = self._get_household_sync(hid)
        if not household:
            return None
        members = self._list_household_members_sync(hid)
        return summarize_household(household, members, str(user_id))

    def _partners_wanting_notify_sync(
        self, actor_user_id: str
    ) -> List[Dict[str, Any]]:
        """Other members with notify_partner_changes=true + their chat_id if any."""
        membership = self._membership_for_user_sync(str(actor_user_id))
        if not membership:
            return []
        members = self._list_household_members_sync(str(membership["household_id"]))
        out: List[Dict[str, Any]] = []
        for m in members:
            if str(m.get("user_id")) == str(actor_user_id):
                continue
            if not m.get("notify_partner_changes"):
                continue
            chat = None
            try:
                res = (
                    self.client.table("telegram_users")
                    .select("user_id,chat_id")
                    .eq("user_id", str(m.get("user_id")))
                    .limit(1)
                    .execute()
                )
                if res.data:
                    chat = res.data[0].get("chat_id")
            except Exception:
                chat = None
            out.append(
                {
                    "user_id": str(m.get("user_id")),
                    "chat_id": chat,
                }
            )
        return out

    async def create_household(
        self, user_id: str, name: str = "Pet Pantry"
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(self._create_household_sync, user_id, name)

    async def join_household(self, user_id: str, invite_code: str) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._join_household_sync, user_id, invite_code
        )

    async def leave_household(self, user_id: str) -> str:
        return await asyncio.to_thread(self._leave_household_sync, user_id)

    async def set_notify_partner(self, user_id: str, enabled: bool) -> bool:
        return await asyncio.to_thread(
            self._set_notify_partner_sync, user_id, enabled
        )

    async def get_household_summary(
        self, user_id: str
    ) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._get_household_summary_sync, user_id)

    async def partners_wanting_notify(
        self, actor_user_id: str
    ) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(
            self._partners_wanting_notify_sync, actor_user_id
        )

