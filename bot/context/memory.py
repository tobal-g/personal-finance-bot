"""Long-term memory: reads .md files from the memory/ directory."""

import logging
import os

logger = logging.getLogger(__name__)

MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "memory")


def load_memory() -> str:
    """Read all .md files from memory/ directory and concatenate.

    Returns empty string if no files found or directory doesn't exist.
    """
    if not os.path.isdir(MEMORY_DIR):
        return ""

    parts: list[str] = []
    for filename in sorted(os.listdir(MEMORY_DIR)):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(MEMORY_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    parts.append(f"## {filename}\n\n{content}")
        except OSError:
            logger.warning("memory.read_error | file=%s", filename, exc_info=True)

    return "\n\n".join(parts)
