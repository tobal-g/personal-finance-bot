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


def _webhook_photo_body(file_id="abc123", caption="", chat_id=-100, user_id=111):
    body = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
            "chat": {"id": chat_id, "type": "group"},
            "date": 1700000000,
            "photo": [
                {"file_id": f"{file_id}_small", "width": 90, "height": 90, "file_size": 1000},
                {"file_id": f"{file_id}_med", "width": 320, "height": 320, "file_size": 5000},
                {"file_id": file_id, "width": 800, "height": 800, "file_size": 50000},
            ],
        },
    }
    if caption:
        body["message"]["caption"] = caption
    return body


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
        # First message should route with no prior context.
        assert mock_route.call_args[0][1] == ""
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

    async def test_no_text_and_no_photo_returns_200(self, aiohttp_client, app):
        client = await aiohttp_client(app)
        body = _webhook_body()
        del body["message"]["text"]
        resp = await client.post(
            "/webhook",
            json=body,
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200

    async def test_photo_message_accepted(self, aiohttp_client, app):
        """Photo message (no text) should be accepted and return 200."""
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_photo_body(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    async def test_photo_disallowed_chat_no_processing(
        self, mock_send, aiohttp_client, app
    ):
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_photo_body(chat_id=-999),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200
        await asyncio.sleep(0.1)
        mock_send.assert_not_called()

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook.extract_receipt", new_callable=AsyncMock)
    async def test_photo_triggers_receipt_extraction(
        self, mock_extract, mock_send, aiohttp_client, app
    ):
        from bot.agent.receipt import ReceiptResult

        mock_extract.return_value = ReceiptResult(
            is_receipt=True,
            amount=15000,
            currency="ARS",
            description="supermercado",
            date="hoy",
        )
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_photo_body(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200
        await asyncio.sleep(0.2)
        mock_extract.assert_called_once()
        # Verify the largest photo was used
        call_args = mock_extract.call_args
        assert call_args[0][0] == "abc123"  # file_id of largest photo

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook.extract_receipt", new_callable=AsyncMock)
    async def test_photo_not_receipt_sends_error(
        self, mock_extract, mock_send, aiohttp_client, app
    ):
        from bot.agent.receipt import ReceiptResult

        mock_extract.return_value = ReceiptResult(is_receipt=False)
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_photo_body(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200
        await asyncio.sleep(0.2)
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "ticket o factura" in sent_text

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook.extract_receipt", new_callable=AsyncMock, return_value=None)
    async def test_photo_download_failure_sends_error(
        self, mock_extract, mock_send, aiohttp_client, app
    ):
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_photo_body(),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200
        await asyncio.sleep(0.2)
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "descargar la foto" in sent_text

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook.extract_receipt", new_callable=AsyncMock)
    async def test_photo_with_caption_passes_caption(
        self, mock_extract, mock_send, aiohttp_client, app
    ):
        from bot.agent.receipt import ReceiptResult

        mock_extract.return_value = ReceiptResult(is_receipt=False)
        client = await aiohttp_client(app)
        resp = await client.post(
            "/webhook",
            json=_webhook_photo_body(caption="USD farmacia"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
        )
        assert resp.status == 200
        await asyncio.sleep(0.2)
        call_args = mock_extract.call_args
        assert call_args[0][1] == "USD farmacia"  # caption arg


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
