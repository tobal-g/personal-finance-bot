"""BaseTool abstract class and ToolContext dataclass."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Coroutine


@dataclass
class ToolContext:
    """Context passed to every tool execution."""

    db_pool: Any  # asyncpg.Pool
    chat_id: int
    request_id: str
    task_id: str
    api_key: str
    llm_call: Callable[..., Coroutine]  # reference to call_llm


class BaseTool(ABC):
    """Abstract base for all tools."""

    name: str
    description: str = ""

    @abstractmethod
    async def execute(self, data: dict, context: ToolContext) -> str:
        """Execute the tool and return the Telegram message to send."""
        ...
