"""Tests for bot.config."""

import pytest

from bot.config import Config
from tests.conftest import make_env


class TestConfig:
    def test_valid_config(self):
        cfg = Config(env=make_env())
        assert cfg.TELEGRAM_BOT_TOKEN == "test-token"
        assert cfg.WEBHOOK_URL == "https://example.com"
        assert cfg.WEBHOOK_SECRET_TOKEN == "test-secret"
        assert cfg.ALLOWED_CHAT_ID == -100
        assert cfg.ALLOWED_USER_IDS == frozenset({111, 222})
        assert cfg.HEALTHCHECK_TOKEN == "health-test-token"
        assert cfg.LOG_LEVEL == "DEBUG"
        assert cfg.PORT == 9090
        assert cfg.CONTEXT_MAX_USER_CHARS == 350
        assert cfg.CONTEXT_MAX_MEMORY_CHARS == 3000
        assert cfg.QUERY_FORMAT_MAX_ROWS == 40
        assert cfg.QUERY_FORMAT_MAX_CHARS == 7000

    def test_missing_single_var_raises(self):
        env = make_env()
        del env["TELEGRAM_BOT_TOKEN"]
        with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
            Config(env=env)

    def test_missing_multiple_vars_lists_all(self):
        env = make_env()
        del env["TELEGRAM_BOT_TOKEN"]
        del env["DATABASE_URL"]
        with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN") as exc_info:
            Config(env=env)
        assert "DATABASE_URL" in str(exc_info.value)

    def test_empty_var_treated_as_missing(self):
        env = make_env(TELEGRAM_BOT_TOKEN="  ")
        with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
            Config(env=env)

    def test_allowed_user_ids_parsing_single(self):
        cfg = Config(env=make_env(ALLOWED_USER_IDS="999"))
        assert cfg.ALLOWED_USER_IDS == frozenset({999})

    def test_allowed_user_ids_parsing_multiple(self):
        cfg = Config(env=make_env(ALLOWED_USER_IDS="1, 2, 3"))
        assert cfg.ALLOWED_USER_IDS == frozenset({1, 2, 3})

    def test_allowed_user_ids_ignores_trailing_comma(self):
        cfg = Config(env=make_env(ALLOWED_USER_IDS="1,2,"))
        assert cfg.ALLOWED_USER_IDS == frozenset({1, 2})

    def test_defaults_log_level(self):
        env = make_env()
        del env["LOG_LEVEL"]
        cfg = Config(env=env)
        assert cfg.LOG_LEVEL == "INFO"

    def test_defaults_port(self):
        env = make_env()
        del env["PORT"]
        cfg = Config(env=env)
        assert cfg.PORT == 8080

    def test_defaults_healthcheck_token(self):
        env = make_env()
        del env["HEALTHCHECK_TOKEN"]
        cfg = Config(env=env)
        assert cfg.HEALTHCHECK_TOKEN == ""

    def test_webhook_url_strips_trailing_slash(self):
        cfg = Config(env=make_env(WEBHOOK_URL="https://example.com/"))
        assert cfg.WEBHOOK_URL == "https://example.com"

    def test_defaults_context_and_query_caps(self):
        env = make_env()
        del env["CONTEXT_MAX_USER_CHARS"]
        del env["CONTEXT_MAX_MEMORY_CHARS"]
        del env["QUERY_FORMAT_MAX_ROWS"]
        del env["QUERY_FORMAT_MAX_CHARS"]
        cfg = Config(env=env)
        assert cfg.CONTEXT_MAX_USER_CHARS == 400
        assert cfg.CONTEXT_MAX_MEMORY_CHARS == 4000
        assert cfg.QUERY_FORMAT_MAX_ROWS == 50
        assert cfg.QUERY_FORMAT_MAX_CHARS == 8000

    def test_invalid_context_cap_raises(self):
        with pytest.raises(RuntimeError, match="CONTEXT_MAX_USER_CHARS"):
            Config(env=make_env(CONTEXT_MAX_USER_CHARS="0"))

    def test_invalid_query_cap_raises(self):
        with pytest.raises(RuntimeError, match="QUERY_FORMAT_MAX_CHARS"):
            Config(env=make_env(QUERY_FORMAT_MAX_CHARS="abc"))
