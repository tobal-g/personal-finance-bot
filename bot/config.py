"""Environment configuration with validation."""

import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str, env: dict[str, str]) -> str:
    val = env.get(name, "").strip()
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


class Config:
    """Validated configuration loaded from environment variables."""

    def __init__(self, env: dict[str, str] | None = None):
        env = env if env is not None else dict(os.environ)

        missing: list[str] = []
        required = [
            "TELEGRAM_BOT_TOKEN",
            "WEBHOOK_URL",
            "WEBHOOK_SECRET_TOKEN",
            "DATABASE_URL",
            "OPENAI_API_KEY",
            "ALLOWED_CHAT_ID",
            "ALLOWED_USER_IDS",
        ]
        for name in required:
            if not env.get(name, "").strip():
                missing.append(name)
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        self.TELEGRAM_BOT_TOKEN: str = env["TELEGRAM_BOT_TOKEN"].strip()
        self.WEBHOOK_URL: str = env["WEBHOOK_URL"].strip().rstrip("/")
        self.WEBHOOK_SECRET_TOKEN: str = env["WEBHOOK_SECRET_TOKEN"].strip()
        self.DATABASE_URL: str = env["DATABASE_URL"].strip()
        self.OPENAI_API_KEY: str = env["OPENAI_API_KEY"].strip()
        self.ALLOWED_CHAT_ID: int = int(env["ALLOWED_CHAT_ID"].strip())
        self.ALLOWED_USER_IDS: frozenset[int] = frozenset(
            int(uid.strip())
            for uid in env["ALLOWED_USER_IDS"].strip().split(",")
            if uid.strip()
        )
        self.HEALTHCHECK_TOKEN: str = env.get("HEALTHCHECK_TOKEN", "").strip()
        self.LOG_LEVEL: str = env.get("LOG_LEVEL", "INFO").strip().upper()
        self.PORT: int = int(env.get("PORT", "8080").strip())
