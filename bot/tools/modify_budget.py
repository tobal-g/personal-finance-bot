"""ModifyBudgetTool — update, add, or remove budget categories."""

import json
import logging

from bot.agent.prompts import MODIFY_BUDGET_PROMPT
from bot.db.queries import (
    DEACTIVATE_EXPENSE_TYPE,
    DELETE_BUDGET,
    GET_ACTIVE_EXPENSE_TYPES,
    GET_BUDGET,
    INSERT_BUDGET,
    INSERT_EXPENSE_TYPE,
    UPDATE_BUDGET,
)
from bot.tools.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)

VALID_ACTIONS = {"update", "add", "remove"}


class ModifyBudgetTool(BaseTool):
    name = "modify_budget"
    description = "Modify budget categories"

    async def execute(self, data: dict, context: ToolContext) -> str:
        description = data.get("description") or data.get("action_description", "")
        if not description:
            return "No entendí qué cambio querés hacer en el presupuesto."

        # Fetch current budget and active expense types
        async with context.db_pool.acquire() as conn:
            budget_rows = await conn.fetch(GET_BUDGET)
            type_rows = await conn.fetch(GET_ACTIVE_EXPENSE_TYPES)

        budget_types = {row["tipo"]: float(row["amount_usd"]) for row in budget_rows}
        expense_types = [row["name"] for row in type_rows]

        budget_str = ", ".join(
            f"{t}: ${a:.0f} USD" for t, a in budget_types.items()
        ) or "(vacío)"
        types_str = ", ".join(expense_types)

        user_msg = (
            f"Mensaje del usuario: {description}\n"
            f"Categorías de presupuesto actuales: {budget_str}\n"
            f"Tipos de gasto activos: {types_str}"
        )

        llm_raw = await context.llm_call(
            system_prompt=MODIFY_BUDGET_PROMPT,
            user_message=user_msg,
            purpose="modify_budget",
            request_id=context.request_id,
            api_key=context.api_key,
        )

        try:
            result = json.loads(llm_raw)
            action = result["action"]
            tipo = result["tipo"]
        except (json.JSONDecodeError, KeyError):
            logger.warning("modify_budget.parse_failed | raw=%s", llm_raw[:200])
            return "No pude interpretar el cambio de presupuesto. Intentá de nuevo."

        if action not in VALID_ACTIONS:
            return "No pude interpretar el cambio de presupuesto. Intentá de nuevo."

        amount_usd = result.get("amount_usd")

        if action == "update":
            if tipo not in budget_types:
                return f"No existe '{tipo}' en el presupuesto. Categorías actuales: {', '.join(budget_types.keys()) or 'ninguna'}"
            if amount_usd is None:
                return "Falta el monto para actualizar el presupuesto."
            async with context.db_pool.acquire() as conn:
                await conn.fetchrow(UPDATE_BUDGET, float(amount_usd), tipo)
            return f"Presupuesto actualizado: {tipo} ahora es ${amount_usd:.0f} USD"

        if action == "add":
            if tipo in budget_types:
                return f"'{tipo}' ya existe en el presupuesto con ${budget_types[tipo]:.0f} USD."
            if amount_usd is None:
                return "Falta el monto para agregar la categoría al presupuesto."
            async with context.db_pool.acquire() as conn:
                await conn.execute(INSERT_EXPENSE_TYPE, tipo)
                await conn.fetchrow(INSERT_BUDGET, tipo, float(amount_usd))
            return f"Categoría agregada: {tipo} con ${amount_usd:.0f} USD"

        # action == "remove"
        if tipo not in budget_types:
            return f"No existe '{tipo}' en el presupuesto."
        async with context.db_pool.acquire() as conn:
            row = await conn.fetchrow(DELETE_BUDGET, tipo)
            if row:
                await conn.execute(DEACTIVATE_EXPENSE_TYPE, tipo)
        if not row:
            return f"No se pudo eliminar '{tipo}' del presupuesto."
        return f"Categoría eliminada: {tipo}"
