"""Tests for bot.tools.modify_budget."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from bot.tools.base import ToolContext
from bot.tools.modify_budget import ModifyBudgetTool


# --- Fixtures ---


class _FakeConn:
    def __init__(self, budget=None, expense_types=None, fetchrow_result=None):
        self._budget = budget or []
        self._expense_types = expense_types or []
        self._fetchrow_result = fetchrow_result
        self.last_fetchrow_args = None
        self.executed_queries = []

    async def fetch(self, query, *args):
        if "budget" in query.lower():
            return [
                {"tipo": t, "amount_usd": a} for t, a in self._budget
            ]
        # expense_types
        return [{"name": t} for t in self._expense_types]

    async def fetchrow(self, query, *args):
        self.last_fetchrow_args = (query, args)
        return self._fetchrow_result

    async def execute(self, query, *args):
        self.executed_queries.append((query, args))


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
    return ModifyBudgetTool()


# --- Tests ---


async def test_update_budget(tool):
    """Update existing budget category."""
    conn = _FakeConn(
        budget=[("Café", 50), ("Transporte", 100)],
        expense_types=["Café", "Transporte"],
        fetchrow_result={"tipo": "Café", "amount_usd": 75},
    )
    pool = _FakePool(conn)
    llm_json = json.dumps({"action": "update", "tipo": "Café", "amount_usd": 75})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "cafe ahora es 75 usd"}, ctx)

    assert "actualizado" in result.lower()
    assert "Café" in result
    assert "75" in result
    ctx.llm_call.assert_called_once()


async def test_add_budget(tool):
    """Add new budget category."""
    conn = _FakeConn(
        budget=[("Café", 50)],
        expense_types=["Café", "Mascotas"],
        fetchrow_result={"tipo": "Mascotas", "amount_usd": 30},
    )
    pool = _FakePool(conn)
    llm_json = json.dumps({"action": "add", "tipo": "Mascotas", "amount_usd": 30})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "agrega mascotas con 30 usd"}, ctx)

    assert "agregada" in result.lower()
    assert "Mascotas" in result
    assert "30" in result
    # Verify expense_type was also created
    assert any("expense_types" in q for q, _ in conn.executed_queries)


async def test_remove_budget(tool):
    """Remove existing budget category."""
    conn = _FakeConn(
        budget=[("Café", 50), ("Mascotas", 30)],
        expense_types=["Café", "Mascotas"],
        fetchrow_result={"tipo": "Mascotas"},
    )
    pool = _FakePool(conn)
    llm_json = json.dumps({"action": "remove", "tipo": "Mascotas"})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "elimina mascotas del presupuesto"}, ctx)

    assert "eliminada" in result.lower()
    assert "Mascotas" in result
    # Verify expense_type was deactivated
    assert any("active = false" in q for q, _ in conn.executed_queries)


async def test_update_nonexistent_tipo(tool):
    """Update a tipo that doesn't exist in budget → error."""
    conn = _FakeConn(
        budget=[("Café", 50)],
        expense_types=["Café", "Transporte"],
    )
    pool = _FakePool(conn)
    llm_json = json.dumps({"action": "update", "tipo": "Inventado", "amount_usd": 100})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "inventado 100 usd"}, ctx)

    assert "No existe" in result


async def test_add_already_exists(tool):
    """Add a tipo that already exists in budget → error."""
    conn = _FakeConn(
        budget=[("Café", 50)],
        expense_types=["Café"],
    )
    pool = _FakePool(conn)
    llm_json = json.dumps({"action": "add", "tipo": "Café", "amount_usd": 100})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "agrega cafe con 100"}, ctx)

    assert "ya existe" in result


async def test_remove_nonexistent(tool):
    """Remove a tipo not in budget → error."""
    conn = _FakeConn(
        budget=[("Café", 50)],
        expense_types=["Café", "Transporte"],
    )
    pool = _FakePool(conn)
    llm_json = json.dumps({"action": "remove", "tipo": "Transporte"})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "elimina transporte"}, ctx)

    assert "No existe" in result


async def test_invalid_llm_response(tool):
    """LLM returns garbage → error message."""
    conn = _FakeConn(
        budget=[("Café", 50)],
        expense_types=["Café"],
    )
    pool = _FakePool(conn)
    ctx = _make_context(pool, llm_return="not valid json at all")

    result = await tool.execute({"description": "algo"}, ctx)

    assert "No pude interpretar" in result


async def test_missing_description(tool):
    """Empty description → error."""
    pool = _FakePool(_FakeConn())
    ctx = _make_context(pool)

    result = await tool.execute({}, ctx)

    assert "No entendí" in result


async def test_update_missing_amount(tool):
    """Update without amount → error."""
    conn = _FakeConn(
        budget=[("Café", 50)],
        expense_types=["Café"],
    )
    pool = _FakePool(conn)
    llm_json = json.dumps({"action": "update", "tipo": "Café"})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "cafe sin monto"}, ctx)

    assert "Falta el monto" in result


async def test_invalid_action(tool):
    """LLM returns unknown action → error."""
    conn = _FakeConn(
        budget=[("Café", 50)],
        expense_types=["Café"],
    )
    pool = _FakePool(conn)
    llm_json = json.dumps({"action": "destroy", "tipo": "Café"})
    ctx = _make_context(pool, llm_return=llm_json)

    result = await tool.execute({"description": "destruí cafe"}, ctx)

    assert "No pude interpretar" in result
