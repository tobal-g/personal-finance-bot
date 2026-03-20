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
from bot.webhook import WEBHOOK_PATH, create_app

logger = logging.getLogger(__name__)

VERSION = "1.0.0"

TELEGRAM_API = "https://api.telegram.org"


async def set_webhook(config: Config) -> None:
    """Register webhook with Telegram and verify the registration."""
    webhook_url = f"{config.WEBHOOK_URL}{WEBHOOK_PATH}"
    api_base = f"{TELEGRAM_API}/bot{config.TELEGRAM_BOT_TOKEN}"

    # Register
    payload = {
        "url": webhook_url,
        "secret_token": config.WEBHOOK_SECRET_TOKEN,
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
        "max_connections": 40,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{api_base}/setWebhook", json=payload) as resp:
            body = await resp.json()
            if resp.status != 200 or not body.get("ok"):
                logger.error(
                    "webhook.register_failed | response=%s",
                    redact_sensitive(body),
                )
                raise RuntimeError(f"Failed to set webhook: {body}")

        # Verify — confirm Telegram actually has the URL we expect
        async with session.get(f"{api_base}/getWebhookInfo") as resp:
            body = await resp.json()
            registered_url = body.get("result", {}).get("url", "")
            pending = body.get("result", {}).get("pending_update_count", 0)
            last_error = body.get("result", {}).get("last_error_message", "")

            if registered_url == webhook_url:
                logger.info(
                    "webhook.verified | url=%s pending=%d",
                    webhook_url,
                    pending,
                )
            else:
                logger.error(
                    "webhook.mismatch | expected=%s registered=%s last_error=%s",
                    webhook_url,
                    registered_url,
                    last_error,
                )
                raise RuntimeError(
                    f"Webhook URL mismatch: expected {webhook_url}, "
                    f"got {registered_url}"
                )


async def on_startup(app: web.Application) -> None:
    """Startup hook: register webhook."""
    logger.info("app.starting | version=%s", VERSION)
    await set_webhook(app["config"])


async def on_shutdown(app: web.Application) -> None:
    """Shutdown hook: close DB pool."""
    logger.info("app.shutting_down | version=%s", VERSION)
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
