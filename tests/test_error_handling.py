"""Tests for error handling across the pipeline (Milestone 6)."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import openai
import pytest

from bot.agent.router import TaskResult
from bot.config import Config
from bot.webhook import (
    _ERR_DB_CONNECTION,
    _ERR_LLM_AUTH,
    _ERR_LLM_TIMEOUT,
    _ERR_ROUTER_MALFORMED,
    _ERR_UNKNOWN_TASK,
    create_app,
)
from tests.conftest import make_env


@pytest.fixture
def config():
    return Config(env=make_env())


class _FakePool:
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


def _headers():
    return {"X-Telegram-Bot-Api-Secret-Token": "test-secret"}


class TestRouterErrors:
    """Router-level error handling."""

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook._fetch_expense_types", new_callable=AsyncMock, return_value=[])
    @patch("bot.webhook.route_message", new_callable=AsyncMock, return_value=[])
    async def test_router_malformed_json(
        self, mock_route, mock_types, mock_send, aiohttp_client, app
    ):
        """Router returns empty list → malformed JSON error."""
        client = await aiohttp_client(app)
        await client.post("/webhook", json=_webhook_body(), headers=_headers())
        await asyncio.sleep(0.1)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "router" in sent_text.lower()
        assert "JSON" in sent_text

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook._fetch_expense_types", new_callable=AsyncMock, return_value=[])
    @patch(
        "bot.webhook.route_message",
        new_callable=AsyncMock,
        side_effect=openai.AuthenticationError(
            message="Invalid API key",
            response=AsyncMock(status_code=401),
            body=None,
        ),
    )
    async def test_llm_auth_error_during_routing(
        self, mock_route, mock_types, mock_send, aiohttp_client, app
    ):
        """LLM auth error during routing → specific auth error message."""
        client = await aiohttp_client(app)
        await client.post("/webhook", json=_webhook_body(), headers=_headers())
        await asyncio.sleep(0.1)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "autenticar" in sent_text
        assert "API key" in sent_text

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook._fetch_expense_types", new_callable=AsyncMock, return_value=[])
    @patch(
        "bot.webhook.route_message",
        new_callable=AsyncMock,
        side_effect=RuntimeError("LLM call failed after 3 retries"),
    )
    async def test_llm_timeout_during_routing(
        self, mock_route, mock_types, mock_send, aiohttp_client, app
    ):
        """LLM timeout during routing → specific timeout message."""
        client = await aiohttp_client(app)
        await client.post("/webhook", json=_webhook_body(), headers=_headers())
        await asyncio.sleep(0.1)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "3 veces" in sent_text
        assert "tiempo de espera" in sent_text

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook._fetch_expense_types", new_callable=AsyncMock, return_value=[])
    @patch(
        "bot.webhook.route_message",
        new_callable=AsyncMock,
        side_effect=OSError("connection refused"),
    )
    async def test_db_connection_failure_during_routing(
        self, mock_route, mock_types, mock_send, aiohttp_client, app
    ):
        """DB connection error during routing → specific DB error message."""
        client = await aiohttp_client(app)
        await client.post("/webhook", json=_webhook_body(), headers=_headers())
        await asyncio.sleep(0.1)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "base de datos" in sent_text
        assert "pool" in sent_text


class TestToolErrors:
    """Tool-level error handling with partial success."""

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook._fetch_expense_types", new_callable=AsyncMock, return_value=[])
    @patch(
        "bot.webhook.route_message",
        new_callable=AsyncMock,
        return_value=[
            TaskResult(task="nonexistent_tool", data={}, requires_clarification=False),
        ],
    )
    async def test_unknown_tool(
        self, mock_route, mock_types, mock_send, aiohttp_client, app
    ):
        """Unknown tool name → descriptive unknown task message."""
        client = await aiohttp_client(app)
        await client.post("/webhook", json=_webhook_body(), headers=_headers())
        await asyncio.sleep(0.1)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "matchear" in sent_text
        assert "tareas que tengo registradas" in sent_text

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook._fetch_expense_types", new_callable=AsyncMock, return_value=[])
    @patch("bot.webhook.route_message", new_callable=AsyncMock)
    async def test_tool_llm_auth_error(
        self, mock_route, mock_types, mock_send, aiohttp_client, app
    ):
        """LLM auth error inside a tool → specific auth error, not crash."""
        mock_route.return_value = [
            TaskResult(task="log_expense", data={"amount": 5000, "description": "cafe"}),
        ]
        # Make the pool return expense types so the tool reaches the LLM call
        pool = app["db_pool"]
        pool.conn.fetch = AsyncMock(return_value=[{"name": "Café"}])

        exc = openai.AuthenticationError(
            message="bad key", response=AsyncMock(status_code=401), body=None
        )
        with patch("bot.integrations.llm.openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(side_effect=exc)
            client = await aiohttp_client(app)
            await client.post("/webhook", json=_webhook_body(), headers=_headers())
            await asyncio.sleep(0.2)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "autenticar" in sent_text

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook._fetch_expense_types", new_callable=AsyncMock, return_value=[])
    @patch("bot.webhook.route_message", new_callable=AsyncMock)
    async def test_tool_generic_exception(
        self, mock_route, mock_types, mock_send, aiohttp_client, app
    ):
        """Unexpected exception inside a tool → generic error with detail."""
        mock_route.return_value = [
            TaskResult(task="log_expense", data={"amount": 5000, "description": "cafe"}),
        ]
        # Make the pool return expense types so the tool reaches the LLM call
        pool = app["db_pool"]
        pool.conn.fetch = AsyncMock(return_value=[{"name": "Café"}])

        with patch("bot.integrations.llm.openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                side_effect=ValueError("unexpected parse error")
            )
            client = await aiohttp_client(app)
            await client.post("/webhook", json=_webhook_body(), headers=_headers())
            await asyncio.sleep(0.2)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "Algo salió mal" in sent_text
        assert "log_expense" in sent_text


class TestPartialSuccess:
    """Multi-task partial success: some tasks succeed, some fail."""

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook._fetch_expense_types", new_callable=AsyncMock, return_value=[])
    @patch("bot.webhook.route_message", new_callable=AsyncMock)
    async def test_partial_success_mixed(
        self, mock_route, mock_types, mock_send, aiohttp_client, app
    ):
        """2 tasks: one succeeds (unknown tool → error), one fails (another unknown).
        Both error messages should appear in the combined response."""
        mock_route.return_value = [
            TaskResult(task="nonexistent_1", data={}),
            TaskResult(task="nonexistent_2", data={}),
        ]

        client = await aiohttp_client(app)
        await client.post("/webhook", json=_webhook_body(), headers=_headers())
        await asyncio.sleep(0.1)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        # Both tasks should produce the unknown task error, combined in one message
        assert sent_text.count("No entendí") == 2

    @patch("bot.webhook.send_message", new_callable=AsyncMock)
    @patch("bot.webhook._fetch_expense_types", new_callable=AsyncMock, return_value=[])
    @patch("bot.webhook.route_message", new_callable=AsyncMock)
    async def test_one_tool_fails_other_succeeds(
        self, mock_route, mock_types, mock_send, aiohttp_client, app
    ):
        """First task has known tool that raises, second is unknown tool.
        Both errors should be sent as combined message (no crash)."""
        mock_route.return_value = [
            TaskResult(task="log_expense", data={"amount": 5000, "description": "cafe"}),
            TaskResult(task="nonexistent", data={}),
        ]
        # Make pool return expense types so tool reaches LLM call
        pool = app["db_pool"]
        pool.conn.fetch = AsyncMock(return_value=[{"name": "Café"}])

        with patch("bot.integrations.llm.openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = AsyncMock(
                side_effect=ValueError("boom")
            )
            client = await aiohttp_client(app)
            await client.post("/webhook", json=_webhook_body(), headers=_headers())
            await asyncio.sleep(0.2)

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        # First task: generic tool error; Second task: unknown tool error
        assert "Algo salió mal" in sent_text
        assert "No entendí" in sent_text
