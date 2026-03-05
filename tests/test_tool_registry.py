"""Tests for bot.tools (ToolRegistry)."""

import pytest

from bot.tools import ToolRegistry
from bot.tools.base import BaseTool, ToolContext


class _FakeTool(BaseTool):
    name = "fake_tool"
    description = "A fake tool for testing"

    async def execute(self, data: dict, context: ToolContext) -> str:
        return "fake result"


class TestToolRegistry:
    def test_empty_registry(self):
        registry = ToolRegistry()
        assert registry.list_tools() == []

    def test_register_and_get(self):
        registry = ToolRegistry()
        tool = _FakeTool()
        registry.register(tool)

        assert registry.get_tool("fake_tool") is tool
        assert "fake_tool" in registry.list_tools()

    def test_get_unknown_returns_none(self):
        registry = ToolRegistry()
        assert registry.get_tool("nonexistent") is None

    def test_discover_with_no_tool_modules(self):
        # discover() should work even when there are no tool modules yet
        registry = ToolRegistry()
        registry.discover()
        # No tools should be registered since we haven't created any tool files
        # (base.py and __init__.py are excluded from discovery)
        # This just verifies discover() doesn't crash
        assert isinstance(registry.list_tools(), list)
