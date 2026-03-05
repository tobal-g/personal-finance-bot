"""Tool registry with auto-discovery."""

import importlib
import inspect
import logging
import os
import pkgutil

from bot.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Registry that discovers and stores BaseTool subclasses."""

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool
        logger.debug("tools.registered | name=%s", tool.name)

    def get_tool(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def discover(self) -> None:
        """Auto-discover BaseTool subclasses in the bot.tools package."""
        package_dir = os.path.dirname(__file__)
        for module_info in pkgutil.iter_modules([package_dir]):
            if module_info.name in ("base", "__init__"):
                continue
            try:
                module = importlib.import_module(f"bot.tools.{module_info.name}")
                for _name, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, BaseTool)
                        and obj is not BaseTool
                        and hasattr(obj, "name")
                        and obj.name
                    ):
                        instance = obj()
                        self.register(instance)
                        for alias in getattr(instance, "aliases", []):
                            self._tools[alias] = instance
                            logger.debug("tools.alias_registered | alias=%s -> %s", alias, instance.name)
            except Exception:
                logger.warning(
                    "tools.discover_error | module=%s",
                    module_info.name,
                    exc_info=True,
                )
