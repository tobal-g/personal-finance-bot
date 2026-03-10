"""Receipt photo extraction — download image + call vision LLM."""

import json
import logging
from dataclasses import dataclass

from bot.agent.prompts import RECEIPT_EXTRACTION_PROMPT
from bot.integrations.llm import call_llm_vision
from bot.integrations.telegram import download_file, get_file_url

logger = logging.getLogger(__name__)


@dataclass
class ReceiptResult:
    """Result of receipt extraction."""

    is_receipt: bool
    amount: float | None = None
    currency: str | None = None
    description: str | None = None
    date: str | None = None


async def extract_receipt(
    file_id: str,
    caption: str | None,
    *,
    request_id: str,
    bot_token: str,
    api_key: str,
) -> ReceiptResult | None:
    """Download a photo from Telegram and extract receipt data via vision LLM.

    Returns ReceiptResult on success, None on download/network failure.
    LLM errors (AuthenticationError, RuntimeError) propagate to caller.
    """
    # 1. Get download URL
    file_url = await get_file_url(file_id, bot_token)
    if not file_url:
        logger.warning(
            "receipt.file_url_failed | req=%s file_id=%s", request_id, file_id
        )
        return None

    # 2. Download image bytes
    image_bytes = await download_file(file_url)
    if not image_bytes:
        logger.warning("receipt.download_failed | req=%s", request_id)
        return None

    logger.info(
        "receipt.downloaded | req=%s size_kb=%.1f",
        request_id,
        len(image_bytes) / 1024,
    )

    # 3. Call vision LLM
    raw = await call_llm_vision(
        RECEIPT_EXTRACTION_PROMPT,
        image_bytes,
        caption=caption,
        purpose="receipt_extraction",
        request_id=request_id,
        api_key=api_key,
    )

    # 4. Parse response
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "receipt.parse_failed | req=%s raw=%s", request_id, raw[:200]
        )
        return None

    if not parsed.get("is_receipt"):
        return ReceiptResult(is_receipt=False)

    return ReceiptResult(
        is_receipt=True,
        amount=parsed.get("amount"),
        currency=parsed.get("currency", "ARS"),
        description=parsed.get("description", ""),
        date=parsed.get("date", "hoy"),
    )
