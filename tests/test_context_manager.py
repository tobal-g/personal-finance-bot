"""Tests for bot.context.manager."""

from unittest.mock import patch

import pytest

from bot.context.manager import build_context
from bot.context.store import ConversationStore, Turn


class TestBuildContext:
    def test_empty_history_minimal_string(self):
        store = ConversationStore()
        result = build_context(1, store)
        # No history, no memory → empty string
        assert result == ""

    def test_two_turns_correct_format(self):
        store = ConversationStore()
        store.add_turn(1, Turn(role="user", text="cuanto gaste?"))
        store.add_turn(
            1,
            Turn(
                role="bot",
                text="¿De qué período?",
                task_result={
                    "task": "query_expenses",
                    "requires_clarification": True,
                    "clarification_reason": "missing time_reference",
                },
            ),
        )

        result = build_context(1, store)
        assert "CONVERSATION CONTEXT" in result
        assert 'Turn 1 - User: "cuanto gaste?"' in result
        assert "requires_clarification=true" in result
        assert "missing time_reference" in result

    def test_includes_memory(self):
        store = ConversationStore()
        with patch(
            "bot.context.manager.load_memory",
            return_value="## notes.md\n\nUser prefers coffee",
        ):
            result = build_context(1, store)

        assert "LONG-TERM MEMORY" in result
        assert "User prefers coffee" in result

    def test_history_and_memory_combined(self):
        store = ConversationStore()
        store.add_turn(1, Turn(role="user", text="hola"))

        with patch(
            "bot.context.manager.load_memory",
            return_value="some memory",
        ):
            result = build_context(1, store)

        assert "CONVERSATION CONTEXT" in result
        assert "LONG-TERM MEMORY" in result
