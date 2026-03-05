"""DeleteExpenseTool — delete a recent expense."""

import json
import logging

from bot.agent.prompts import IDENTIFY_EXPENSE_PROMPT
from bot.db.queries import DELETE_EXPENSE, GET_LAST_N_EXPENSES
from bot.tools.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)


class DeleteExpenseTool(BaseTool):
    name = "delete_expense"
    description = "Delete a recent expense"

    async def execute(self, data: dict, context: ToolContext) -> str:
        description = data.get("description", "")

        # Fetch recent expenses
        async with context.db_pool.acquire() as conn:
            rows = await conn.fetch(GET_LAST_N_EXPENSES, 10)

        if not rows:
            return "No hay gastos recientes para eliminar."

        # Build expense list for LLM
        expense_list = []
        valid_ids = set()
        for row in rows:
            valid_ids.add(row["id"])
            expense_list.append(
                f"ID {row['id']}: ${row['monto_ars']:,.0f} ARS / ${row['monto_usd']:.2f} USD "
                f"en {row['tipo']} — \"{row['motivo']}\" ({row['expense_date']})"
            )

        expenses_str = "\n".join(expense_list)
        user_msg = f"El usuario quiere eliminar: {description}\n\nGastos recientes:\n{expenses_str}"

        llm_raw = await context.llm_call(
            system_prompt=IDENTIFY_EXPENSE_PROMPT,
            user_message=user_msg,
            purpose="identify_expense",
            request_id=context.request_id,
            api_key=context.api_key,
        )

        try:
            result = json.loads(llm_raw)
            expense_id = int(result["expense_id"])
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            logger.warning("delete_expense.identify_failed | raw=%s", llm_raw[:200])
            return "No pude identificar qué gasto eliminar. Intentá ser más específico."

        if expense_id not in valid_ids:
            return "No pude identificar qué gasto eliminar. Intentá ser más específico."

        # Delete
        async with context.db_pool.acquire() as conn:
            deleted = await conn.fetchrow(DELETE_EXPENSE, expense_id)

        if not deleted:
            return "Ese gasto ya no existe. Puede que ya se haya eliminado."

        return (
            f"Eliminado: ${deleted['monto_ars']:,.0f} ARS en "
            f"{deleted['tipo']} — \"{deleted['motivo']}\""
        )
