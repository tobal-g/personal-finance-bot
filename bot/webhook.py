"""aiohttp webhook server and health endpoint."""

import asyncio
import json
import logging
import secrets
import time

import aiohttp as aiohttp_lib
import openai
from aiohttp import web

from bot.agent.clarifier import generate_clarification
from bot.agent.receipt import extract_receipt
from bot.agent.router import TaskResult, route_message
from bot.context.manager import build_context
from bot.context.store import ConversationStore, Turn
from bot.integrations.telegram import send_message
from bot.tools import ToolRegistry
from bot.utils.logging_safety import redact_sensitive

logger = logging.getLogger(__name__)

# Module-level singleton initialized in create_app
_tool_registry = ToolRegistry()

# --- User-facing error messages (Argentine Spanish, transparent about internals) ---

_ERR_ROUTER_MALFORMED = (
    "No pude procesar tu mensaje. El router no pudo armar un JSON válido para "
    "asociarlo a una tarea. Probá reformulándolo con más detalle, por ejemplo: "
    "'5000 cafe' o 'cuánto gasté en marzo'."
)

_ERR_UNKNOWN_TASK = (
    "No entendí qué querés hacer. No pude matchear tu pedido con ninguna de las "
    "tareas que tengo registradas. Probá siendo más específico, por ejemplo: "
    "anotar gastos ('5000 uber'), eliminarlos ('borrá el último cafe'), "
    "consultar ('cuánto gasté este mes'), registrar tipo de cambio ('tc 1450'), "
    "o modificar presupuesto ('presupuesto cafe 75 usd')."
)

_ERR_LLM_TIMEOUT = (
    "El servicio de IA no respondió. Intenté 3 veces pero se agotó el tiempo "
    "de espera en todas. Esperá unos segundos y probá de nuevo."
)

_ERR_LLM_AUTH = (
    "No me pude autenticar con el servicio de IA — la API key parece inválida "
    "o expirada. Avisale al admin para que la revise."
)

_ERR_DB_CONNECTION = (
    "No me pude conectar a la base de datos — el pool de conexiones no respondió. "
    "Si el problema persiste, avisale al admin."
)

_ERR_TOOL_GENERIC = (
    "Algo salió mal ejecutando la tarea '{tool_name}'. "
    "Probá de nuevo o reformulá el mensaje."
)

_ERR_RECEIPT_DOWNLOAD = (
    "No pude descargar la foto del ticket. "
    "Probá mandándola de nuevo o sacá una foto con mejor iluminación."
)

_ERR_RECEIPT_NOT_FOUND = (
    "No pude identificar un ticket o factura en la foto. "
    "Asegurate de que se vea bien el total y probá de nuevo."
)


def create_app(config, db_pool) -> web.Application:
    """Create the aiohttp application with routes."""
    app = web.Application()
    app["config"] = config
    app["db_pool"] = db_pool
    app["conversation_store"] = ConversationStore(
        max_user_chars=config.CONTEXT_MAX_USER_CHARS,
    )
    app["tool_registry"] = _tool_registry

    # Auto-discover tools
    _tool_registry.discover()

    app.router.add_post("/webhook", handle_webhook)
    app.router.add_get("/health", handle_health)
    return app


async def handle_webhook(request: web.Request) -> web.Response:
    """Receive Telegram webhook updates."""
    config = request.app["config"]

    # Validate secret token
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != config.WEBHOOK_SECRET_TOKEN:
        logger.warning("webhook.invalid_secret")
        return web.Response(status=403, text="Forbidden")

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.Response(status=400, text="Bad Request")

    # Extract message data
    message = body.get("message")
    if not message:
        return web.Response(status=200, text="OK")

    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")
    text = message.get("text", "")
    photo = message.get("photo")  # list of PhotoSize or None
    caption = message.get("caption", "")

    # Accept text messages OR photo messages
    has_content = bool(text) or bool(photo)
    if not has_content or chat_id is None or user_id is None:
        return web.Response(status=200, text="OK")

    content_preview = text[:80] if text else f"[photo file_id={photo[-1]['file_id'][:20]}]"
    logger.info(
        "telegram.incoming | user_id=%s chat_id=%s content=%r",
        user_id,
        chat_id,
        content_preview,
    )

    # Check allowlists
    if chat_id != config.ALLOWED_CHAT_ID:
        logger.debug("webhook.chat_not_allowed | chat_id=%s", chat_id)
        return web.Response(status=200, text="OK")

    if user_id not in config.ALLOWED_USER_IDS:
        logger.debug("webhook.user_not_allowed | user_id=%s", user_id)
        return web.Response(status=200, text="OK")

    # Return 200 immediately, process async
    asyncio.create_task(
        _process_message(
            config,
            request.app["db_pool"],
            request.app["conversation_store"],
            request.app["tool_registry"],
            text,
            chat_id,
            photo=photo,
            caption=caption,
        )
    )
    return web.Response(status=200, text="OK")


async def _process_message(
    config,
    db_pool,
    store: ConversationStore,
    registry: ToolRegistry,
    text: str,
    chat_id: int,
    *,
    photo: list[dict] | None = None,
    caption: str | None = None,
) -> None:
    """Process a message through the full pipeline."""
    request_id = f"req_{secrets.token_hex(2)}"
    start_time = time.monotonic()

    try:
        # --- Receipt photo preprocessing ---
        if photo and not text:
            await _process_receipt(
                config, db_pool, store, registry,
                photo, caption, chat_id, request_id, start_time,
            )
            return

        # Build context from conversation history BEFORE storing the current turn,
        # so context only contains prior turns.
        context = build_context(
            chat_id,
            store,
            max_memory_chars=config.CONTEXT_MAX_MEMORY_CHARS,
        )

        # Store the user turn for future follow-ups.
        store.add_turn(chat_id, Turn(role="user", text=text))

        # Fetch expense types from DB
        expense_types = await _fetch_expense_types(db_pool)

        # Route the message — may raise LLM errors
        tasks = await _route_with_error_handling(
            text, context, expense_types, request_id, config, chat_id, store
        )
        if tasks is None:
            # Error already handled and messaged to user
            return

        # Process each task with partial success support
        responses: list[str] = []
        tasks_ok = 0
        tasks_err = 0

        for i, task_result in enumerate(tasks, 1):
            task_id = f"{request_id}/{i}"

            if task_result.requires_clarification:
                reason = task_result.clarification_reason or "información incompleta"
                clarification = await generate_clarification(
                    text, reason, request_id, api_key=config.OPENAI_API_KEY
                )
                responses.append(clarification)
                tasks_ok += 1
                store.add_turn(
                    chat_id,
                    Turn(
                        role="bot",
                        text=clarification,
                        task_result={
                            "task": task_result.task,
                            "requires_clarification": True,
                            "clarification_reason": reason,
                        },
                    ),
                )
                continue

            # Look up the tool
            tool = registry.get_tool(task_result.task)
            if tool is None:
                responses.append(_ERR_UNKNOWN_TASK)
                tasks_err += 1
                logger.warning(
                    "tool.unknown | task=%s tool=%s", task_id, task_result.task
                )
                continue

            # Execute the tool with error isolation
            result_text = await _execute_tool_safe(
                tool, task_result, task_id, config, db_pool, chat_id, request_id
            )
            responses.append(result_text)

            if result_text.startswith("Algo salió mal") or result_text == _ERR_LLM_TIMEOUT or result_text == _ERR_LLM_AUTH or result_text == _ERR_DB_CONNECTION:
                tasks_err += 1
            else:
                tasks_ok += 1

            store.add_turn(
                chat_id,
                Turn(
                    role="bot",
                    text=result_text,
                    task_result={"task": task_result.task},
                ),
            )

        # Send combined response
        if responses:
            combined = "\n\n".join(responses)
            await send_message(chat_id, combined, config.TELEGRAM_BOT_TOKEN)

        elapsed = time.monotonic() - start_time
        total = tasks_ok + tasks_err
        if tasks_err == 0:
            log_fn = logger.info
            status = "success"
        elif tasks_ok > 0:
            log_fn = logger.warning
            status = "partial"
        else:
            log_fn = logger.error
            status = "failure"

        log_fn(
            "request.complete | req=%s total_time=%.1fs tasks=%d tasks_ok=%d tasks_err=%d status=%s",
            request_id,
            elapsed,
            total,
            tasks_ok,
            tasks_err,
            status,
        )

    except Exception:
        elapsed = time.monotonic() - start_time
        logger.error(
            "webhook.process_error | req=%s chat_id=%s total_time=%.1fs",
            request_id,
            chat_id,
            elapsed,
            exc_info=True,
        )
        try:
            await send_message(
                chat_id,
                _ERR_ROUTER_MALFORMED,
                config.TELEGRAM_BOT_TOKEN,
            )
        except Exception:
            logger.critical(
                "webhook.error_response_failed | req=%s chat_id=%s",
                request_id,
                chat_id,
                exc_info=True,
            )


async def _process_receipt(
    config, db_pool, store, registry,
    photo, caption, chat_id, request_id, start_time,
) -> None:
    """Process a receipt photo: extract data via vision LLM, then log expense."""
    file_id = photo[-1]["file_id"]

    logger.info(
        "receipt.start | req=%s file_id=%s caption=%r",
        request_id,
        file_id,
        (caption or "")[:80],
    )

    try:
        result = await extract_receipt(
            file_id,
            caption,
            request_id=request_id,
            bot_token=config.TELEGRAM_BOT_TOKEN,
            api_key=config.OPENAI_API_KEY,
        )
    except openai.AuthenticationError:
        elapsed = time.monotonic() - start_time
        logger.error(
            "request.complete | req=%s total_time=%.1fs status=failure reason=llm_auth",
            request_id,
            elapsed,
        )
        await _send_error(chat_id, _ERR_LLM_AUTH, config, store)
        return
    except RuntimeError:
        elapsed = time.monotonic() - start_time
        logger.error(
            "request.complete | req=%s total_time=%.1fs status=failure reason=llm_timeout",
            request_id,
            elapsed,
        )
        await _send_error(chat_id, _ERR_LLM_TIMEOUT, config, store)
        return

    if result is None:
        elapsed = time.monotonic() - start_time
        logger.warning(
            "request.complete | req=%s total_time=%.1fs status=failure reason=receipt_download_failed",
            request_id,
            elapsed,
        )
        await _send_error(chat_id, _ERR_RECEIPT_DOWNLOAD, config, store)
        return

    if not result.is_receipt:
        elapsed = time.monotonic() - start_time
        logger.info(
            "request.complete | req=%s total_time=%.1fs status=failure reason=not_a_receipt",
            request_id,
            elapsed,
        )
        await _send_error(chat_id, _ERR_RECEIPT_NOT_FOUND, config, store)
        return

    # Store synthetic user turn for conversation context
    summary = (
        f"[Foto de ticket: ${result.amount:,.0f} {result.currency} "
        f"{result.description}]"
    )
    store.add_turn(chat_id, Turn(role="user", text=summary))

    # Execute log_expense directly, bypassing the router
    tool = registry.get_tool("log_expense")
    if tool is None:
        await _send_error(chat_id, _ERR_UNKNOWN_TASK, config, store)
        return

    task_data = {
        "amount": result.amount,
        "currency": result.currency,
        "description": result.description,
        "date": result.date,
    }
    task_result = TaskResult(task="log_expense", data=task_data)
    task_id = f"{request_id}/1"

    result_text = await _execute_tool_safe(
        tool, task_result, task_id, config, db_pool, chat_id, request_id,
    )

    store.add_turn(
        chat_id,
        Turn(
            role="bot",
            text=result_text,
            task_result={"task": "log_expense", "source": "receipt_photo"},
        ),
    )
    await send_message(chat_id, result_text, config.TELEGRAM_BOT_TOKEN)

    elapsed = time.monotonic() - start_time
    logger.info(
        "request.complete | req=%s total_time=%.1fs tasks=1 tasks_ok=1 "
        "tasks_err=0 status=success source=receipt_photo",
        request_id,
        elapsed,
    )


async def _route_with_error_handling(
    text, context, expense_types, request_id, config, chat_id, store
):
    """Route message, catching LLM-specific errors.

    Returns list[TaskResult] on success, None if error was handled.
    """
    try:
        tasks = await route_message(
            text, context, expense_types, request_id, api_key=config.OPENAI_API_KEY
        )
    except openai.AuthenticationError:
        await _send_error(chat_id, _ERR_LLM_AUTH, config, store)
        return None
    except RuntimeError:
        await _send_error(chat_id, _ERR_LLM_TIMEOUT, config, store)
        return None
    except OSError:
        await _send_error(chat_id, _ERR_DB_CONNECTION, config, store)
        return None

    if not tasks:
        await _send_error(chat_id, _ERR_ROUTER_MALFORMED, config, store)
        return None

    return tasks


async def _execute_tool_safe(
    tool, task_result, task_id, config, db_pool, chat_id, request_id
):
    """Execute a tool with error isolation — never raises."""
    from bot.integrations.llm import call_llm
    from bot.tools.base import ToolContext

    tool_context = ToolContext(
        db_pool=db_pool,
        chat_id=chat_id,
        request_id=request_id,
        task_id=task_id,
        api_key=config.OPENAI_API_KEY,
        llm_call=call_llm,
        query_format_max_rows=config.QUERY_FORMAT_MAX_ROWS,
        query_format_max_chars=config.QUERY_FORMAT_MAX_CHARS,
    )
    logger.info("tool.start | task=%s tool=%s", task_id, task_result.task)

    try:
        result_text = await tool.execute(task_result.data, tool_context)
        logger.info("tool.complete | task=%s tool=%s status=success", task_id, task_result.task)
        return result_text

    except openai.AuthenticationError:
        logger.error("tool.error | task=%s tool=%s error=llm_auth", task_id, task_result.task)
        return _ERR_LLM_AUTH

    except RuntimeError as exc:
        if "LLM call failed" in str(exc):
            logger.error("tool.error | task=%s tool=%s error=llm_timeout", task_id, task_result.task)
            return _ERR_LLM_TIMEOUT
        logger.error(
            "tool.error | task=%s tool=%s error=%s",
            task_id, task_result.task, str(exc)[:100],
            exc_info=True,
        )
        return _ERR_TOOL_GENERIC.format(tool_name=task_result.task)

    except OSError as exc:
        logger.error("tool.error | task=%s tool=%s error=db_connection", task_id, task_result.task)
        return _ERR_DB_CONNECTION

    except Exception as exc:
        logger.error(
            "tool.error | task=%s tool=%s error=%s",
            task_id, task_result.task, str(exc)[:100],
            exc_info=True,
        )
        return _ERR_TOOL_GENERIC.format(tool_name=task_result.task)


async def _send_error(chat_id, message, config, store):
    """Send an error message and store the turn."""
    await send_message(chat_id, message, config.TELEGRAM_BOT_TOKEN)
    store.add_turn(chat_id, Turn(role="bot", text=message))


async def _fetch_expense_types(db_pool) -> list[str]:
    """Fetch active expense type names from the database."""
    if db_pool is None:
        return []
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT name FROM expense_types WHERE active = true ORDER BY name"
            )
            return [row["name"] for row in rows]
    except Exception:
        logger.warning("webhook.expense_types_fetch_failed", exc_info=True)
        return []


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    from bot.main import VERSION

    config = request.app["config"]
    health_header = request.headers.get("X-Health-Token", "")
    has_health_token = bool(config.HEALTHCHECK_TOKEN)
    is_authorized = has_health_token and secrets.compare_digest(
        health_header,
        config.HEALTHCHECK_TOKEN,
    )

    # Keep public health checks minimal by default.
    if not is_authorized:
        return web.json_response({"status": "ok", "version": VERSION})

    db_pool = request.app["db_pool"]
    db_ok = False

    if db_pool is not None:
        try:
            async with db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_ok = True
        except Exception:
            logger.warning("health.db_check_failed", exc_info=True)

    # Fetch webhook info from Telegram (non-sensitive fields only)
    webhook_info = None
    try:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getWebhookInfo"
        async with aiohttp_lib.ClientSession() as session:
            async with session.get(url) as resp:
                body = await resp.json()
                if body.get("ok"):
                    result = body["result"]
                    webhook_info = {
                        "has_webhook": bool(result.get("url")),
                        "pending_update_count": result.get("pending_update_count", 0),
                    }
    except Exception as exc:
        logger.warning(
            "health.webhook_info_failed | error=%s",
            redact_sensitive(exc)[:200],
        )

    status = {"status": "ok", "db": db_ok, "version": VERSION}
    if webhook_info is not None:
        status["webhook"] = webhook_info
    return web.json_response(status)
