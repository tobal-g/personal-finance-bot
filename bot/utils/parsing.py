"""JSON extraction utilities."""

import json
import re


def extract_json(text: str) -> dict | None:
    """Extract a JSON object from text that may contain markdown fences or preamble.

    Returns the parsed dict, or None if no valid JSON found.
    """
    if not text or not text.strip():
        return None

    # Try direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
        return None
    except (json.JSONDecodeError, TypeError):
        pass

    # Strip markdown code fences
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fenced:
        try:
            result = json.loads(fenced.group(1))
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, TypeError):
            pass

    # Find first { ... } block
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        try:
            result = json.loads(brace_match.group(0))
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, TypeError):
            pass

    return None
