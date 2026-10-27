"""Light FastAPI webhook / health tests (no Telegram or AI network)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")

    # Import after env so lazy getters don't fail if touched
    import main as main_mod

    # Reset singletons between tests
    main_mod._openai = None
    main_mod._gemini = None
    main_mod._gemini_initialized = False
    main_mod._assemblyai = None
    main_mod._assemblyai_initialized = False
    main_mod._supabase = None
    main_mod._telegram = None

    return TestClient(main_mod.app)


def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_root(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body.get("ok") is True or "status" in body


def test_webhook_invalid_json(client: TestClient):
    r = client.post("/webhook", content=b"not-json", headers={"content-type": "application/json"})
    assert r.status_code == 400


def test_webhook_ignores_non_message(client: TestClient):
    r = client.post("/webhook", json={"update_id": 1})
    assert r.status_code == 200


def test_webhook_start_command(client: TestClient):
    import main as main_mod

    tg = AsyncMock()
    tg.send_message = AsyncMock()
    sb = AsyncMock()
    sb.upsert_telegram_user = AsyncMock()

    with (
        patch.object(main_mod, "get_telegram", return_value=tg),
        patch.object(main_mod, "get_supabase", return_value=sb),
    ):
        r = client.post(
            "/webhook",
            json={
                "update_id": 2,
                "message": {
                    "chat": {"id": 99},
                    "from": {"id": 42},
                    "text": "/start",
                },
            },
        )
    assert r.status_code == 200
    tg.send_message.assert_awaited()
    sb.upsert_telegram_user.assert_awaited()


def test_webhook_queues_voice(client: TestClient):
    import main as main_mod

    sb = AsyncMock()
    sb.upsert_telegram_user = AsyncMock()
    created = []

    def fake_create_task(coro):
        created.append(coro)
        # Close coroutine to avoid "never awaited" warnings
        coro.close()
        return MagicMock()

    with (
        patch.object(main_mod, "get_supabase", return_value=sb),
        patch.object(main_mod.asyncio, "create_task", side_effect=fake_create_task),
    ):
        r = client.post(
            "/webhook",
            json={
                "update_id": 3,
                "message": {
                    "chat": {"id": 1},
                    "from": {"id": 2},
                    "voice": {"file_id": "VOICE123"},
                },
            },
        )
    assert r.status_code == 200
    assert len(created) == 1
