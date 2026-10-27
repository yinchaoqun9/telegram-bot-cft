"""
Inventory dashboard API + HTML page.

Users sign in with Telegram Login Widget; the server verifies the HMAC and
sets an HttpOnly session cookie. All data access is scoped to that user_id.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from services.dashboard_auth import (
    SESSION_COOKIE,
    SESSION_MAX_AGE_SEC,
    DashboardAuthError,
    bot_username,
    mint_session_token,
    parse_session_token,
    verify_telegram_login,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["dashboard"])

STATIC_DIR = Path(__file__).resolve().parent / "static" / "dashboard"


class TelegramLoginBody(BaseModel):
    id: int | str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    auth_date: int | str
    hash: str


def _cookie_secure() -> bool:
    # Local http://localhost → insecure cookie OK; production HTTPS → Secure
    return (os.environ.get("ENV") or "production").strip().lower() == "production"


def _set_session_cookie(response: Response, user_id: str) -> None:
    token = mint_session_token(user_id)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_MAX_AGE_SEC,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        path="/",
    )


def require_user(request: Request) -> str:
    try:
        return parse_session_token(request.cookies.get(SESSION_COOKIE))
    except DashboardAuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page() -> FileResponse:
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=500, detail="Dashboard UI missing")
    return FileResponse(index, media_type="text/html; charset=utf-8")


@router.get("/api/dashboard/config")
async def dashboard_config() -> Dict[str, Any]:
    """Public config for the Login Widget (no secrets)."""
    uname = bot_username()
    # Restock heuristics for the dashboard (units per category)
    return {
        "bot_username": uname,
        "bot_configured": bool(uname),
        "login_hint": (
            None
            if uname
            else "Set TELEGRAM_BOT_USERNAME and BotFather /setdomain for this host."
        ),
        "restock_thresholds": {
            "罐头": int(os.environ.get("RESTOCK_THRESHOLD_CAN", "6")),
            "冻干": int(os.environ.get("RESTOCK_THRESHOLD_FREEZE", "3")),
            "汤包": int(os.environ.get("RESTOCK_THRESHOLD_SOUP", "2")),
            "猫条": int(os.environ.get("RESTOCK_THRESHOLD_STICK", "2")),
            "零食": int(os.environ.get("RESTOCK_THRESHOLD_TREAT", "2")),
            "其他": int(os.environ.get("RESTOCK_THRESHOLD_OTHER", "2")),
        },
    }


@router.post("/api/auth/telegram")
async def auth_telegram(body: TelegramLoginBody, response: Response) -> Dict[str, Any]:
    try:
        user = verify_telegram_login(body.model_dump(exclude_none=True))
    except DashboardAuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    _set_session_cookie(response, user["user_id"])
    logger.info("Dashboard login user_id=%s username=%s", user["user_id"], user.get("username"))
    return {
        "ok": True,
        "user": {
            "user_id": user["user_id"],
            "first_name": user["first_name"],
            "username": user["username"],
            "photo_url": user["photo_url"],
        },
    }


@router.post("/api/auth/logout")
async def auth_logout(response: Response) -> Dict[str, Any]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/api/me")
async def me(user_id: str = Depends(require_user)) -> Dict[str, Any]:
    return {"user_id": user_id}


@router.get("/api/me/inventory")
async def my_inventory(
    request: Request,
    user_id: str = Depends(require_user),
) -> Dict[str, Any]:
    from main import get_supabase

    include_zero = request.query_params.get("include_zero", "").lower() in (
        "1",
        "true",
        "yes",
    )
    try:
        rows = await get_supabase().list_inventory_for_user(
            user_id, include_zero=include_zero
        )
    except Exception as e:
        logger.exception("list inventory failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to load inventory") from e
    return {"user_id": user_id, "items": rows, "count": len(rows)}


class UsedBody(BaseModel):
    delta: int = Field(default=1, ge=1, le=99)


@router.post("/api/me/inventory/{item_id}/used")
async def mark_used(
    item_id: str,
    body: UsedBody | None = None,
    user_id: str = Depends(require_user),
) -> Dict[str, Any]:
    from main import get_supabase
    from services.supabase_service import SupabaseServiceError

    delta = (body or UsedBody()).delta
    try:
        status = await get_supabase().decrement_item_quantity(user_id, item_id, delta=delta)
    except SupabaseServiceError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("mark used failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to update item") from e
    return {"ok": True, "status": status, "item_id": item_id}
