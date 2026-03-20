"""Monthly snapshot cron job.

Aggregates the previous month's expenses + budget into monthly_snapshots.
Runs on the 1st of each month via Railway cron: 0 4 1 * * (4am UTC = 1am Argentina).

Safe to re-run — ON CONFLICT updates existing rows.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

import asyncpg

_CONNECT_TIMEOUT = 30    # seconds
_STATEMENT_TIMEOUT = 30  # seconds
_GLOBAL_TIMEOUT = 120    # seconds

SNAPSHOT_SQL = """\
WITH month_expenses AS (
    SELECT *
    FROM expenses
    WHERE expense_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '1 month'
      AND expense_date < date_trunc('month', CURRENT_DATE)
)
INSERT INTO monthly_snapshots (
    year_month, tipo, total_ars, total_usd, transaction_count,
    total_original_ars, total_original_usd, budget_usd
)
SELECT
    to_char(date_trunc('month', CURRENT_DATE) - INTERVAL '1 day', 'YYYY-MM'),
    COALESCE(e.tipo, b.tipo),
    COALESCE(SUM(e.monto_ars), 0),
    COALESCE(SUM(e.monto_usd), 0),
    COUNT(e.id),
    COALESCE(SUM(CASE WHEN e.currency = 'ARS' THEN e.monto_ars ELSE 0 END), 0),
    COALESCE(SUM(CASE WHEN e.currency = 'USD' THEN e.monto_usd ELSE 0 END), 0),
    b.amount_usd
FROM budget b
FULL OUTER JOIN month_expenses e ON e.tipo = b.tipo
GROUP BY COALESCE(e.tipo, b.tipo), b.amount_usd
ON CONFLICT (year_month, tipo) DO UPDATE SET
    total_ars = EXCLUDED.total_ars,
    total_usd = EXCLUDED.total_usd,
    transaction_count = EXCLUDED.transaction_count,
    total_original_ars = EXCLUDED.total_original_ars,
    total_original_usd = EXCLUDED.total_original_usd,
    budget_usd = EXCLUDED.budget_usd,
    created_at = now()
"""

TARGET_MONTH_SQL = """\
SELECT to_char(date_trunc('month', CURRENT_DATE) - INTERVAL '1 day', 'YYYY-MM') AS target_month
"""

EXPENSE_COUNT_SQL = """\
SELECT COUNT(*) AS cnt
FROM expenses
WHERE expense_date >= date_trunc('month', CURRENT_DATE) - INTERVAL '1 month'
  AND expense_date < date_trunc('month', CURRENT_DATE)
"""

BUDGET_COUNT_SQL = "SELECT COUNT(*) AS cnt FROM budget"

VERIFY_SQL = """\
SELECT tipo, total_usd, budget_usd, transaction_count
FROM monthly_snapshots
WHERE year_month = $1
ORDER BY total_usd DESC
"""


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"[{ts}] {msg}")


async def main() -> None:
    log("snapshot.start | monthly snapshot cron starting")

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log("snapshot.error | DATABASE_URL env var not set — aborting")
        sys.exit(1)

    # Connect
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
        # --- Critical block: target month, source counts, upsert ---
        try:
            # Determine target month
            row = await conn.fetchrow(TARGET_MONTH_SQL)
            target_month = row["target_month"]
            log(f"snapshot.target | target_month={target_month}")

            # Count source data
            expense_row = await conn.fetchrow(EXPENSE_COUNT_SQL)
            budget_row = await conn.fetchrow(BUDGET_COUNT_SQL)
            expense_count = expense_row["cnt"]
            budget_count = budget_row["cnt"]
            log(
                f"snapshot.source | expenses_in_month={expense_count} "
                f"budget_categories={budget_count}"
            )

            if expense_count == 0 and budget_count == 0:
                log(
                    "snapshot.skip | no expenses and no budget categories found "
                    "— nothing to snapshot"
                )
                return

            # Execute upsert
            log("snapshot.execute | running snapshot upsert")
            result = await conn.execute(SNAPSHOT_SQL)
            row_count = result.split()[-1] if result else "unknown"
            log(f"snapshot.execute | upsert complete — rows_upserted={row_count}")

        except asyncio.TimeoutError:
            log(f"snapshot.error | SQL statement timed out after {_STATEMENT_TIMEOUT}s")
            sys.exit(1)
        except Exception as exc:
            log(f"snapshot.error | snapshot failed — {exc}")
            sys.exit(1)

        # --- Non-critical block: verification & detail logging ---
        try:
            rows = await conn.fetch(VERIFY_SQL, target_month)
            total_usd = sum(float(r["total_usd"]) for r in rows)
            with_budget = sum(1 for r in rows if r["budget_usd"] is not None)
            without_budget = sum(1 for r in rows if r["budget_usd"] is None)
            total_transactions = sum(r["transaction_count"] for r in rows)
            total_budget = sum(
                float(r["budget_usd"]) for r in rows if r["budget_usd"] is not None
            )

            log(
                f"snapshot.verify | month={target_month} "
                f"categories={len(rows)} "
                f"total_spent_usd={total_usd:.2f} "
                f"total_budget_usd={total_budget:.2f} "
                f"total_transactions={total_transactions} "
                f"categories_with_budget={with_budget} "
                f"categories_without_budget={without_budget}"
            )

            # Log top 5 categories by spending
            log("snapshot.details | top categories by spending:")
            for r in rows[:5]:
                budget_str = (
                    f"${float(r['budget_usd']):.2f}"
                    if r["budget_usd"] is not None
                    else "no budget"
                )
                log(
                    f"  {r['tipo']}: "
                    f"spent=${float(r['total_usd']):.2f} "
                    f"budget={budget_str} "
                    f"txns={r['transaction_count']}"
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


async def run_with_timeout() -> None:
    try:
        await asyncio.wait_for(main(), timeout=_GLOBAL_TIMEOUT)
    except asyncio.TimeoutError:
        log(f"snapshot.timeout | script exceeded {_GLOBAL_TIMEOUT}s global timeout — force exiting")
        sys.exit(2)


if __name__ == "__main__":
    asyncio.run(run_with_timeout())
