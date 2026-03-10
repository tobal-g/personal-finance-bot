"""Long-term memory: reads .md files from the memory/ directory."""

import logging
import os

logger = logging.getLogger(__name__)

MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "memory")
MAX_MEMORY_CHARS = 4000

# Files loaded via load_memory_file() — excluded from general load_memory()
_DEDICATED_FILES = {"spending_behaviors.md"}


def load_memory(max_chars: int | None = None) -> str:
    """Read all .md files from memory/ directory and concatenate.

    Returns empty string if no files found or directory doesn't exist.
    """
    if not os.path.isdir(MEMORY_DIR):
        return ""

    parts: list[str] = []
    for filename in sorted(os.listdir(MEMORY_DIR)):
        if not filename.endswith(".md"):
            continue
        if filename in _DEDICATED_FILES:
            continue
        filepath = os.path.join(MEMORY_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    parts.append(f"## {filename}\n\n{content}")
        except OSError:
            logger.warning("memory.read_error | file=%s", filename, exc_info=True)

    limit = MAX_MEMORY_CHARS if max_chars is None else max_chars
    return "\n\n".join(parts)[:limit]


def load_memory_file(filename: str) -> str:
    """Read a specific memory file by name.

    Returns empty string if file doesn't exist or is empty.
    """
    filepath = os.path.join(MEMORY_DIR, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except OSError:
        logger.info("memory.load | file=%s chars=0 status=not_found", filename)
        return ""

    logger.info("memory.load | file=%s chars=%d", filename, len(content))
    return content
