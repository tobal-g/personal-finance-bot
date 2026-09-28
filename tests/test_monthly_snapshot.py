"""Set TEST_DATABASE_URL to run PostgreSQL regressions using temporary tables."""

import argparse
from datetime import date
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncpg
import pytest

from scripts import monthly_snapshot
from scripts.monthly_snapshot import resolve_target_month, snapshot_sql


def test_resolve_target_month_uses_requested_month():
    assert resolve_target_month("2026-08", today=date(2026, 9, 26)) == date(2026, 8, 1)


def test_resolve_target_month_defaults_to_previous_month():
    assert resolve_target_month(None, today=date(2026, 9, 26)) == date(2026, 8, 1)


def test_resolve_target_month_rejects_invalid_month():
    with pytest.raises(ValueError, match="YYYY-MM"):
        resolve_target_month("2026-8", today=date(2026, 9, 26))


def test_resolve_target_month_rejects_current_or_future_month():
    with pytest.raises(ValueError, match="historical"):
        resolve_target_month("2026-09", today=date(2026, 9, 26))
    with pytest.raises(ValueError, match="historical"):
        resolve_target_month("2027-01", today=date(2026, 9, 26))


def test_cli_rejects_invalid_month_without_asyncio_traceback():
    script = Path(__file__).parents[1] / "scripts" / "monthly_snapshot.py"
    result = subprocess.run(
        [sys.executable, str(script), "--month", "2026-13"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "YYYY-MM" in result.stderr
    assert "Task exception was never retrieved" not in result.stderr


def test_backfill_sql_preserves_existing_historical_budget():
    sql = snapshot_sql(preserve_existing_budget=True)

    assert "budget_usd = monthly_snapshots.budget_usd" in sql
    assert "budget_usd = EXCLUDED.budget_usd" not in sql


def test_regular_snapshot_sql_refreshes_budget_at_month_close():
    sql = snapshot_sql(preserve_existing_budget=False)

    assert "budget_usd = EXCLUDED.budget_usd" in sql


@pytest.fixture
async def snapshot_db():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL snapshot regressions")
    conn = await asyncpg.connect(database_url, command_timeout=10)
    try:
        await conn.execute("""
            CREATE TEMP TABLE expenses (
                id serial PRIMARY KEY, tipo text, monto_ars numeric,
                monto_usd numeric, currency text, expense_date date
            );
            CREATE TEMP TABLE budget (tipo text PRIMARY KEY, amount_usd numeric);
            CREATE TEMP TABLE monthly_snapshots (
                year_month text, tipo text, total_ars numeric, total_usd numeric,
                transaction_count int, total_original_ars numeric,
                total_original_usd numeric, budget_usd numeric,
                created_at timestamptz DEFAULT now(), UNIQUE (year_month, tipo)
            );
        """)
        yield conn
    finally:
        await conn.close()


async def _run_backfill(conn, monkeypatch):
    # Keep the fixture's connection open so assertions can inspect its temp tables.
    wrapper = SimpleNamespace(
        fetchrow=conn.fetchrow, execute=conn.execute, fetch=conn.fetch,
        close=AsyncMock(),
    )
    monkeypatch.setenv("DATABASE_URL", "postgresql://test/snapshot")
    monkeypatch.setattr(
        monthly_snapshot.asyncpg, "connect", AsyncMock(return_value=wrapper)
    )
    await monthly_snapshot.main(argparse.Namespace(month="2026-08"))
    wrapper.close.assert_awaited_once()


@pytest.mark.parametrize("unrelated_budget", [False, True])
@pytest.mark.parametrize("frozen_budget", [None, 100])
async def test_backfill_zeroes_deleted_expenses(
    snapshot_db, monkeypatch, unrelated_budget, frozen_budget
):
    conn = snapshot_db
    # The category's last expense and current budget have both been deleted.
    await conn.execute("""
        INSERT INTO monthly_snapshots VALUES
            ('2026-08', 'Removed', 50000, 50, 2, 30000, 20, $1, now()),
            ('2026-07', 'Removed', 90000, 90, 1, 90000, 0, 200, now())
    """, frozen_budget)
    if unrelated_budget:
        await conn.execute("INSERT INTO budget VALUES ('Unrelated', 300)")

    await _run_backfill(conn, monkeypatch)

    row = await conn.fetchrow("SELECT * FROM monthly_snapshots WHERE year_month='2026-08'")
    for field in (
        "total_ars", "total_usd", "transaction_count",
        "total_original_ars", "total_original_usd",
    ):
        assert row[field] == 0
    assert row["budget_usd"] == frozen_budget
    assert await conn.fetchval(
        "SELECT COUNT(*) FROM monthly_snapshots WHERE year_month='2026-08'"
    ) == 1
    previous = await conn.fetchrow("SELECT * FROM monthly_snapshots WHERE year_month='2026-07'")
    assert previous["total_usd"] == 90
    assert previous["budget_usd"] == 200


@pytest.mark.parametrize("existing_snapshot", [False, True])
async def test_backfill_uses_only_historical_categories_and_budgets(
    snapshot_db, monkeypatch, existing_snapshot
):
    conn = snapshot_db
    if existing_snapshot:
        await conn.execute("""
            INSERT INTO monthly_snapshots VALUES
                ('2026-08', 'Food', 99000, 99, 1, 99000, 0, 100, now())
        """)
    await conn.execute("""
        INSERT INTO budget VALUES
            ('Food', 900), ('NewExpense', 200), ('BudgetOnly', 300);
        INSERT INTO expenses (tipo, monto_ars, monto_usd, currency, expense_date) VALUES
            ('Food', 12000, 12, 'ARS', '2026-08-01'),
            ('Food', 14000, 14, 'USD', '2026-08-31'),
            ('Food', 90000, 90, 'ARS', '2026-07-31'),
            ('Food', 80000, 80, 'USD', '2026-09-01'),
            ('NewExpense', 5000, 5, 'USD', '2026-08-15');
    """)

    # Repeated runs must neither duplicate totals nor introduce today's budgets.
    for _ in range(2):
        await _run_backfill(conn, monkeypatch)
        rows = {row["tipo"]: row for row in await conn.fetch("SELECT * FROM monthly_snapshots")}
        assert set(rows) == {"Food", "NewExpense"}
        food = rows["Food"]
        assert food["total_ars"] == 26000
        assert food["total_usd"] == 26
        assert food["transaction_count"] == 2
        assert food["total_original_ars"] == 12000
        assert food["total_original_usd"] == 14
        assert food["budget_usd"] == (100 if existing_snapshot else None)
        assert rows["NewExpense"]["total_usd"] == 5
        assert rows["NewExpense"]["budget_usd"] is None


async def test_scheduled_snapshot_still_refreshes_current_budgets(snapshot_db):
    conn = snapshot_db
    await conn.execute("""
        INSERT INTO monthly_snapshots VALUES
            ('2026-08', 'Food', 10000, 10, 1, 10000, 0, 100, now());
        INSERT INTO budget VALUES ('Food', 900), ('BudgetOnly', 300);
        INSERT INTO expenses (tipo, monto_ars, monto_usd, currency, expense_date)
        VALUES ('Food', 12000, 12, 'USD', '2026-08-20');
    """)
    await conn.execute(
        snapshot_sql(preserve_existing_budget=False), date(2026, 8, 1), date(2026, 9, 1)
    )
    rows = {row["tipo"]: row for row in await conn.fetch("SELECT * FROM monthly_snapshots")}
    assert set(rows) == {"Food", "BudgetOnly"}
    assert rows["Food"]["budget_usd"] == 900
    assert rows["Food"]["total_usd"] == 12
    assert rows["BudgetOnly"]["budget_usd"] == 300
    assert rows["BudgetOnly"]["total_usd"] == 0
    assert rows["BudgetOnly"]["transaction_count"] == 0
