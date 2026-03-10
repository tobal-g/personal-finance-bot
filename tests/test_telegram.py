"""Tests for bot.integrations.telegram."""

import logging

import pytest
from aioresponses import aioresponses
from yarl import URL

from bot.integrations.telegram import (
    MAX_MESSAGE_LENGTH,
    TRUNCATION_NOTICE,
    download_file,
    get_file_url,
    send_message,
)

CHAT_ID = -100
TOKEN = "test-token"
API_URL = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


def _get_request(mocked):
    """Get the first request from aioresponses, handling URL key type."""
    key = ("POST", URL(API_URL))
    return mocked.requests[key][0]


class TestSendMessage:
    async def test_successful_send(self):
        with aioresponses() as mocked:
            mocked.post(API_URL, status=200, payload={"ok": True})
            result = await send_message(CHAT_ID, "hello", TOKEN)
            assert result is True

    async def test_correct_payload(self):
        with aioresponses() as mocked:
            mocked.post(API_URL, status=200, payload={"ok": True})
            await send_message(CHAT_ID, "test text", TOKEN)
            call = _get_request(mocked)
            assert call.kwargs["json"]["chat_id"] == CHAT_ID
            assert call.kwargs["json"]["text"] == "test text"


class TestTruncation:
    async def test_long_message_truncated(self):
        long_text = "x" * 5000
        with aioresponses() as mocked:
            mocked.post(API_URL, status=200, payload={"ok": True})
            await send_message(CHAT_ID, long_text, TOKEN)
            call = _get_request(mocked)
            sent_text = call.kwargs["json"]["text"]
            assert len(sent_text) <= MAX_MESSAGE_LENGTH
            assert sent_text.endswith(TRUNCATION_NOTICE)

    async def test_short_message_not_truncated(self):
        with aioresponses() as mocked:
            mocked.post(API_URL, status=200, payload={"ok": True})
            await send_message(CHAT_ID, "short", TOKEN)
            call = _get_request(mocked)
            assert call.kwargs["json"]["text"] == "short"


class TestRetry:
    async def test_retries_on_failure_then_succeeds(self):
        with aioresponses() as mocked:
            mocked.post(API_URL, status=500, payload={"ok": False})
            mocked.post(API_URL, status=200, payload={"ok": True})
            result = await send_message(CHAT_ID, "retry test", TOKEN)
            assert result is True

    async def test_both_attempts_fail_returns_false(self, caplog):
        with aioresponses() as mocked:
            mocked.post(API_URL, status=500, payload={"ok": False})
            mocked.post(API_URL, status=500, payload={"ok": False})
            with caplog.at_level(logging.CRITICAL):
                result = await send_message(CHAT_ID, "fail", TOKEN)
            assert result is False
            assert any("send_exhausted" in r.message for r in caplog.records)

    async def test_network_error_retries(self):
        with aioresponses() as mocked:
            mocked.post(API_URL, exception=ConnectionError("nope"))
            mocked.post(API_URL, status=200, payload={"ok": True})
            result = await send_message(CHAT_ID, "net error", TOKEN)
            assert result is True

    async def test_network_error_log_redacts_token(self, caplog):
        error = ConnectionError(f"boom {API_URL}")
        with aioresponses() as mocked:
            mocked.post(API_URL, exception=error)
            mocked.post(API_URL, status=200, payload={"ok": True})
            with caplog.at_level(logging.WARNING):
                result = await send_message(CHAT_ID, "net error", TOKEN)
        assert result is True
        combined = " ".join(r.message for r in caplog.records)
        assert TOKEN not in combined
        assert "[REDACTED]" in combined


GET_FILE_URL = f"https://api.telegram.org/bot{TOKEN}/getFile"


class TestGetFileUrl:
    async def test_successful_get_file(self):
        with aioresponses() as mocked:
            mocked.post(
                GET_FILE_URL,
                status=200,
                payload={"ok": True, "result": {"file_path": "photos/file_0.jpg"}},
            )
            result = await get_file_url("file_abc", TOKEN)

        assert result == f"https://api.telegram.org/file/bot{TOKEN}/photos/file_0.jpg"

    async def test_api_error_returns_none(self):
        with aioresponses() as mocked:
            mocked.post(GET_FILE_URL, status=400, payload={"ok": False})
            result = await get_file_url("file_abc", TOKEN)

        assert result is None

    async def test_missing_file_path_returns_none(self):
        with aioresponses() as mocked:
            mocked.post(
                GET_FILE_URL,
                status=200,
                payload={"ok": True, "result": {}},
            )
            result = await get_file_url("file_abc", TOKEN)

        assert result is None

    async def test_network_error_returns_none(self):
        with aioresponses() as mocked:
            mocked.post(GET_FILE_URL, exception=ConnectionError("nope"))
            result = await get_file_url("file_abc", TOKEN)

        assert result is None


class TestDownloadFile:
    async def test_successful_download(self):
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/photos/file_0.jpg"
        with aioresponses() as mocked:
            mocked.get(file_url, status=200, body=b"\xff\xd8jpeg-data")
            result = await download_file(file_url)

        assert result == b"\xff\xd8jpeg-data"

    async def test_error_returns_none(self):
        file_url = "https://api.telegram.org/file/botX/missing.jpg"
        with aioresponses() as mocked:
            mocked.get(file_url, status=404)
            result = await download_file(file_url)

        assert result is None

    async def test_network_error_returns_none(self):
        file_url = "https://api.telegram.org/file/botX/photo.jpg"
        with aioresponses() as mocked:
            mocked.get(file_url, exception=ConnectionError("nope"))
            result = await download_file(file_url)

        assert result is None
