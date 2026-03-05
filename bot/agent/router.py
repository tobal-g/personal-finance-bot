"""LLM call #1: classify message into task(s) + data."""

import logging
from dataclasses import dataclass

from bot.agent.prompts import ROUTER_SYSTEM_PROMPT
from bot.integrations.llm import call_llm
from bot.utils.parsing import extract_json

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result of routing a single task."""

    task: str
    data: dict
    requires_clarification: bool = False
    clarification_reason: str | None = None


async def route_message(
    message: str,
    context: str,
    expense_types: list[str],
    request_id: str,
    *,
    api_key: str,
) -> list[TaskResult]:
    """Route a message into one or more TaskResults.

    Injects expense types into the router prompt, calls LLM, parses JSON.
    Retries once on parse failure.
    """
    types_str = ", ".join(expense_types) if expense_types else "(no expense types loaded)"
    prompt = ROUTER_SYSTEM_PROMPT.replace("{expense_types}", types_str)

    user_content = message
    if context:
        user_content = f"{context}\n\nCURRENT MESSAGE: {message}"

    logger.info("router.start | req=%s message=%r", request_id, message[:80])

    for attempt in range(1, 3):
        raw = await call_llm(
            prompt,
            user_content,
            purpose="router",
            request_id=request_id,
            api_key=api_key,
        )

        parsed = extract_json(raw)
        if parsed and "tasks" in parsed and isinstance(parsed["tasks"], list):
            results = []
            for t in parsed["tasks"]:
                results.append(
                    TaskResult(
                        task=t.get("task", "unknown"),
                        data=t.get("data", {}),
                        requires_clarification=t.get("requires_clarification", False),
                        clarification_reason=t.get("clarification_reason"),
                    )
                )

            logger.info(
                "router.result | req=%s task_count=%d tasks=%s",
                request_id,
                len(results),
                [r.task for r in results],
            )
            return results

        logger.warning(
            "router.parse_fail | req=%s attempt=%d raw_preview=%r",
            request_id,
            attempt,
            raw[:200] if raw else "",
        )

    # Both attempts failed to parse
    logger.error("router.parse_exhausted | req=%s", request_id)
    return []
