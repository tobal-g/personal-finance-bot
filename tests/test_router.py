"""Tests for bot.agent.router."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from bot.agent.router import TaskResult, route_message


def _llm_returns(response_text: str):
    """Patch call_llm to return a fixed response."""
    return patch(
        "bot.agent.router.call_llm",
        new_callable=AsyncMock,
        return_value=response_text,
    )


class TestRouteMessage:
    async def test_single_task(self):
        response = json.dumps(
            {
                "tasks": [
                    {
                        "task": "log_expense",
                        "data": {"amount": 1500, "description": "cafe"},
                        "requires_clarification": False,
                        "clarification_reason": None,
                    }
                ]
            }
        )
        with _llm_returns(response):
            results = await route_message(
                "1500 cafe", "", ["Café", "Uber"], "req_1", api_key="sk-t"
            )

        assert len(results) == 1
        assert results[0].task == "log_expense"
        assert results[0].data["amount"] == 1500
        assert results[0].requires_clarification is False

    async def test_multi_task(self):
        response = json.dumps(
            {
                "tasks": [
                    {
                        "task": "log_expense",
                        "data": {"amount": 5000, "description": "uber"},
                        "requires_clarification": False,
                    },
                    {
                        "task": "query_expenses",
                        "data": {"question": "cuanto gaste este mes"},
                        "requires_clarification": False,
                    },
                ]
            }
        )
        with _llm_returns(response):
            results = await route_message(
                "5000 uber, cuanto gaste este mes", "", [], "req_2", api_key="sk-t"
            )

        assert len(results) == 2
        assert results[0].task == "log_expense"
        assert results[1].task == "query_expenses"

    async def test_clarification_flag(self):
        response = json.dumps(
            {
                "tasks": [
                    {
                        "task": "unknown",
                        "data": {},
                        "requires_clarification": True,
                        "clarification_reason": "missing amount",
                    }
                ]
            }
        )
        with _llm_returns(response):
            results = await route_message(
                "anotame algo", "", [], "req_3", api_key="sk-t"
            )

        assert len(results) == 1
        assert results[0].requires_clarification is True
        assert results[0].clarification_reason == "missing amount"

    async def test_garbage_response_retries_then_empty(self):
        with patch(
            "bot.agent.router.call_llm",
            new_callable=AsyncMock,
            return_value="this is not json at all",
        ):
            results = await route_message(
                "hola", "", [], "req_4", api_key="sk-t"
            )

        assert results == []

    async def test_expense_types_injected_into_prompt(self):
        response = json.dumps(
            {
                "tasks": [
                    {"task": "log_expense", "data": {}, "requires_clarification": False}
                ]
            }
        )
        mock_llm = AsyncMock(return_value=response)
        with patch("bot.agent.router.call_llm", mock_llm):
            await route_message(
                "1500 cafe", "", ["Café", "Uber", "Ocio"], "req_5", api_key="sk-t"
            )

        # Check that the system prompt contains the expense types
        call_args = mock_llm.call_args
        system_prompt = call_args[0][0]
        assert "Café" in system_prompt
        assert "Uber" in system_prompt
        assert "Ocio" in system_prompt

    async def test_uses_context_plus_current_message(self):
        response = json.dumps(
            {
                "tasks": [
                    {"task": "query_expenses", "data": {}, "requires_clarification": False}
                ]
            }
        )
        context = (
            "## CONVERSATION CONTEXT (recent turns)\n\n"
            'Turn 1 - User: "cuanto gaste?"\n'
            'Turn 1 - Bot response: "¿De qué período?"\n'
            'Turn 2 - User: "este mes"'
        )
        mock_llm = AsyncMock(return_value=response)

        with patch("bot.agent.router.call_llm", mock_llm):
            await route_message(
                "este mes", context, ["Café"], "req_6", api_key="sk-t"
            )

        user_content = mock_llm.call_args[0][1]
        assert user_content.startswith(context)
        assert "CURRENT MESSAGE: este mes" in user_content
