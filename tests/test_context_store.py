"""Tests for bot.context.store."""

import time

import pytest

from bot.context.store import ConversationStore, Turn


class TestConversationStore:
    def test_add_and_get_turns(self):
        store = ConversationStore()
        store.add_turn(1, Turn(role="user", text="hola"))
        store.add_turn(1, Turn(role="bot", text="hola!"))

        history = store.get_history(1)
        assert len(history) == 2
        assert history[0].role == "user"
        assert history[1].role == "bot"

    def test_ttl_pruning(self):
        store = ConversationStore(ttl_seconds=5)
        old_turn = Turn(role="user", text="old", timestamp=time.time() - 10)
        new_turn = Turn(role="user", text="new")

        store.add_turn(1, old_turn)
        store.add_turn(1, new_turn)

        history = store.get_history(1)
        assert len(history) == 1
        assert history[0].text == "new"

    def test_max_turns_enforced(self):
        store = ConversationStore(max_turns=3)
        for i in range(5):
            store.add_turn(1, Turn(role="user", text=f"msg{i}"))

        history = store.get_history(1)
        assert len(history) == 3
        # Should keep the last 3
        assert history[0].text == "msg2"
        assert history[2].text == "msg4"

    def test_clear(self):
        store = ConversationStore()
        store.add_turn(1, Turn(role="user", text="test"))
        store.clear(1)

        history = store.get_history(1)
        assert len(history) == 0

    def test_separate_chats(self):
        store = ConversationStore()
        store.add_turn(1, Turn(role="user", text="chat1"))
        store.add_turn(2, Turn(role="user", text="chat2"))

        assert len(store.get_history(1)) == 1
        assert len(store.get_history(2)) == 1
        assert store.get_history(1)[0].text == "chat1"

    def test_empty_history_returns_empty_list(self):
        store = ConversationStore()
        assert store.get_history(999) == []

    def test_task_result_stored(self):
        store = ConversationStore()
        store.add_turn(
            1,
            Turn(
                role="bot",
                text="stub",
                task_result={"task": "log_expense"},
            ),
        )
        history = store.get_history(1)
        assert history[0].task_result == {"task": "log_expense"}
