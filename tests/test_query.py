"""Tests for bot.tools.query."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import asyncpg
import pytest

from bot.tools.base import ToolContext
from bot.tools.query import QueryTool, validate_sql


# --- Helpers ---

class _FakeConn:
    def __init__(self, expense_types=None, query_rows=None, raise_on_fetch=None):
        self._expense_types = expense_types or []
        self._query_rows = query_rows or []
        self._raise_on_fetch = raise_on_fetch
        self._call_count = 0

    async def fetch(self, query, *args):
        self._call_count += 1
        if "expense_types" in query:
            return self._expense_types
        if self._raise_on_fetch:
            raise self._raise_on_fetch
        return self._query_rows

    async def execute(self, query, *args):
        pass


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    @asynccontextmanager
    async def acquire(self):
        yield self._conn


def _make_context(pool, llm_returns=None):
    """Create a ToolContext with mocked LLM that returns values in sequence."""
    returns = list(llm_returns or [""])
    llm_call = AsyncMock(side_effect=returns)
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
    return QueryTool()


EXPENSE_TYPES = [{"name": "Café"}, {"name": "Transporte"}, {"name": "Comida"}]


# --- SQL Validation Tests ---

def test_sql_validation_rejects_delete():
    assert validate_sql("DELETE FROM expenses") is False


def test_sql_validation_rejects_multi_statement():
    assert validate_sql("SELECT 1; DROP TABLE expenses") is False


def test_sql_validation_rejects_insert():
    assert validate_sql("INSERT INTO expenses (tipo) VALUES ('x')") is False


def test_sql_validation_accepts_select():
    assert validate_sql("SELECT * FROM expenses WHERE tipo = 'Café'") is True


def test_sql_validation_case_insensitive():
    assert validate_sql("select count(*) from expenses") is True


# --- Full Flow Tests ---

async def test_full_query_flow(tool):
    """Mocked LLM (2 calls) + mocked DB → formatted response."""
    sql_response = json.dumps({"sql": "SELECT tipo, SUM(monto_ars) FROM expenses GROUP BY tipo", "explanation": "Sum by type"})
    format_response = "Gastaste $5,000 en Café y $3,000 en Transporte."

    query_rows = [{"tipo": "Café", "sum": 5000}, {"tipo": "Transporte", "sum": 3000}]
    conn = _FakeConn(expense_types=EXPENSE_TYPES, query_rows=query_rows)
    pool = _FakePool(conn)
    ctx = _make_context(pool, llm_returns=[sql_response, format_response])

    result = await tool.execute({"question": "cuanto gaste por tipo?"}, ctx)

    assert result == "Gastaste $5,000 en Café y $3,000 en Transporte."
    assert ctx.llm_call.call_count == 2


async def test_empty_results(tool):
    """DB returns no rows → 'No encontré resultados'."""
    sql_response = json.dumps({"sql": "SELECT * FROM expenses WHERE tipo = 'Nada'", "explanation": "nothing"})

    conn = _FakeConn(expense_types=EXPENSE_TYPES, query_rows=[])
    pool = _FakePool(conn)
    ctx = _make_context(pool, llm_returns=[sql_response])

    result = await tool.execute({"question": "gastos en nada?"}, ctx)

    assert "No encontré resultados" in result


async def test_db_timeout(tool):
    """asyncpg timeout → friendly message."""
    sql_response = json.dumps({"sql": "SELECT * FROM expenses", "explanation": "all"})

    conn = _FakeConn(
        expense_types=EXPENSE_TYPES,
        raise_on_fetch=asyncpg.QueryCanceledError("canceling statement due to statement timeout"),
    )
    pool = _FakePool(conn)
    ctx = _make_context(pool, llm_returns=[sql_response])

    result = await tool.execute({"question": "todos los gastos"}, ctx)

    assert "tardó más de 5 segundos" in result


async def test_db_error(tool):
    """PostgresError → friendly message."""
    sql_response = json.dumps({"sql": "SELECT * FROM nonexistent", "explanation": "bad"})

    conn = _FakeConn(
        expense_types=EXPENSE_TYPES,
        raise_on_fetch=asyncpg.UndefinedTableError("relation nonexistent does not exist"),
    )
    pool = _FakePool(conn)
    ctx = _make_context(pool, llm_returns=[sql_response])

    result = await tool.execute({"question": "tabla inexistente"}, ctx)

    assert "falló al ejecutarse" in result


async def test_response_truncation(tool):
    """Long response truncated at 4000 chars."""
    sql_response = json.dumps({"sql": "SELECT * FROM expenses", "explanation": "all"})
    long_response = "x" * 5000

    query_rows = [{"id": 1}]
    conn = _FakeConn(expense_types=EXPENSE_TYPES, query_rows=query_rows)
    pool = _FakePool(conn)
    ctx = _make_context(pool, llm_returns=[sql_response, long_response])

    result = await tool.execute({"question": "algo"}, ctx)

    assert len(result) == 4000


async def test_missing_question(tool):
    """No question in data → error message."""
    conn = _FakeConn(expense_types=EXPENSE_TYPES)
    pool = _FakePool(conn)
    ctx = _make_context(pool)

    result = await tool.execute({}, ctx)

    assert "No recibí una pregunta" in result


async def test_llm_bad_json(tool):
    """LLM returns unparseable JSON → error."""
    conn = _FakeConn(expense_types=EXPENSE_TYPES)
    pool = _FakePool(conn)
    ctx = _make_context(pool, llm_returns=["not valid json at all"])

    result = await tool.execute({"question": "cuanto gaste?"}, ctx)

    assert "No pude armar una consulta válida" in result
