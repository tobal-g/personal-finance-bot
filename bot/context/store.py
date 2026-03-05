"""In-memory conversation store with TTL, keyed by chat_id."""

import time
from dataclasses import dataclass, field


@dataclass
class Turn:
    """A single conversation turn."""

    role: str  # "user" or "bot"
    text: str
    timestamp: float = field(default_factory=time.time)
    task_result: dict | None = None


class ConversationStore:
    """Per-chat conversation history with TTL pruning.

    Stores up to max_turns entries per chat_id.
    Entries older than ttl_seconds are pruned on access.
    """

    def __init__(
        self,
        ttl_seconds: int = 600,
        max_turns: int = 6,
        max_user_chars: int = 400,
    ):
        self._store: dict[int, list[Turn]] = {}
        self._ttl = ttl_seconds
        self._max_turns = max_turns
        self._max_user_chars = max_user_chars

    def add_turn(self, chat_id: int, turn: Turn) -> None:
        """Add a turn and prune old entries."""
        if turn.role == "user" and len(turn.text) > self._max_user_chars:
            turn = Turn(
                role=turn.role,
                text=turn.text[: self._max_user_chars],
                timestamp=turn.timestamp,
                task_result=turn.task_result,
            )

        if chat_id not in self._store:
            self._store[chat_id] = []
        self._store[chat_id].append(turn)
        self._prune(chat_id)

    def get_history(self, chat_id: int) -> list[Turn]:
        """Return recent turns for a chat, after TTL pruning."""
        self._prune(chat_id)
        return list(self._store.get(chat_id, []))

    def clear(self, chat_id: int) -> None:
        """Clear all history for a chat."""
        self._store.pop(chat_id, None)

    def _prune(self, chat_id: int) -> None:
        """Remove expired turns and enforce max_turns."""
        turns = self._store.get(chat_id)
        if not turns:
            return
        now = time.time()
        self._store[chat_id] = [
            t for t in turns if (now - t.timestamp) < self._ttl
        ][-self._max_turns:]
