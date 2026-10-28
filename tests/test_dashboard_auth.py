"""Dashboard Telegram Login HMAC + session cookie tests."""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from services.dashboard_auth import (
    mint_session_token,
    parse_session_token,
    verify_telegram_login,
)


def _signed_login(token: str, **fields) -> dict:
    data = {k: str(v) for k, v in fields.items()}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret = hashlib.sha256(token.encode("utf-8")).digest()
    data["hash"] = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
    return data


def test_verify_telegram_login_ok(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST")
    payload = _signed_login(
        "123456:TEST",
        id=42,
        first_name="Ada",
        username="ada",
        auth_date=int(time.time()),
    )
    user = verify_telegram_login(payload)
    assert user["user_id"] == "42"
    assert user["username"] == "ada"


def test_verify_telegram_login_bad_hash(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST")
    payload = _signed_login(
        "123456:TEST",
        id=42,
        first_name="Ada",
        auth_date=int(time.time()),
    )
    payload["hash"] = "0" * 64
    with pytest.raises(Exception):
        verify_telegram_login(payload)


def test_session_roundtrip(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST")
    tok = mint_session_token("99")
    assert parse_session_token(tok) == "99"


@pytest.fixture
def dash_client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:TEST")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "cpg_tracker_bot")
    monkeypatch.setenv("ENV", "development")

    import main as main_mod

    main_mod._openai = None
    main_mod._gemini = None
    main_mod._gemini_initialized = False
    main_mod._assemblyai = None
    main_mod._assemblyai_initialized = False
    main_mod._supabase = None
    main_mod._telegram = None

    return TestClient(main_mod.app)


def test_dashboard_page(dash_client: TestClient):
    r = dash_client.get("/dashboard")
    assert r.status_code == 200
    assert "Pet Pantry" in r.text
    assert "telegram-login" in r.text or "telegram.org/js/telegram-widget" in r.text


def test_dashboard_config(dash_client: TestClient):
    r = dash_client.get("/api/dashboard/config")
    assert r.status_code == 200
    body = r.json()
    assert body["bot_username"] == "cpg_tracker_bot"
    assert body["restock_thresholds"]["罐头"] == 6
    assert body["restock_thresholds"]["冻干"] == 3
    assert body["restock_thresholds"]["药品"] == 1
    assert body["open_shelf_days"]["罐头"] == 2


def test_auth_and_inventory(dash_client: TestClient, monkeypatch):
    import main as main_mod

    payload = _signed_login(
        "123456:TEST",
        id=8633985127,
        first_name="Tester",
        auth_date=int(time.time()),
    )
    r = dash_client.post("/api/auth/telegram", json=payload)
    assert r.status_code == 200
    assert r.json()["user"]["user_id"] == "8633985127"
    assert "cft_session" in r.cookies

    mock_sb = MagicMock()
    mock_sb.list_inventory_for_user = AsyncMock(
        return_value=[
            {
                "id": "a1",
                "brand": "Orijen",
                "flavor": "chicken",
                "category": "冻干",
                "best_by": "2030-01-01",
                "quantity": 2,
            }
        ]
    )
    monkeypatch.setattr(main_mod, "get_supabase", lambda: mock_sb)

    r2 = dash_client.get("/api/me/inventory")
    assert r2.status_code == 200
    body = r2.json()
    assert body["count"] == 1
    assert body["items"][0]["brand"] == "Orijen"


def test_inventory_requires_auth(dash_client: TestClient):
    r = dash_client.get("/api/me/inventory")
    assert r.status_code == 401
