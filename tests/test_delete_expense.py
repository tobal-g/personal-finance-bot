"""Tests for bot.tools.delete_expense."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from bot.tools.base import ToolContext
from bot.tools.delete_expense import DeleteExpenseTool


# --- Fixtures ---

SAMPLE_EXPENSES = [
    {"id": 10, "tipo": "Café", "monto_ars": 3900, "monto_usd": 2.69, "currency": "ARS", "motivo": "cafe", "expense_date": "2026-03-04"},
    {"id": 11, "tipo": "Transporte", "monto_ars": 5000, "monto_usd": 3.45, "currency": "ARS", "motivo": "uber", "expense_date": "2026-03-04"},
]


class _FakeConn:
    def __init__(self, expenses=None, delete_result=None):
        self._expenses = expenses if expenses is not None else []
        self._delete_result = delete_result
        self._call_count = 0

    async def fetch(self, query, *args):
        return self._expenses

    async def fetchrow(self, query, *args):
        return self._delete_result


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


@pytest.fixture
def tool():
    return DeleteExpenseTool()


# --- Tests ---

async def test_delete_valid(tool):
    """Successfully delete an identified expense."""
    delete_row = {"id": 10, "tipo": "Café", "monto_ars": 3900, "monto_usd": 2.69, "motivo": "cafe"}
    conn = _FakeConn(expenses=SAMPLE_EXPENSES, delete_result=delete_row)
    pool = _FakePool(conn)
    llm_json = json.dumps({"expense_id": 10})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "el cafe"}, ctx)

    assert "Eliminado" in result
    assert "3,900 ARS" in result
    assert "Café" in result


async def test_delete_id_not_in_list(tool):
    """LLM picks an ID not in the recent list → error."""
    conn = _FakeConn(expenses=SAMPLE_EXPENSES)
    pool = _FakePool(conn)
    llm_json = json.dumps({"expense_id": 999})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "algo"}, ctx)

    assert "No pude identificar" in result


async def test_delete_already_gone(tool):
    """Expense exists in list but RETURNING is empty (race condition)."""
    conn = _FakeConn(expenses=SAMPLE_EXPENSES, delete_result=None)
    pool = _FakePool(conn)
    llm_json = json.dumps({"expense_id": 10})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "el cafe"}, ctx)

    assert "ya no existe" in result


async def test_delete_empty_list(tool):
    """No recent expenses → message."""
    conn = _FakeConn(expenses=[])
    pool = _FakePool(conn)
    ctx = _make_context(pool)

    result = await tool.execute({"description": "algo"}, ctx)

    assert "No hay gastos recientes" in result


async def test_delete_llm_parse_failure(tool):
    """LLM returns invalid JSON → error."""
    conn = _FakeConn(expenses=SAMPLE_EXPENSES)
    pool = _FakePool(conn)
    ctx = _make_context(pool, llm_return="not json")

    result = await tool.execute({"description": "algo"}, ctx)

    assert "No pude identificar" in result
