# Finance Bot

Telegram bot for personal finance management. Communicates in Argentine Spanish ("vos" form) in a group chat restricted to 2 users. Migrated from a ~100-node n8n workflow to a custom Python 3.12 application.

## What it does

- **Log expenses** in ARS or USD with automatic categorization
- **Delete expenses** by describing which one to remove
- **Record exchange rates** (ARS/USD) directly or calculated from amounts
- **Query anything** — natural-language questions answered via SQL generation ("cuanto gaste este mes?")
- **Manage budgets** — update, add, or remove budget categories
- **Receipt photos** — snap a paper receipt, send the photo, expense is logged automatically (vision LLM extracts store, amount, currency)
- **Multi-task** — handle multiple actions in a single message ("5000 uber, cuanto gaste hoy?")
- **Conversation context** — resolves follow-ups across messages

## Architecture

```
Telegram → aiohttp webhook → Router (LLM) → Tool execution → Telegram response
                  ↓                ↓
           Photo? → Vision LLM → log_expense directly (bypasses router)
                                   ↓
                          ConversationStore (in-memory, 10min TTL)
                                   ↓
                          Neon PostgreSQL (asyncpg)
```

The router classifies each message into one or more tasks via an LLM call. It receives prior conversation context plus the current message explicitly. Each task maps to a tool that executes against the database and returns a Spanish-language response. Multiple tasks in a single message are processed independently with partial success support.

### Key components

| Component | File | Purpose |
|-----------|------|---------|
| Webhook server | `bot/webhook.py` | Validates, routes, executes, responds |
| Router | `bot/agent/router.py` | LLM-based message → task classification |
| Clarifier | `bot/agent/clarifier.py` | Generates clarification prompts |
| Receipt extractor | `bot/agent/receipt.py` | Downloads photo + vision LLM extraction |
| Prompts | `bot/agent/prompts.py` | All LLM system prompts (centralized) |
| Context store | `bot/context/store.py` | Per-chat conversation history (TTL 600s, max 6 turns) |
| Context manager | `bot/context/manager.py` | Assembles history + long-term memory |
| Tool registry | `bot/tools/__init__.py` | Auto-discovers `BaseTool` subclasses |
| LLM wrapper | `bot/integrations/llm.py` | OpenAI SDK with 3x retry, JSON mode, vision support |
| DB pool | `bot/db/pool.py` | asyncpg pool lifecycle |
| SQL constants | `bot/db/queries.py` | All SQL + `DB_SCHEMA_CONTEXT` for LLM |

### Tools

| Tool | Aliases | What it does |
|------|---------|-------------|
| `LogExpenseTool` | `log_expense` | LLM categorizes → DB insert → confirmation |
| `DeleteExpenseTool` | `delete_expense` | Fetch recent → LLM identifies → DB delete |
| `LogExchangeRateTool` | `log_exchange_rate` | Validate range → DB insert |
| `QueryTool` | `query_expenses`, `query_budget`, `query_exchange`, `query_general` | LLM SQL gen → validate → execute → LLM format |
| `ModifyBudgetTool` | `modify_budget` | LLM interprets action → validate → execute |

## Setup

### Prerequisites

- Python 3.12+
- Neon PostgreSQL database (or any PostgreSQL with the required schema)
- OpenAI API key
- Telegram bot token (via @BotFather)

### Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # for tests
```

### Configure

```bash
cp .env.example .env
```

Fill required values in `.env` (optional values have defaults):

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from @BotFather |
| `WEBHOOK_URL` | Yes | Public HTTPS URL (ngrok for local dev) |
| `WEBHOOK_SECRET_TOKEN` | Yes | Random string for webhook validation |
| `DATABASE_URL` | Yes | PostgreSQL connection string with `?sslmode=require` |
| `OPENAI_API_KEY` | Yes | OpenAI API key |
| `ALLOWED_CHAT_ID` | Yes | Telegram chat ID (int) |
| `ALLOWED_USER_IDS` | Yes | Comma-separated Telegram user IDs |
| `HEALTHCHECK_TOKEN` | No | Token for detailed health endpoint (default: empty, only public minimal health response) |
| `LOG_LEVEL` | No | Default: `INFO` |
| `PORT` | No | Default: `8080` |
| `CONTEXT_MAX_USER_CHARS` | No | Max chars stored per user turn in short-term history (default: `400`) |
| `CONTEXT_MAX_MEMORY_CHARS` | No | Max total chars loaded from `memory/*.md` into router context (default: `4000`) |
| `QUERY_FORMAT_MAX_ROWS` | No | Max DB rows passed to the query formatter LLM call (default: `50`) |
| `QUERY_FORMAT_MAX_CHARS` | No | Max chars from DB rows passed to the query formatter LLM call (default: `8000`) |

### Run locally

```bash
# Start ngrok (separate terminal)
ngrok http 8080

# Set WEBHOOK_URL in .env to the ngrok HTTPS URL

# Run the bot
python -m bot.main
```

### Run tests

```bash
.venv/bin/pytest tests/ -v
```

162 tests across 18 test files. Uses `pytest-asyncio` with `asyncio_mode = "auto"`.

### Context and token controls

- Router context uses previous turns + current message (no duplication of current message).
- `CONTEXT_MAX_USER_CHARS` truncates stored user turns in short-term history.
- `CONTEXT_MAX_MEMORY_CHARS` truncates concatenated long-term memory loaded from `memory/*.md`.
- `QUERY_FORMAT_MAX_ROWS` and `QUERY_FORMAT_MAX_CHARS` window the DB result payload sent to the query formatter LLM call.
- When limits are hit, payload is truncated/windowed (the request does not fail).

## Docker

```bash
docker build -t finance-bot .
docker run --env-file .env -p 8080:8080 finance-bot
```

## Deployment (Railway)

1. Create Railway project, connect GitHub repo
2. Set all env vars in Railway dashboard
3. Deploy (auto-detects `Dockerfile`)
4. Set `WEBHOOK_URL` to Railway's public URL and redeploy
5. Health check: `GET /health` returns `{"status": "ok", "version": "1.0.0"}`

## Database schema

| Table | Purpose |
|-------|---------|
| `expenses` | Expense records (tipo, monto_ars, monto_usd, currency, motivo, expense_date) |
| `exchange_rates` | ARS/USD exchange rates |
| `expense_types` | Active expense categories |
| `budget` | Monthly budget per category (USD) |
| `monthly_snapshots` | Aggregated monthly data (cron job) |

| View | Purpose |
|------|---------|
| `budget_status` | Current month: budget vs spent per category |
| `current_month_summary` | Current month expenses by type |

## Project structure

```
bot/
├── main.py              # Entry point
├── config.py            # Env var validation
├── webhook.py           # Webhook server + pipeline
├── agent/
│   ├── router.py        # Message classification
│   ├── clarifier.py     # Clarification generation
│   ├── receipt.py       # Receipt photo extraction (vision LLM)
│   └── prompts.py       # All LLM prompts
├── context/
│   ├── store.py         # Conversation history
│   ├── manager.py       # Context assembly
│   └── memory.py        # Long-term memory loader
├── tools/
│   ├── base.py          # BaseTool ABC + ToolContext
│   ├── log_expense.py
│   ├── delete_expense.py
│   ├── log_exchange_rate.py
│   ├── query.py
│   └── modify_budget.py
├── integrations/
│   ├── telegram.py      # Send message, file download with retry
│   └── llm.py           # OpenAI wrapper with retry + vision
├── db/
│   ├── pool.py          # asyncpg pool
│   └── queries.py       # SQL constants
└── utils/
    ├── parsing.py       # JSON extraction
    └── logging_safety.py # API key redaction
```
