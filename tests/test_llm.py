"""Tests for bot.integrations.llm."""

from unittest.mock import AsyncMock, MagicMock, patch

import openai
import pytest

from bot.integrations.llm import call_llm


def _mock_response(content: str, total_tokens: int = 100):
    """Create a mock OpenAI ChatCompletion response."""
    usage = MagicMock()
    usage.total_tokens = total_tokens

    choice = MagicMock()
    choice.message.content = content

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


class TestCallLLM:
    async def test_successful_call(self):
        mock_create = AsyncMock(return_value=_mock_response('{"task": "log_expense"}'))
        with patch("bot.integrations.llm.openai.AsyncOpenAI") as mock_client_cls:
            mock_client_cls.return_value.chat.completions.create = mock_create
            result = await call_llm(
                "system prompt",
                "user message",
                purpose="test",
                request_id="req_1234",
                api_key="sk-test",
            )

        assert result == '{"task": "log_expense"}'
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["model"] == "gpt-5.2"
        assert call_kwargs["temperature"] == 0.1
        assert call_kwargs["response_format"] == {"type": "json_object"}
        assert call_kwargs["messages"][0]["content"] == "system prompt"
        assert call_kwargs["messages"][1]["content"] == "user message"

    async def test_retry_on_rate_limit(self):
        mock_create = AsyncMock(
            side_effect=[
                openai.RateLimitError(
                    message="Rate limited",
                    response=MagicMock(status_code=429),
                    body=None,
                ),
                _mock_response('{"ok": true}'),
            ]
        )
        with patch("bot.integrations.llm.openai.AsyncOpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create = mock_create
            with patch("bot.integrations.llm.asyncio.sleep", new_callable=AsyncMock):
                result = await call_llm(
                    "sys", "usr", purpose="test", request_id="req_1", api_key="sk-t"
                )

        assert result == '{"ok": true}'
        assert mock_create.call_count == 2

    async def test_auth_error_not_retried(self):
        mock_create = AsyncMock(
            side_effect=openai.AuthenticationError(
                message="Invalid API key",
                response=MagicMock(status_code=401),
                body=None,
            )
        )
        with patch("bot.integrations.llm.openai.AsyncOpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create = mock_create
            with pytest.raises(openai.AuthenticationError):
                await call_llm(
                    "sys", "usr", purpose="test", request_id="req_1", api_key="bad"
                )

        assert mock_create.call_count == 1

    async def test_exhausted_retries_raises_runtime_error(self):
        mock_create = AsyncMock(
            side_effect=openai.RateLimitError(
                message="Rate limited",
                response=MagicMock(status_code=429),
                body=None,
            )
        )
        with patch("bot.integrations.llm.openai.AsyncOpenAI") as mock_cls:
            mock_cls.return_value.chat.completions.create = mock_create
            with patch("bot.integrations.llm.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(RuntimeError, match="failed after 3 retries"):
                    await call_llm(
                        "sys", "usr", purpose="test", request_id="req_1", api_key="sk-t"
                    )

        assert mock_create.call_count == 3
