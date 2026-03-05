"""Tests for bot.utils.parsing."""

from bot.utils.parsing import extract_json


class TestExtractJson:
    def test_clean_json(self):
        result = extract_json('{"task": "log_expense", "amount": 1500}')
        assert result == {"task": "log_expense", "amount": 1500}

    def test_markdown_fenced_json(self):
        text = '```json\n{"task": "log_expense"}\n```'
        result = extract_json(text)
        assert result == {"task": "log_expense"}

    def test_markdown_fenced_no_lang(self):
        text = '```\n{"task": "query"}\n```'
        result = extract_json(text)
        assert result == {"task": "query"}

    def test_leading_text_before_json(self):
        text = 'Here is the result:\n{"task": "log_expense", "data": {}}'
        result = extract_json(text)
        assert result == {"task": "log_expense", "data": {}}

    def test_invalid_json_returns_none(self):
        result = extract_json("{bad json here}")
        assert result is None

    def test_empty_string_returns_none(self):
        result = extract_json("")
        assert result is None

    def test_none_returns_none(self):
        result = extract_json(None)
        assert result is None

    def test_whitespace_only_returns_none(self):
        result = extract_json("   \n  ")
        assert result is None

    def test_json_array_returns_none(self):
        result = extract_json("[1, 2, 3]")
        assert result is None

    def test_nested_json(self):
        text = '{"tasks": [{"task": "a"}, {"task": "b"}]}'
        result = extract_json(text)
        assert result["tasks"][0]["task"] == "a"

    def test_json_with_trailing_text(self):
        text = '{"task": "log"} some trailing text'
        result = extract_json(text)
        assert result == {"task": "log"}
