"""LogExchangeRateTool — record a new exchange rate."""

import logging

from bot.db.queries import INSERT_EXCHANGE_RATE
from bot.tools.base import BaseTool, ToolContext

logger = logging.getLogger(__name__)


class LogExchangeRateTool(BaseTool):
    name = "log_exchange_rate"
    description = "Record an exchange rate"

    async def execute(self, data: dict, context: ToolContext) -> str:
        rate = data.get("rate")
        usd_amount = data.get("usd_amount")
        ars_amount = data.get("ars_amount")

        if rate is not None:
            try:
                rate = float(rate)
            except (ValueError, TypeError):
                return "El tipo de cambio no es válido."
        elif usd_amount is not None and ars_amount is not None:
            try:
                usd_amount = float(usd_amount)
                ars_amount = float(ars_amount)
            except (ValueError, TypeError):
                return "Los montos no son válidos."
            if usd_amount <= 0:
                return "El monto en USD debe ser mayor a 0."
            rate = ars_amount / usd_amount
        else:
            return "Falta el tipo de cambio. Podés mandarlo directamente (ej: 'tc 1450') o con montos (ej: 'pagué 100 USD = 145000 ARS')."

        if not 100 <= rate <= 100_000:
            return f"El tipo de cambio {rate:,.0f} parece fuera de rango (esperado entre 100 y 100.000)."

        async with context.db_pool.acquire() as conn:
            row = await conn.fetchrow(INSERT_EXCHANGE_RATE, rate)

        return f"Tipo de cambio registrado: 1 USD = {row['rate']:,.0f} ARS"
