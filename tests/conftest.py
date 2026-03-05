"""Shared fixtures for tests."""

import pytest

from bot.config import Config


def make_env(**overrides) -> dict[str, str]:
    """Return a minimal valid env dict, with optional overrides."""
    base = {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "WEBHOOK_URL": "https://example.com",
        "WEBHOOK_SECRET_TOKEN": "test-secret",
        "DATABASE_URL": "postgresql://user:pass@localhost/testdb",
        "OPENAI_API_KEY": "sk-test",
        "ALLOWED_CHAT_ID": "-100",
        "ALLOWED_USER_IDS": "111,222",
        "HEALTHCHECK_TOKEN": "health-test-token",
        "LOG_LEVEL": "DEBUG",
        "PORT": "9090",
    }
    base.update(overrides)
    return base


@pytest.fixture
def valid_env():
    return make_env()


@pytest.fixture
def config(valid_env):
    return Config(env=valid_env)
