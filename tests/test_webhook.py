"""Tests for bot.webhook."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.config import Config
from bot.webhook import create_app
from tests.conftest import make_env


@pytest.fixture
def config():
    return Config(env=make_env())


class _FakePool:
    """Fake asyncpg pool with a working acquire() context manager."""

    def __init__(self, *, healthy=True):
        self._healthy = healthy
        self.conn = AsyncMock()
        self.conn.fetchval = AsyncMock(return_value=1)

    @asynccontextmanager
    async def acquire(self):
        if not self._healthy:
            raise Exception("down")
        yield self.conn


@pytest.fixture
def mock_pool():
    return _FakePool(healthy=True)


@pytest.fixture
def app(config, mock_pool):
    return create_app(config, mock_pool)


def _webhook_body(text="hola", chat_id=-100, user_id=111):
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "chat": {"id": chat_id, "type": "group"},
            "date": 1700000000,
            "text": text,
        },
    }


def _health_headers():
    return {"X-Health-Token": "health-test-token"}


class TestWebhookSecurity:
    async def test_missing_secret_returns_403(self, aiohttp_client, app):
        client = await aiohttp_client(app)
        resp = await client.post("/webhook", json=_webhook_body())
        assert resp.status == 403

    async def test_wrong_secret_returns_403(self, aiohttp_client, app):
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_body(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        assert resp.status == 403

    async def test_correct_secret_returns_200(self, aiohttp_client, app):
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_body(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200


class TestWebhookFiltering:
    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook._fetch_expense_types", new_callable=AsyncMock, return_value=[])
    @patch(
        "bot.webhook.route_message",
        new_callable=AsyncMock,
        return_value=[],
    )
    async def test_allowed_chat_and_user_processes(
        self, mock_route, mock_types, mock_send, aiohttp_client, app
    ):
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_body(chat_id=-100, user_id=111),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200
        await asyncio.sleep(0.1)
        # Pipeline was invoked (send_message called with error fallback since route returned [])
        mock_send.assert_called_once()

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    async def test_disallowed_chat_no_processing(
        self, mock_send, aiohttp_client, app
    ):
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_body(chat_id=-999, user_id=111),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200
        await asyncio.sleep(0.1)
        mock_send.assert_not_called()

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    async def test_disallowed_user_no_processing(
        self, mock_send, aiohttp_client, app
    ):
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_body(chat_id=-100, user_id=999),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200
        await asyncio.sleep(0.1)
        mock_send.assert_not_called()

    async def test_no_message_returns_200(self, aiohttp_client, app):
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200

    async def test_no_text_returns_200(self, aiohttp_client, app):
        client = await aiohttp_client(app)
        body = _webhook_body()
        del body["message"]["text"]
        resp = await client.post(
            "/webhook",
            json=body,
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200


class TestHealth:
    async def test_health_requires_token_for_details(self, aiohttp_client, app):
        client = await aiohttp_client(app)
        resp = await client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert "db" not in data
        assert "webhook" not in data

    async def test_health_db_ok(self, aiohttp_client, app):
        client = await aiohttp_client(app)
        resp = await client.get("/health", headers=_health_headers())
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["db"] is True

    async def test_health_invalid_token_returns_limited(self, aiohttp_client, app):
        client = await aiohttp_client(app)
        resp = await client.get("/health", headers={"X-Health-Token": "wrong"})
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] == "ok"
        assert "db" not in data

    async def test_health_db_down(self, aiohttp_client, config):
        unhealthy_pool = _FakePool(healthy=False)
        app = create_app(config, unhealthy_pool)
        client = await aiohttp_client(app)
        resp = await client.get("/health", headers=_health_headers())
        data = await resp.json()
        assert data["status"] == "ok"
        assert data["db"] is False

    async def test_health_no_pool(self, aiohttp_client, config):
        app = create_app(config, None)
        client = await aiohttp_client(app)
        resp = await client.get("/health", headers=_health_headers())
        data = await resp.json()
        assert data["db"] is False
