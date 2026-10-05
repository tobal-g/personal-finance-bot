"""Monthly snapshot cron job.

Aggregates the previous month's expenses + budget into ``monthly_snapshots``.
Runs on the 1st of each month via Railway cron: 0 4 1 * * (4am UTC = 1am Argentina).

Pass ``--month YYYY-MM`` to backfill a historical month. Backfills update the
expense-derived totals but preserve any budget already frozen in the snapshot.
New historical categories have an unknown (NULL) budget, never today's budget.
"""

import argparse
import asyncio
import os
import re
import sys
from datetime import date, datetime, timezone

import asyncpg

_CONNECT_TIMEOUT = 30  # seconds
_STATEMENT_TIMEOUT = 30  # seconds
_GLOBAL_TIMEOUT = 120  # seconds
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def resolve_target_month(month: str | None, *, today: date | None = None) -> date:
    """Return the first day of the requested month or of the previous month."""
    today = today or datetime.now(timezone.utc).date()
    if month is not None:
        match = _MONTH_RE.fullmatch(month)
        if not match:
            raise ValueError("--month must use YYYY-MM format")
        try:
            requested_month = date(int(match.group(1)), int(match.group(2)), 1)
        except ValueError as exc:
            raise ValueError("--month must use YYYY-MM format") from exc
        if requested_month >= date(today.year, today.month, 1):
            raise ValueError("--month must be a historical month before the current month")
        return requested_month

    if today.month == 1:
        return date(today.year - 1, 12, 1)
    return date(today.year, today.month - 1, 1)


def next_month(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def snapshot_sql(*, preserve_existing_budget: bool) -> str:
    """Build the monthly upsert, retaining frozen budgets during backfills."""
    # Existing snapshots also keep categories whose last expense was deleted in
    # the aggregation, so their totals are reset to zero during a backfill.
    budget_source = (
        """SELECT tipo, budget_usd
    FROM monthly_snapshots
    WHERE year_month = to_char($1::date, 'YYYY-MM')"""
        if preserve_existing_budget
        else "SELECT tipo, amount_usd AS budget_usd FROM budget"
    )
    budget_update = (
        "monthly_snapshots.budget_usd"
        if preserve_existing_budget
        else "EXCLUDED.budget_usd"
    )
    return f"""\
WITH month_expenses AS (
    SELECT *
    FROM expenses
    WHERE expense_date >= $1::date
      AND expense_date < $2::date
), month_budget AS (
    {budget_source}
)
INSERT INTO monthly_snapshots (
    year_month, tipo, total_ars, total_usd, transaction_count,
    total_original_ars, total_original_usd, budget_usd
)
SELECT
    to_char($1::date, 'YYYY-MM'),
    COALESCE(e.tipo, b.tipo),
    COALESCE(SUM(e.monto_ars), 0),
    COALESCE(SUM(e.monto_usd), 0),
    COUNT(e.id),
    COALESCE(SUM(CASE WHEN e.currency = 'ARS' THEN e.monto_ars ELSE 0 END), 0),
    COALESCE(SUM(CASE WHEN e.currency = 'USD' THEN e.monto_usd ELSE 0 END), 0),
    b.budget_usd
FROM month_budget b
FULL OUTER JOIN month_expenses e ON e.tipo = b.tipo
GROUP BY COALESCE(e.tipo, b.tipo), b.budget_usd
ON CONFLICT (year_month, tipo) DO UPDATE SET
    total_ars = EXCLUDED.total_ars,
    total_usd = EXCLUDED.total_usd,
    transaction_count = EXCLUDED.transaction_count,
    total_original_ars = EXCLUDED.total_original_ars,
    total_original_usd = EXCLUDED.total_original_usd,
    budget_usd = {budget_update},
    created_at = now()
"""


EXPENSE_COUNT_SQL = """\
SELECT COUNT(*) AS cnt
FROM expenses
WHERE expense_date >= $1::date
  AND expense_date < $2::date
"""
BUDGET_COUNT_SQL = "SELECT COUNT(*) AS cnt FROM budget"
VERIFY_SQL = """\
SELECT tipo, total_usd, budget_usd, transaction_count
FROM monthly_snapshots
WHERE year_month = $1
ORDER BY total_usd DESC
"""


def _parse_backfill_month(value: str) -> str:
    try:
        resolve_target_month(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or backfill expense snapshots")
    parser.add_argument(
        "--month",
        metavar="YYYY-MM",
        type=_parse_backfill_month,
        help="Backfill this historical month; preserve frozen budgets and leave unknown budgets unset",
    )
    return parser.parse_args()


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


async def main(args: argparse.Namespace) -> None:
    try:
        month_start = resolve_target_month(args.month)
    except ValueError as exc:
        log(f"snapshot.error | {exc}")
        sys.exit(2)
    month_end = next_month(month_start)
    target_month = month_start.strftime("%Y-%m")
    preserve_existing_budget = args.month is not None

    log("snapshot.start | monthly snapshot cron starting")
    log(
        "snapshot.target | "
        f"target_month={target_month} mode={'backfill' if args.month else 'scheduled'} "
        f"preserve_existing_budget={preserve_existing_budget}"
    )

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log("snapshot.error | DATABASE_URL env var not set — aborting")
        sys.exit(1)

    log("snapshot.connect | connecting to database")
    try:
        conn = await asyncpg.connect(
            database_url,
            timeout=_CONNECT_TIMEOUT,
            command_timeout=_STATEMENT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log(f"snapshot.error | database connection timed out after {_CONNECT_TIMEOUT}s")
        sys.exit(1)
    except Exception as exc:
        log(f"snapshot.error | failed to connect to database — {exc}")
        sys.exit(1)
    log("snapshot.connect | connected successfully")

    try:
        try:
            expense_row = await conn.fetchrow(EXPENSE_COUNT_SQL, month_start, month_end)
            budget_row = await conn.fetchrow(BUDGET_COUNT_SQL)
            expense_count = expense_row["cnt"]
            budget_count = budget_row["cnt"]
            log(
                f"snapshot.source | expenses_in_month={expense_count} "
                f"budget_categories={budget_count}"
            )

            # Empty sources can still require clearing stale historical totals.
            log("snapshot.execute | running snapshot upsert")
            result = await conn.execute(
                snapshot_sql(preserve_existing_budget=preserve_existing_budget),
                month_start,
                month_end,
            )
            row_count = result.split()[-1] if result else "unknown"
            log(f"snapshot.execute | upsert complete — rows_upserted={row_count}")
        except asyncio.TimeoutError:
            log(f"snapshot.error | SQL statement timed out after {_STATEMENT_TIMEOUT}s")
            sys.exit(1)
        except Exception as exc:
            log(f"snapshot.error | snapshot failed — {exc}")
            sys.exit(1)

        try:
            rows = await conn.fetch(VERIFY_SQL, target_month)
            total_usd = sum(float(row["total_usd"]) for row in rows)
            with_budget = sum(1 for row in rows if row["budget_usd"] is not None)
            without_budget = sum(1 for row in rows if row["budget_usd"] is None)
            total_transactions = sum(row["transaction_count"] for row in rows)
            total_budget = sum(
                float(row["budget_usd"]) for row in rows if row["budget_usd"] is not None
            )
            log(
                f"snapshot.verify | month={target_month} categories={len(rows)} "
                f"total_spent_usd={total_usd:.2f} total_budget_usd={total_budget:.2f} "
                f"total_transactions={total_transactions} categories_with_budget={with_budget} "
                f"categories_without_budget={without_budget}"
            )
            log("snapshot.details | top categories by spending:")
            for row in rows[:5]:
                budget_str = (
                    f"${float(row['budget_usd']):.2f}"
                    if row["budget_usd"] is not None
                    else "no budget"
                )
                log(
                    f"  {row['tipo']}: spent=${float(row['total_usd']):.2f} "
                    f"budget={budget_str} txns={row['transaction_count']}"
                )
        except Exception as exc:
            log(f"snapshot.warn | verification failed (upsert already succeeded) — {exc}")

        log(f"snapshot.complete | monthly snapshot for {target_month} finished successfully")
    finally:
        try:
            await asyncio.wait_for(conn.close(), timeout=5.0)
        except Exception:
            log("snapshot.warn | connection close timed out or failed")
        log("snapshot.cleanup | database connection closed")


async def run_with_timeout(args: argparse.Namespace) -> None:
    try:
        await asyncio.wait_for(main(args), timeout=_GLOBAL_TIMEOUT)
    except asyncio.TimeoutError:
        log(f"snapshot.timeout | script exceeded {_GLOBAL_TIMEOUT}s global timeout — force exiting")
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(run_with_timeout(parse_args()))
