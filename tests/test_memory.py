"""Tests for bot.context.memory."""

from bot.context import memory


def test_load_memory_caps_total_chars(tmp_path, monkeypatch):
    long_text = "x" * 1000
    (tmp_path / "notes.md").write_text(long_text, encoding="utf-8")

    monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
    monkeypatch.setattr(memory, "MAX_MEMORY_CHARS", 120)

    result = memory.load_memory()
    assert len(result) == 120


def test_load_memory_ignores_non_md_files(tmp_path, monkeypatch):
    (tmp_path / "notes.md").write_text("abc", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("should not load", encoding="utf-8")

    monkeypatch.setattr(memory, "MEMORY_DIR", str(tmp_path))
    result = memory.load_memory()

    assert "notes.md" in result
    assert "should not load" not in result
