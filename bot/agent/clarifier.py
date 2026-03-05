"""LLM call for generating clarification messages."""

import logging

from bot.agent.prompts import CLARIFIER_SYSTEM_PROMPT
from bot.integrations.llm import call_llm
from bot.utils.parsing import extract_json

logger = logging.getLogger(__name__)


async def generate_clarification(
    original_message: str,
    clarification_reason: str,
    request_id: str,
    *,
    api_key: str,
) -> str:
    """Generate a friendly clarification message in Argentine Spanish.

    Returns the clarification text to send to the user.
    """
    user_content = (
        f"The user sent: \"{original_message}\"\n"
        f"Reason clarification is needed: {clarification_reason}\n\n"
        f"Generate a friendly response asking for the missing information. "
        f"Respond with JSON: {{\"message\": \"your response\"}}"
    )

    raw = await call_llm(
        CLARIFIER_SYSTEM_PROMPT,
        user_content,
        purpose="clarifier",
        request_id=request_id,
        api_key=api_key,
    )

    parsed = extract_json(raw)
    if parsed and "message" in parsed:
        return parsed["message"]

    # Fallback: use raw content stripped of JSON artifacts
    return raw.strip().strip('"')
