"""LogExpenseTool — record an expense to the database."""

import json
import logging
from datetime import date, timedelta

from bot.agent.prompts import CATEGORIZE_EXPENSE_PROMPT
from bot.context.memory import load_memory_file
from bot.db.queries import GET_ACTIVE_EXPENSE_TYPES, INSERT_EXPENSE
from bot.tools.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)


def _parse_date(raw: str) -> date:
    """Parse a date string: 'hoy', 'ayer', or ISO format."""
    lower = raw.strip().lower()
    if lower in ("hoy", "today", ""):
        return date.today()
    if lower in ("ayer", "yesterday"):
        return date.today() - timedelta(days=1)
    return date.fromisoformat(lower)


class LogExpenseTool(BaseTool):
    name = "log_expense"
    description = "Record an expense"

    async def execute(self, data: dict, context: ToolContext) -> str:
        amount = data.get("amount")
        if amount is None:
            return "Falta el monto del gasto."

        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return "El monto no es válido."

        currency = data.get("currency", "ARS").upper()
        description = data.get("description", "")
        raw_date = data.get("date", "hoy")

        try:
            expense_date = _parse_date(raw_date)
        except (ValueError, TypeError):
            return f"No pude interpretar la fecha: {raw_date}"

        # Fetch active expense types
        async with context.db_pool.acquire() as conn:
            rows = await conn.fetch(GET_ACTIVE_EXPENSE_TYPES)
        expense_types = [row["name"] for row in rows]

        if not expense_types:
            return "No hay tipos de gasto configurados."

        # LLM categorization
        types_str = ", ".join(expense_types)
        user_msg = f"Descripción: {description}\nMonto: {amount} {currency}\nTipos disponibles: {types_str}"

        behaviors = load_memory_file("spending_behaviors.md")
        behaviors_block = (
            f"\nSpending behaviors (apply these rules when categorizing):\n{behaviors}\n"
            if behaviors
            else ""
        )
        system_prompt = CATEGORIZE_EXPENSE_PROMPT.format(
            spending_behaviors=behaviors_block,
        )

        llm_raw = await context.llm_call(
            system_prompt=system_prompt,
            user_message=user_msg,
            purpose="categorize_expense",
            request_id=context.request_id,
            api_key=context.api_key,
        )

        try:
            categorization = json.loads(llm_raw)
            tipo = categorization["tipo"]
            motivo = categorization["motivo"]
        except (json.JSONDecodeError, KeyError):
            logger.warning("log_expense.categorization_failed | raw=%s", llm_raw[:200])
            return "No pude categorizar el gasto. Intentá de nuevo."

        if tipo not in expense_types:
            return f"El tipo '{tipo}' no es válido. Tipos disponibles: {types_str}"

        # Insert expense
        try:
            async with context.db_pool.acquire() as conn:
                row = await conn.fetchrow(
                    INSERT_EXPENSE, tipo, amount, currency, motivo, expense_date
                )
        except Exception as exc:
            if "No hay tipo de cambio registrado" in str(exc):
                return "No hay tipo de cambio registrado. Primero cargá el tipo de cambio con, por ejemplo: 'tipo de cambio 1450'."
            raise

        monto_ars = row["monto_ars_final"]
        monto_usd = row["monto_usd_final"]
        date_str = expense_date.strftime("%d/%m/%Y")

        return (
            f'Anotado: ${monto_ars:,.0f} ARS (${monto_usd:.2f} USD) '
            f'en {tipo} — "{motivo}" ({date_str})'
        )
