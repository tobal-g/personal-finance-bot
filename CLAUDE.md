# CLAUDE.md

## Project

Telegram expenses bot — Python 3.12, async architecture (aiohttp + asyncpg + OpenAI). Argentine Spanish ("vos" form), 2-user group chat. Migrated from n8n.

## Commands

```bash
# Run the bot
python -m bot.main

# Run tests (162 tests, all passing)
.venv/bin/pytest tests/ -v

# Run a single test file
.venv/bin/pytest tests/test_log_expense.py -v

# Docker
docker build -t finance-bot .
docker run --env-file .env -p 8080:8080 finance-bot
```

## Architecture

**Pipeline:** `webhook.py` → validate → build context (prior turns only) → store current turn → fetch expense types → route (LLM) → clarify or execute tool → send response

**Receipt photo pipeline:** `webhook.py` (detect photo) → `telegram.py` (download via getFile API) → `llm.py` (vision extraction) → `receipt.py` (orchestrate) → bypass router → `log_expense` tool directly

**Key files:**
- `bot/webhook.py` — Main pipeline, error handling, health endpoint
- `bot/agent/router.py` — LLM classifies messages into TaskResult(s)
- `bot/agent/prompts.py` — All LLM system prompts (centralized, template strings)
- `bot/agent/clarifier.py` — Generates clarification messages
- `bot/tools/__init__.py` — ToolRegistry with auto-discovery from `bot/tools/`
- `bot/tools/base.py` — `BaseTool` ABC + `ToolContext` dataclass
- `bot/agent/receipt.py` — Receipt photo extraction orchestrator (download + vision LLM)
- `bot/integrations/llm.py` — OpenAI wrapper, 3x retry, JSON mode, vision support, `gpt-5.2`
- `bot/context/store.py` — In-memory per-chat history (TTL 600s, max 6 turns, user turns truncated at `max_user_chars`)
- `bot/db/queries.py` — All SQL constants + `DB_SCHEMA_CONTEXT`

**Tools:** `log_expense`, `delete_expense`, `log_exchange_rate`, `query` (aliases: query_expenses/budget/exchange/general), `modify_budget`

**Request ID format:** `req_{hex(2)}` (e.g. `req_a3f8`), task IDs: `req_a3f8/1`

## Database

Neon PostgreSQL. Tables: `expenses`, `exchange_rates`, `expense_types`, `budget`, `monthly_snapshots`. Views: `budget_status`, `current_month_summary` (current month only — for past months query `expenses` directly or `monthly_snapshots`).

## Testing patterns

- `pytest-asyncio` with `asyncio_mode = "auto"` in `pyproject.toml`
- `tests/conftest.py`: `make_env()` helper, `valid_env` and `config` fixtures
- Mock DB: `_FakePool` / `_FakeConn` classes for asyncpg
- Mock LLM: `ToolContext.llm_call = AsyncMock(return_value=json_str)`
- `pytest-aiohttp` for webhook endpoint tests
- `aioresponses` for HTTP mocking

## Error handling

- `bot/webhook.py` has error constants: `_ERR_ROUTER_MALFORMED`, `_ERR_UNKNOWN_TASK`, `_ERR_LLM_TIMEOUT`, `_ERR_LLM_AUTH`, `_ERR_DB_CONNECTION`, `_ERR_TOOL_GENERIC`, `_ERR_RECEIPT_DOWNLOAD`, `_ERR_RECEIPT_NOT_FOUND`
- Multi-task partial success: each tool executes in `_execute_tool_safe()`, failures don't block other tasks
- All error messages are in Argentine Spanish and transparent about internals
- `request.complete` log: `total_time`, `tasks_ok`, `tasks_err`, `status` (success/partial/failure)

## Style conventions

- All user-facing text in Argentine Spanish ("vos" form)
- Structured logging: `category.action | key=value` format
- SQL constants in `bot/db/queries.py`, never inline
- New tools go in `bot/tools/`, subclass `BaseTool`, auto-discovered by registry
- Prompts centralized in `bot/agent/prompts.py` as template strings

## Config

All env vars validated at startup in `bot/config.py`. Required: `TELEGRAM_BOT_TOKEN`, `WEBHOOK_URL`, `WEBHOOK_SECRET_TOKEN`, `DATABASE_URL`, `OPENAI_API_KEY`, `ALLOWED_CHAT_ID`, `ALLOWED_USER_IDS`, `HEALTHCHECK_TOKEN`. Optional: `LOG_LEVEL` (INFO), `PORT` (8080), `CONTEXT_MAX_USER_CHARS` (400), `CONTEXT_MAX_MEMORY_CHARS` (4000), `QUERY_FORMAT_MAX_ROWS` (50), `QUERY_FORMAT_MAX_CHARS` (8000).

## Token/context caps

- **Router de-duplication**: Context is built from prior turns only; current message appended separately as `CURRENT MESSAGE:`. First message (no history) sends raw message only.
- **User turn truncation**: `ConversationStore` truncates user turns at `max_user_chars` (default 400) on storage.
- **Bot turn truncation**: `build_context()` truncates bot responses at 200 chars in the context string.
- **Memory cap**: `load_memory()` caps total memory at `MAX_MEMORY_CHARS` (default 4000).
- **Query formatter caps**: `QueryTool` limits formatter input to `_MAX_FORMAT_ROWS` (50) and `_MAX_FORMAT_CHARS` (8000). Metadata header tells the LLM about truncation.

## Milestones

M1-M6 complete. M7 (Dockerfile + Railway deployment) pending. See `PLAN.md` for full roadmap.
