"""Tests for bot.agent.clarifier."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from bot.agent.clarifier import generate_clarification


class TestGenerateClarification:
    async def test_returns_message_from_json(self):
        response = json.dumps(
            {"message": "Decime el monto y una descripción, por ejemplo: '5000 uber'."}
        )
        with patch(
            "bot.agent.clarifier.call_llm",
            new_callable=AsyncMock,
            return_value=response,
        ):
            result = await generate_clarification(
                "anotame algo",
                "missing amount",
                "req_1",
                api_key="sk-t",
            )

        assert result == "Decime el monto y una descripción, por ejemplo: '5000 uber'."

    async def test_calls_llm_with_clarifier_prompt(self):
        response = json.dumps({"message": "test"})
        mock_llm = AsyncMock(return_value=response)
        with patch("bot.agent.clarifier.call_llm", mock_llm):
            await generate_clarification(
                "anotame algo",
                "missing amount",
                "req_1",
                api_key="sk-t",
            )

        call_args = mock_llm.call_args
        assert call_args[1]["purpose"] == "clarifier"
        # System prompt should contain Argentine Spanish instructions
        system_prompt = call_args[0][0]
        assert "vos" in system_prompt

    async def test_fallback_on_non_json_response(self):
        with patch(
            "bot.agent.clarifier.call_llm",
            new_callable=AsyncMock,
            return_value="Decime más detalles.",
        ):
            result = await generate_clarification(
                "algo",
                "vague",
                "req_1",
                api_key="sk-t",
            )

        assert "Decime más detalles." in result
