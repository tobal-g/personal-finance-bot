"""Telegram Bot API helpers."""

import asyncio
import logging

import aiohttp

from bot.utils.logging_safety import redact_sensitive

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE_LENGTH = 4096
TRUNCATION_NOTICE = "\n(Resultado recortado. Probá una consulta más específica.)"


async def send_message(chat_id: int, text: str, token: str) -> bool:
    """Send a message via Telegram Bot API.

    Truncates at 4096 chars. Retries once after 2s on failure.
    Returns True if sent successfully, False otherwise.
    """
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[: MAX_MESSAGE_LENGTH - len(TRUNCATION_NOTICE)] + TRUNCATION_NOTICE

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    for attempt in range(1, 3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(
                            "telegram.sent | chat_id=%s text_length=%d",
                            chat_id,
                            len(text),
                        )
                        return True
                    body = await resp.text()
                    logger.warning(
                        "telegram.send_failed | chat_id=%s status=%d body=%s attempt=%d",
                        chat_id,
                        resp.status,
                        redact_sensitive(body)[:200],
                        attempt,
                    )
        except Exception as exc:
            logger.warning(
                "telegram.send_error | chat_id=%s attempt=%d error=%s",
                chat_id,
                attempt,
                redact_sensitive(exc)[:200],
            )

        if attempt == 1:
            await asyncio.sleep(2)

    logger.critical(
        "telegram.send_exhausted | chat_id=%s text_length=%d",
        chat_id,
        len(text),
    )
    return False


async def get_file_url(file_id: str, token: str) -> str | None:
    """Fetch the file_path from Telegram's getFile API and return the download URL.

    Returns None if the API call fails.
    """
    url = f"{TELEGRAM_API}/bot{token}/getFile"
    payload = {"file_id": file_id}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.warning(
                        "telegram.get_file_failed | file_id=%s status=%d",
                        file_id,
                        resp.status,
                    )
                    return None
                body = await resp.json()
                file_path = body.get("result", {}).get("file_path")
                if not file_path:
                    logger.warning(
                        "telegram.get_file_empty | file_id=%s",
                        file_id,
                    )
                    return None
                return f"{TELEGRAM_API}/file/bot{token}/{file_path}"
    except Exception as exc:
        logger.warning(
            "telegram.get_file_error | file_id=%s error=%s",
            file_id,
            str(exc)[:200],
        )
        return None


async def download_file(file_url: str) -> bytes | None:
    """Download a file from a Telegram file URL. Returns raw bytes or None."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status != 200:
                    logger.warning(
                        "telegram.download_failed | url=%s status=%d",
                        file_url[:80],
                        resp.status,
                    )
                    return None
                return await resp.read()
    except Exception as exc:
        logger.warning(
            "telegram.download_error | error=%s",
            str(exc)[:200],
        )
        return None
