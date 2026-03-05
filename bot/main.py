"""Entry point: init DB pool, start aiohttp server, manage webhook lifecycle."""

import asyncio
import logging
import signal
import sys

import aiohttp
from aiohttp import web

from bot.config import Config
from bot.db.pool import close_pool, create_pool
from bot.utils.logging_safety import redact_sensitive
from bot.webhook import create_app

logger = logging.getLogger(__name__)

VERSION = "1.0.0"

TELEGRAM_API = "https://api.telegram.org"


async def set_webhook(config: Config) -> None:
    """Register webhook with Telegram."""
    url = f"{TELEGRAM_API}/bot{config.TELEGRAM_BOT_TOKEN}/setWebhook"
    payload = {
        "url": f"{config.WEBHOOK_URL}/webhook",
        "secret_token": config.WEBHOOK_SECRET_TOKEN,
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
        "max_connections": 40,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            body = await resp.json()
            if resp.status == 200 and body.get("ok"):
                logger.info("webhook.registered | url=%s", config.WEBHOOK_URL)
            else:
                logger.error(
                    "webhook.register_failed | response=%s",
                    redact_sensitive(body),
                )
                raise RuntimeError(f"Failed to set webhook: {body}")


async def delete_webhook(config: Config) -> None:
    """Unregister webhook with Telegram."""
    url = f"{TELEGRAM_API}/bot{config.TELEGRAM_BOT_TOKEN}/deleteWebhook"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url) as resp:
                body = await resp.json()
                logger.info("webhook.deleted | response=%s", body)
    except Exception as exc:
        logger.warning(
            "webhook.delete_failed | error=%s",
            redact_sensitive(exc)[:200],
        )


async def on_startup(app: web.Application) -> None:
    """Startup hook: register webhook."""
    logger.info("app.starting | version=%s", VERSION)
    await set_webhook(app["config"])


async def on_shutdown(app: web.Application) -> None:
    """Shutdown hook: delete webhook, close DB pool."""
    logger.info("app.shutting_down | version=%s", VERSION)
    config = app["config"]
    await delete_webhook(config)
    pool = app.get("db_pool")
    if pool is not None:
        await close_pool(pool)
    logger.info("app.shutdown_complete")


def _handle_signal(sig: signal.Signals, loop: asyncio.AbstractEventLoop) -> None:
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    logger.info("app.signal_received | signal=%s", sig.name)
    raise SystemExit(0)


def main() -> None:
    """Main entry point."""
    config = Config()

    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="[%(levelname)-8s] %(name)-24s | %(message)s",
        stream=sys.stdout,
    )

    logger.info("app.init | version=%s port=%d", VERSION, config.PORT)

    async def init_app() -> web.Application:
        pool = await create_pool(config.DATABASE_URL)
        app = create_app(config, pool)
        app["config"] = config
        app.on_startup.append(on_startup)
        app.on_shutdown.append(on_shutdown)
        return app

    web.run_app(init_app(), port=config.PORT)


if __name__ == "__main__":
    main()
