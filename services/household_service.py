"""
Household (shared pet pantry) helpers.

Free plan: up to HOUSEHOLD_FREE_MAX_MEMBERS (default 2).
Digest always goes to every member; partner change pings are per-member opt-in.
"""

from __future__ import annotations

import logging
import os
import secrets
import string
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def free_max_members() -> int:
    try:
        return max(2, int(os.environ.get("HOUSEHOLD_FREE_MAX_MEMBERS", "2")))
    except ValueError:
        return 2


def hard_max_members() -> int:
    """Absolute cap; paid tiers can raise HOUSEHOLD_MAX_MEMBERS later."""
    try:
        paid = int(os.environ.get("HOUSEHOLD_MAX_MEMBERS", str(free_max_members())))
        return max(free_max_members(), paid)
    except ValueError:
        return free_max_members()


def make_invite_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"PET-{body}"


class HouseholdError(Exception):
    """User-facing household error."""

    pass


def summarize_household(
    household: Dict[str, Any],
    members: List[Dict[str, Any]],
    my_user_id: str,
) -> Dict[str, Any]:
    me = next((m for m in members if str(m.get("user_id")) == str(my_user_id)), None)
    return {
        "id": household.get("id"),
        "name": household.get("name") or "Pet Pantry",
        "invite_code": household.get("invite_code"),
        "member_count": len(members),
        "max_members": hard_max_members(),
        "free_max_members": free_max_members(),
        "members": [
            {
                "user_id": str(m.get("user_id")),
                "role": m.get("role") or "member",
                "notify_partner_changes": bool(m.get("notify_partner_changes")),
            }
            for m in members
        ],
        "my_role": (me or {}).get("role") or "member",
        "notify_partner_changes": bool((me or {}).get("notify_partner_changes")),
    }
