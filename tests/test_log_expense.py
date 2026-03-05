"""Tests for bot.tools.log_expense."""

import json
from contextlib import asynccontextmanager
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest

from bot.tools.base import ToolContext
from bot.tools.log_expense import LogExpenseTool, _parse_date


# --- Fixtures ---

class _FakeConn:
    def __init__(self, expense_types=None, insert_result=None, insert_exc=None):
        self._expense_types = expense_types or []
        self._insert_result = insert_result
        self._insert_exc = insert_exc

    async def fetch(self, query, *args):
        return [{"name": t} for t in self._expense_types]

    async def fetchrow(self, query, *args):
        if self._insert_exc:
            raise self._insert_exc
        return self._insert_result


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def _make_context(pool, llm_return=None):
    llm_call = AsyncMock(return_value=llm_return or "")
    return ToolContext(
        db_pool=pool,
        chat_id=-100,
        request_id="req_test",
        task_id="req_test/1",
        api_key="sk-test",
        llm_call=llm_call,
    )


# --- _parse_date tests ---

def test_parse_date_hoy():
    assert _parse_date("hoy") == date.today()


def test_parse_date_ayer():
    assert _parse_date("ayer") == date.today() - timedelta(days=1)


def test_parse_date_iso():
    assert _parse_date("2026-03-01") == date(2026, 3, 1)


def test_parse_date_empty():
    assert _parse_date("") == date.today()


# --- LogExpenseTool tests ---

@pytest.fixture
def tool():
    return LogExpenseTool()


async def test_log_expense_ars(tool):
    """Valid ARS expense logs correctly."""
    types = ["Café", "Transporte", "Supermercado"]
    insert_row = {
        "expense_id": 42,
        "monto_ars_final": 3900,
        "monto_usd_final": 2.69,
        "exchange_rate_used": 1450,
    }
    conn = _FakeConn(expense_types=types, insert_result=insert_row)
    pool = _FakePool(conn)
    llm_json = json.dumps({"tipo": "Café", "motivo": "cafe"})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute(
        {"amount": 3900, "currency": "ARS", "description": "cafe", "date": "hoy"},
        ctx,
    )

    assert "Anotado" in result
    assert "3,900 ARS" in result
    assert "Café" in result
    assert "cafe" in result
    ctx.llm_call.assert_called_once()


async def test_log_expense_usd(tool):
    """USD expense passes correct currency."""
    types = ["Café"]
    insert_row = {
        "expense_id": 43,
        "monto_ars_final": 14500,
        "monto_usd_final": 10.0,
        "exchange_rate_used": 1450,
    }
    conn = _FakeConn(expense_types=types, insert_result=insert_row)
    pool = _FakePool(conn)
    llm_json = json.dumps({"tipo": "Café", "motivo": "coffee"})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute(
        {"amount": 10, "currency": "USD", "description": "coffee", "date": "hoy"},
        ctx,
    )

    assert "14,500 ARS" in result
    assert "$10.00 USD" in result


async def test_log_expense_invalid_tipo(tool):
    """LLM returns tipo not in active list → error."""
    types = ["Café", "Transporte"]
    conn = _FakeConn(expense_types=types)
    pool = _FakePool(conn)
    llm_json = json.dumps({"tipo": "Inventado", "motivo": "test"})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute(
        {"amount": 1000, "description": "algo"},
        ctx,
    )

    assert "no es válido" in result
    assert "Café" in result


async def test_log_expense_no_exchange_rate(tool):
    """DB raises 'No hay tipo de cambio' → prescribed error."""
    types = ["Café"]
    exc = Exception("No hay tipo de cambio registrado")
    conn = _FakeConn(expense_types=types, insert_exc=exc)
    pool = _FakePool(conn)
    llm_json = json.dumps({"tipo": "Café", "motivo": "cafe"})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute(
        {"amount": 5000, "description": "cafe"},
        ctx,
    )

    assert "No hay tipo de cambio registrado" in result
    assert "tipo de cambio" in result


async def test_log_expense_date_ayer(tool):
    """Date 'ayer' is parsed correctly."""
    types = ["Café"]
    yesterday = date.today() - timedelta(days=1)
    insert_row = {
        "expense_id": 44,
        "monto_ars_final": 2000,
        "monto_usd_final": 1.38,
        "exchange_rate_used": 1450,
    }
    conn = _FakeConn(expense_types=types, insert_result=insert_row)
    pool = _FakePool(conn)
    llm_json = json.dumps({"tipo": "Café", "motivo": "cafe"})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute(
        {"amount": 2000, "description": "cafe", "date": "ayer"},
        ctx,
    )

    expected_date = yesterday.strftime("%d/%m/%Y")
    assert expected_date in result


async def test_log_expense_missing_amount(tool):
    """Missing amount returns error."""
    pool = _FakePool(_FakeConn())
    ctx = _make_context(pool)

    result = await tool.execute({"description": "cafe"}, ctx)

    assert "Falta el monto" in result


async def test_log_expense_bad_date(tool):
    """Unparseable date returns error."""
    pool = _FakePool(_FakeConn())
    ctx = _make_context(pool)

    result = await tool.execute(
        {"amount": 1000, "description": "cafe", "date": "not-a-date"},
        ctx,
    )

    assert "No pude interpretar la fecha" in result
