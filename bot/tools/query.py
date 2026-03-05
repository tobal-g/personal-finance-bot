"""QueryTool — answer natural-language questions via SQL generation."""

import json
import logging
import re

import asyncpg

from bot.agent.prompts import QUERY_FORMATTER_PROMPT, QUERY_SQL_PROMPT
from bot.db.queries import DB_SCHEMA_CONTEXT, GET_ACTIVE_EXPENSE_TYPES
from bot.tools.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)

_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

_MAX_RESPONSE_LEN = 4000
_MAX_FORMAT_ROWS = 50
_MAX_FORMAT_CHARS = 8000

_ERR_INVALID_SQL = (
    "No pude armar una consulta válida para lo que preguntaste — el SQL que generé "
    "no pasó la validación de seguridad. Probá reformulándola con más detalle, "
    "por ejemplo: 'cuánto gasté en cafe en marzo'."
)
_ERR_TIMEOUT = (
    "La consulta tardó más de 5 segundos y fue cancelada. "
    "Probá con algo más acotado, por ejemplo un solo mes o una categoría específica."
)
_ERR_DB = (
    "La consulta se armó pero falló al ejecutarse contra la base de datos. "
    "Probá reformulando la pregunta o siendo más específico con fechas y categorías."
)
_ERR_NO_RESULTS = "No encontré resultados para tu consulta."
_ERR_MISSING_QUESTION = "No recibí una pregunta para consultar."


def validate_sql(sql: str) -> bool:
    """Return True if the SQL is a safe SELECT query."""
    stripped = sql.strip()
    if not stripped.upper().startswith("SELECT"):
        return False
    if ";" in stripped:
        return False
    if _FORBIDDEN_SQL.search(stripped):
        return False
    return True


class QueryTool(BaseTool):
    name = "query_expenses"
    aliases = ["query_budget", "query_exchange", "query_general"]
    description = "Answer questions about expenses, budget, and exchange rates"

    async def execute(self, data: dict, context: ToolContext) -> str:
        question = data.get("question", "").strip()
        if not question:
            return _ERR_MISSING_QUESTION

        # Fetch expense types for context
        async with context.db_pool.acquire() as conn:
            rows = await conn.fetch(GET_ACTIVE_EXPENSE_TYPES)
        expense_types = [row["name"] for row in rows]
        types_str = ", ".join(expense_types) if expense_types else "(ninguno)"

        # Generate SQL via LLM
        user_msg = (
            f"{DB_SCHEMA_CONTEXT}\n\n"
            f"## Active expense types\n{types_str}\n\n"
            f"## User question\n{question}"
        )

        llm_raw = await context.llm_call(
            system_prompt=QUERY_SQL_PROMPT,
            user_message=user_msg,
            purpose="query_sql",
            request_id=context.request_id,
            api_key=context.api_key,
        )

        try:
            parsed = json.loads(llm_raw)
            sql = parsed["sql"]
            explanation = parsed.get("explanation", "")
        except (json.JSONDecodeError, KeyError):
            logger.warning("query.sql_parse_failed | raw=%s", llm_raw[:200])
            return _ERR_INVALID_SQL

        if not validate_sql(sql):
            logger.warning("query.sql_validation_failed | sql=%s", sql[:200])
            return _ERR_INVALID_SQL

        # Execute query with timeout
        try:
            async with context.db_pool.acquire() as conn:
                await conn.execute("SET LOCAL statement_timeout = '5s'")
                rows = await conn.fetch(sql)
        except asyncpg.QueryCanceledError:
            return _ERR_TIMEOUT
        except asyncpg.PostgresError as exc:
            logger.warning("query.db_error | error=%s", exc)
            return _ERR_DB

        if not rows:
            return _ERR_NO_RESULTS

        # Format results via LLM (cap payload size to control token usage)
        max_rows = context.query_format_max_rows or _MAX_FORMAT_ROWS
        max_chars = context.query_format_max_chars or _MAX_FORMAT_CHARS

        rows_for_format = rows[:max_rows]
        result_lines: list[str] = []
        result_chars = 0
        for row in rows_for_format:
            line = str(dict(row))
            line_len = len(line) + 1  # include newline separator
            if result_lines and (result_chars + line_len) > max_chars:
                break
            if not result_lines and line_len > max_chars:
                # Keep at least one row, truncated to the cap.
                line = line[: max_chars - 1]
                line_len = len(line) + 1
            result_lines.append(line)
            result_chars += line_len

        results_str = "\n".join(result_lines)
        fmt_msg = (
            f"## User question\n{question}\n\n"
            f"## Query explanation\n{explanation}\n\n"
            f"## Results window\n"
            f"included_rows={len(result_lines)} total_rows={len(rows)}\n"
            f"included_chars={len(results_str)} char_cap={max_chars}\n\n"
            f"## Results\n{results_str}"
        )

        response = await context.llm_call(
            system_prompt=QUERY_FORMATTER_PROMPT,
            user_message=fmt_msg,
            purpose="query_format",
            request_id=context.request_id,
            api_key=context.api_key,
            json_mode=False,
        )

        if len(response) > _MAX_RESPONSE_LEN:
            response = response[:_MAX_RESPONSE_LEN]

        return response
