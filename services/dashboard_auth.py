"""
Telegram Login Widget verification + signed session cookie for the inventory dashboard.

Auth never exposes SUPABASE_SERVICE_KEY to the browser: the server verifies the
Telegram HMAC, then issues an HttpOnly cookie; inventory APIs read that cookie
and query Supabase with the service role scoped to that user_id.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger(__name__)

SESSION_COOKIE = "cft_session"
# Login Widget auth_date must be recent
AUTH_MAX_AGE_SEC = 86400  # 24h
# Dashboard session lifetime
SESSION_MAX_AGE_SEC = 60 * 60 * 24 * 30  # 30 days


class DashboardAuthError(Exception):
    """Invalid Telegram login payload or session."""

    pass


def _bot_token() -> str:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise DashboardAuthError("TELEGRAM_BOT_TOKEN not set")
    return token


def verify_telegram_login(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Verify data from Telegram Login Widget / OAuth.

    https://core.telegram.org/widgets/login#checking-authorization
    """
    data = {str(k): str(v) for k, v in payload.items() if v is not None}
    recv_hash = data.pop("hash", None)
    if not recv_hash:
        raise DashboardAuthError("Missing hash")

    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret_key = hashlib.sha256(_bot_token().encode("utf-8")).digest()
    calc = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, recv_hash):
        raise DashboardAuthError("Invalid Telegram login signature")

    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError as e:
        raise DashboardAuthError("Invalid auth_date") from e
    if auth_date <= 0 or (time.time() - auth_date) > AUTH_MAX_AGE_SEC:
        raise DashboardAuthError("Telegram login expired; try again")

    user_id = data.get("id")
    if not user_id:
        raise DashboardAuthError("Missing Telegram user id")

    return {
        "user_id": str(user_id),
        "first_name": data.get("first_name") or "",
        "last_name": data.get("last_name") or "",
        "username": data.get("username") or "",
        "photo_url": data.get("photo_url") or "",
        "auth_date": auth_date,
    }


def _session_secret() -> bytes:
    # Derive a dedicated key so widget auth and session signing stay separated
    return hashlib.sha256(f"cft-session:{_bot_token()}".encode("utf-8")).digest()


def mint_session_token(user_id: str, *, max_age: int = SESSION_MAX_AGE_SEC) -> str:
    exp = int(time.time()) + max_age
    body = f"{user_id}.{exp}"
    sig = hmac.new(_session_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_session_token(token: Optional[str]) -> str:
    if not token or token.count(".") != 2:
        raise DashboardAuthError("Not signed in")
    user_id, exp_s, sig = token.split(".", 2)
    body = f"{user_id}.{exp_s}"
    expect = hmac.new(_session_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        raise DashboardAuthError("Invalid session")
    try:
        exp = int(exp_s)
    except ValueError as e:
        raise DashboardAuthError("Invalid session") from e
    if exp < int(time.time()):
        raise DashboardAuthError("Session expired")
    if not user_id:
        raise DashboardAuthError("Invalid session")
    return user_id


def bot_username() -> str:
    """Bot username without @ for the Login Widget."""
    raw = (os.environ.get("TELEGRAM_BOT_USERNAME") or "").strip().lstrip("@")
    return raw
