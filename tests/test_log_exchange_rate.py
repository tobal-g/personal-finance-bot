"""Tests for bot.tools.log_exchange_rate."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from bot.tools.base import ToolContext
from bot.tools.log_exchange_rate import LogExchangeRateTool


# --- Fixtures ---

class _FakeConn:
    def __init__(self, insert_result=None):
        self._insert_result = insert_result

    async def fetchrow(self, query, *args):
        return self._insert_result


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def _make_context(pool):
    return ToolContext(
        db_pool=pool,
        chat_id=-100,
        request_id="req_test",
        task_id="req_test/1",
        api_key="sk-test",
        llm_call=AsyncMock(),
    )


@pytest.fixture
def tool():
    return LogExchangeRateTool()


# --- Tests ---

async def test_direct_rate(tool):
    """Direct rate value is inserted correctly."""
    conn = _FakeConn(insert_result={"id": 1, "rate": 1450, "created_at": "2026-03-04"})
    pool = _FakePool(conn)
    ctx = _make_context(pool)

    result = await tool.execute({"rate": 1450}, ctx)

    assert "Tipo de cambio registrado" in result
    assert "1,450 ARS" in result


async def test_calculated_from_amounts(tool):
    """Rate calculated from usd_amount + ars_amount."""
    conn = _FakeConn(insert_result={"id": 2, "rate": 1450, "created_at": "2026-03-04"})
    pool = _FakePool(conn)
    ctx = _make_context(pool)

    result = await tool.execute({"usd_amount": 100, "ars_amount": 145000}, ctx)

    assert "Tipo de cambio registrado" in result


async def test_rate_out_of_range_low(tool):
    """Rate below 100 → error."""
    pool = _FakePool(_FakeConn())
    ctx = _make_context(pool)

    result = await tool.execute({"rate": 50}, ctx)

    assert "fuera de rango" in result


async def test_rate_out_of_range_high(tool):
    """Rate above 100,000 → error."""
    pool = _FakePool(_FakeConn())
    ctx = _make_context(pool)

    result = await tool.execute({"rate": 200000}, ctx)

    assert "fuera de rango" in result


async def test_missing_data(tool):
    """No rate or amounts → error."""
    pool = _FakePool(_FakeConn())
    ctx = _make_context(pool)

    result = await tool.execute({}, ctx)

    assert "Falta el tipo de cambio" in result


async def test_zero_usd_amount(tool):
    """USD amount of 0 → error."""
    pool = _FakePool(_FakeConn())
    ctx = _make_context(pool)

    result = await tool.execute({"usd_amount": 0, "ars_amount": 145000}, ctx)

    assert "mayor a 0" in result


async def test_invalid_rate_string(tool):
    """Non-numeric rate → error."""
    pool = _FakePool(_FakeConn())
    ctx = _make_context(pool)

    result = await tool.execute({"rate": "abc"}, ctx)

    assert "no es válido" in result
