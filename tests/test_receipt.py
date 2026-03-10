"""Tests for bot.agent.receipt."""

import json
from unittest.mock import AsyncMock, patch

import openai
import pytest
from unittest.mock import MagicMock

from bot.agent.receipt import ReceiptResult, extract_receipt


def _vision_response(data: dict) -> str:
    return json.dumps(data)


class TestExtractReceipt:
    async def test_happy_path(self):
        receipt_json = _vision_response(
            {
                "is_receipt": True,
                "amount": 15230,
                "currency": "ARS",
                "description": "supermercado coto, alimentos",
                "date": "2026-03-09",
            }
        )
        with (
            patch(
                "bot.agent.receipt.get_file_url",
                new_callable=AsyncMock,
                return_value="https://api.telegram.org/file/bot123/photo.jpg",
            ),
            patch(
                "bot.agent.receipt.download_file",
                new_callable=AsyncMock,
                return_value=b"\xff\xd8fake-jpeg",
            ),
            patch(
                "bot.agent.receipt.call_llm_vision",
                new_callable=AsyncMock,
                return_value=receipt_json,
            ),
        ):
            result = await extract_receipt(
                "file_abc",
                None,
                request_id="req_1234",
                bot_token="test-token",
                api_key="sk-test",
            )

        assert result is not None
        assert result.is_receipt is True
        assert result.amount == 15230
        assert result.currency == "ARS"
        assert result.description == "supermercado coto, alimentos"
        assert result.date == "2026-03-09"

    async def test_not_a_receipt(self):
        with (
            patch(
                "bot.agent.receipt.get_file_url",
                new_callable=AsyncMock,
                return_value="https://example.com/photo.jpg",
            ),
            patch(
                "bot.agent.receipt.download_file",
                new_callable=AsyncMock,
                return_value=b"\xff\xd8fake",
            ),
            patch(
                "bot.agent.receipt.call_llm_vision",
                new_callable=AsyncMock,
                return_value=_vision_response({"is_receipt": False}),
            ),
        ):
            result = await extract_receipt(
                "file_abc",
                None,
                request_id="req_1234",
                bot_token="test-token",
                api_key="sk-test",
            )

        assert result is not None
        assert result.is_receipt is False
        assert result.amount is None

    async def test_file_url_failure_returns_none(self):
        with patch(
            "bot.agent.receipt.get_file_url",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await extract_receipt(
                "file_abc",
                None,
                request_id="req_1234",
                bot_token="test-token",
                api_key="sk-test",
            )

        assert result is None

    async def test_download_failure_returns_none(self):
        with (
            patch(
                "bot.agent.receipt.get_file_url",
                new_callable=AsyncMock,
                return_value="https://example.com/photo.jpg",
            ),
            patch(
                "bot.agent.receipt.download_file",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await extract_receipt(
                "file_abc",
                None,
                request_id="req_1234",
                bot_token="test-token",
                api_key="sk-test",
            )

        assert result is None

    async def test_parse_failure_returns_none(self):
        with (
            patch(
                "bot.agent.receipt.get_file_url",
                new_callable=AsyncMock,
                return_value="https://example.com/photo.jpg",
            ),
            patch(
                "bot.agent.receipt.download_file",
                new_callable=AsyncMock,
                return_value=b"\xff\xd8fake",
            ),
            patch(
                "bot.agent.receipt.call_llm_vision",
                new_callable=AsyncMock,
                return_value="not valid json {{{",
            ),
        ):
            result = await extract_receipt(
                "file_abc",
                None,
                request_id="req_1234",
                bot_token="test-token",
                api_key="sk-test",
            )

        assert result is None

    async def test_caption_passed_to_vision(self):
        mock_vision = AsyncMock(
            return_value=_vision_response(
                {
                    "is_receipt": True,
                    "amount": 50,
                    "currency": "USD",
                    "description": "farmacia",
                    "date": "hoy",
                }
            )
        )
        with (
            patch(
                "bot.agent.receipt.get_file_url",
                new_callable=AsyncMock,
                return_value="https://example.com/photo.jpg",
            ),
            patch(
                "bot.agent.receipt.download_file",
                new_callable=AsyncMock,
                return_value=b"\xff\xd8fake",
            ),
            patch("bot.agent.receipt.call_llm_vision", mock_vision),
        ):
            result = await extract_receipt(
                "file_abc",
                "USD farmacia",
                request_id="req_1234",
                bot_token="test-token",
                api_key="sk-test",
            )

        assert result is not None
        assert result.currency == "USD"
        # Verify caption was passed through
        mock_vision.assert_called_once()
        assert mock_vision.call_args.kwargs["caption"] == "USD farmacia"

    async def test_usd_currency_extracted(self):
        with (
            patch(
                "bot.agent.receipt.get_file_url",
                new_callable=AsyncMock,
                return_value="https://example.com/photo.jpg",
            ),
            patch(
                "bot.agent.receipt.download_file",
                new_callable=AsyncMock,
                return_value=b"\xff\xd8fake",
            ),
            patch(
                "bot.agent.receipt.call_llm_vision",
                new_callable=AsyncMock,
                return_value=_vision_response(
                    {
                        "is_receipt": True,
                        "amount": 25.50,
                        "currency": "USD",
                        "description": "amazon, electronics",
                        "date": "2026-03-10",
                    }
                ),
            ),
        ):
            result = await extract_receipt(
                "file_abc",
                None,
                request_id="req_1234",
                bot_token="test-token",
                api_key="sk-test",
            )

        assert result.currency == "USD"
        assert result.amount == 25.50

    async def test_defaults_currency_and_date(self):
        with (
            patch(
                "bot.agent.receipt.get_file_url",
                new_callable=AsyncMock,
                return_value="https://example.com/photo.jpg",
            ),
            patch(
                "bot.agent.receipt.download_file",
                new_callable=AsyncMock,
                return_value=b"\xff\xd8fake",
            ),
            patch(
                "bot.agent.receipt.call_llm_vision",
                new_callable=AsyncMock,
                return_value=_vision_response(
                    {
                        "is_receipt": True,
                        "amount": 5000,
                    }
                ),
            ),
        ):
            result = await extract_receipt(
                "file_abc",
                None,
                request_id="req_1234",
                bot_token="test-token",
                api_key="sk-test",
            )

        assert result.currency == "ARS"
        assert result.date == "hoy"

    async def test_llm_auth_error_propagates(self):
        with (
            patch(
                "bot.agent.receipt.get_file_url",
                new_callable=AsyncMock,
                return_value="https://example.com/photo.jpg",
            ),
            patch(
                "bot.agent.receipt.download_file",
                new_callable=AsyncMock,
                return_value=b"\xff\xd8fake",
            ),
            patch(
                "bot.agent.receipt.call_llm_vision",
                new_callable=AsyncMock,
                side_effect=openai.AuthenticationError(
                    message="Invalid API key",
                    response=MagicMock(status_code=401),
                    body=None,
                ),
            ),
        ):
            with pytest.raises(openai.AuthenticationError):
                await extract_receipt(
                    "file_abc",
                    None,
                    request_id="req_1234",
                    bot_token="test-token",
                    api_key="bad-key",
                )

    async def test_llm_timeout_propagates(self):
        with (
            patch(
                "bot.agent.receipt.get_file_url",
                new_callable=AsyncMock,
                return_value="https://example.com/photo.jpg",
            ),
            patch(
                "bot.agent.receipt.download_file",
                new_callable=AsyncMock,
                return_value=b"\xff\xd8fake",
            ),
            patch(
                "bot.agent.receipt.call_llm_vision",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM call failed after 3 retries"),
            ),
        ):
            with pytest.raises(RuntimeError, match="failed after 3 retries"):
                await extract_receipt(
                    "file_abc",
                    None,
                    request_id="req_1234",
                    bot_token="test-token",
                    api_key="sk-test",
                )
