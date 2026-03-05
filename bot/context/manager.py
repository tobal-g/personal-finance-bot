"""Assembles conversation context (history + memory) for the router."""

from bot.context.memory import load_memory
from bot.context.store import ConversationStore


def build_context(chat_id: int, store: ConversationStore) -> str:
    """Build the context block for the router prompt.

    Combines recent conversation history with long-term memory.
    """
    parts: list[str] = []

    # Short-term history
    history = store.get_history(chat_id)
    if history:
        lines: list[str] = []
        turn_num = 0
        for turn in history:
            if turn.role == "user":
                turn_num += 1
                lines.append(f"Turn {turn_num} - User: \"{turn.text}\"")
            elif turn.role == "bot":
                task_info = ""
                if turn.task_result:
                    task_info = f" task={turn.task_result.get('task', '?')}"
                    if turn.task_result.get("requires_clarification"):
                        reason = turn.task_result.get("clarification_reason", "")
                        task_info += f", requires_clarification=true, reason=\"{reason}\""
                lines.append(f"Turn {turn_num} - Bot:{task_info}")
                lines.append(f"Turn {turn_num} - Bot response: \"{turn.text[:200]}\"")

        parts.append(
            "## CONVERSATION CONTEXT (recent turns)\n\n" + "\n".join(lines)
        )

    # Long-term memory
    memory = load_memory()
    if memory:
        parts.append(f"## LONG-TERM MEMORY\n\n{memory}")

    return "\n\n".join(parts)
