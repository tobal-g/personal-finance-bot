"""SQL query constants."""

GET_LATEST_EXCHANGE_RATE = (
    "SELECT id, rate, created_at FROM exchange_rates ORDER BY created_at DESC LIMIT 1"
)

GET_ACTIVE_EXPENSE_TYPES = (
    "SELECT name FROM expense_types WHERE active = true ORDER BY name"
)

INSERT_EXPENSE = "SELECT * FROM insert_expense($1, $2, $3, $4, $5)"
# params: (tipo, monto, currency, motivo, expense_date)
# returns: (expense_id, monto_ars_final, monto_usd_final, exchange_rate_used)

GET_LAST_N_EXPENSES = """
    SELECT id, tipo, monto_ars, monto_usd, currency, motivo, expense_date
    FROM expenses ORDER BY created_at DESC LIMIT $1
"""

DELETE_EXPENSE = (
    "DELETE FROM expenses WHERE id = $1 RETURNING id, tipo, monto_ars, monto_usd, motivo"
)

INSERT_EXCHANGE_RATE = (
    "INSERT INTO exchange_rates (rate) VALUES ($1) RETURNING id, rate, created_at"
)

GET_BUDGET = "SELECT tipo, amount_usd FROM budget ORDER BY tipo"

UPDATE_BUDGET = (
    "UPDATE budget SET amount_usd = $1, updated_at = now() WHERE tipo = $2 "
    "RETURNING tipo, amount_usd"
)

INSERT_BUDGET = (
    "INSERT INTO budget (tipo, amount_usd) VALUES ($1, $2) "
    "RETURNING tipo, amount_usd"
)

DELETE_BUDGET = "DELETE FROM budget WHERE tipo = $1 RETURNING tipo"

INSERT_EXPENSE_TYPE = (
    "INSERT INTO expense_types (name) VALUES ($1) ON CONFLICT (name) DO UPDATE "
    "SET active = true RETURNING name"
)

DEACTIVATE_EXPENSE_TYPE = (
    "UPDATE expense_types SET active = false WHERE name = $1 RETURNING name"
)

DB_SCHEMA_CONTEXT = """\
## Database Schema

### Tables

**expenses**
- id (serial PK)
- tipo (text) — expense type, references expense_types.name
- monto_ars (numeric) — amount in ARS
- monto_usd (numeric) — amount in USD
- currency (text) — original currency: 'ARS' or 'USD'
- exchange_rate_id (int FK → exchange_rates.id)
- motivo (text) — short description/memo
- expense_date (date)
- created_at (timestamptz, default now())

**exchange_rates**
- id (serial PK)
- rate (numeric) — ARS per 1 USD
- notes (text, nullable)
- created_at (timestamptz, default now())

**expense_types**
- id (serial PK)
- name (text, unique)
- description (text, nullable)
- active (boolean, default true)
- created_at (timestamptz, default now())

**budget**
- id (serial PK)
- tipo (text, unique) — expense type
- amount_usd (numeric) — monthly budget in USD
- updated_at (timestamptz, default now())

**monthly_snapshots**
- id (serial PK)
- year_month (text) — e.g. '2026-03'
- tipo (text)
- total_ars (numeric)
- total_usd (numeric)
- transaction_count (int)
- total_original_ars (numeric)
- total_original_usd (numeric)
- budget_usd (numeric, nullable) — frozen budget for that tipo at month close
- created_at (timestamptz, default now())

### Views

**budget_status** — budget per type with current month spent, remaining, and percentage used (CURRENT MONTH ONLY)
Columns: tipo, budget_usd, spent_usd, remaining_usd, percentage_used

**current_month_summary** — current month expenses aggregated by type (CURRENT MONTH ONLY)
Columns: tipo, total_ars, total_usd, total_gastado_en_ars, total_gastado_en_usd, transaction_count
NOTE: These columns (total_gastado_en_ars, etc.) ONLY exist on this view. When querying the expenses table directly, use SUM(monto_ars) and SUM(monto_usd) instead.

### Notes
- All monetary amounts use numeric type for precision.
- exchange_rates.rate is ARS per 1 USD.
- budget_status and current_month_summary are views that ONLY contain current month data. NEVER use them for past months.
- The budget table stores CURRENT budget only. It has no history — do NOT join it for past month queries.
- For past months, prefer monthly_snapshots — it has spending totals AND the frozen budget_usd for each tipo.
- monthly_snapshots stores pre-aggregated data per year_month + tipo. Use it for all past month queries.
- If monthly_snapshots returns no rows for a past month (snapshot not yet generated), fall back to querying the expenses table directly with date filters + LEFT JOIN budget.
- Today's date can be obtained with CURRENT_DATE.
- For date filtering, expense_date is a date column (no time component).

### Common past-month query patterns
- "cuánto gasté el mes pasado": SELECT tipo, total_usd, budget_usd FROM monthly_snapshots WHERE year_month = to_char(CURRENT_DATE - INTERVAL '1 month', 'YYYY-MM')
- "cuánto gasté en febrero": SELECT tipo, total_usd, budget_usd FROM monthly_snapshots WHERE year_month = '2026-02'
- Total spent last month: SELECT SUM(total_usd) FROM monthly_snapshots WHERE year_month = to_char(CURRENT_DATE - INTERVAL '1 month', 'YYYY-MM')
"""
