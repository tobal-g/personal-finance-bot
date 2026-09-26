from datetime import date
from pathlib import Path
import subprocess
import sys

import pytest

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
