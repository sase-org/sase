"""Tests for YAML config xprompt insertion logic."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.modals.xprompt_config_yaml import (
    _generate_xprompt_yaml,
    insert_xprompt_into_config,
)


class TestGenerateXpromptYaml:
    """Tests for _generate_xprompt_yaml."""

    def test_short_form_no_inputs(self) -> None:
        lines = _generate_xprompt_yaml("foo", [], "Hello world")
        assert lines == [
            "  foo: |",
            "    Hello world",
        ]

    def test_short_form_multiline(self) -> None:
        lines = _generate_xprompt_yaml("foo", [], "Line 1\nLine 2\nLine 3")
        assert lines == [
            "  foo: |",
            "    Line 1",
            "    Line 2",
            "    Line 3",
        ]

    def test_short_form_blank_lines(self) -> None:
        lines = _generate_xprompt_yaml("foo", [], "Line 1\n\nLine 3")
        assert lines == [
            "  foo: |",
            "    Line 1",
            "",
            "    Line 3",
        ]

    def test_long_form_with_inputs(self) -> None:
        lines = _generate_xprompt_yaml("greet", [("name", "word")], "Hello {{ name }}!")
        assert lines == [
            "  greet:",
            "    input:",
            "      name: word",
            "    content: |",
            "      Hello {{ name }}!",
        ]

    def test_long_form_multiple_inputs(self) -> None:
        lines = _generate_xprompt_yaml(
            "greet",
            [("name", "word"), ("count", "int")],
            "Hello {{ name }}, count={{ count }}",
        )
        assert lines == [
            "  greet:",
            "    input:",
            "      name: word",
            "      count: int",
            "    content: |",
            "      Hello {{ name }}, count={{ count }}",
        ]

    def test_trailing_newlines_stripped(self) -> None:
        lines = _generate_xprompt_yaml("foo", [], "Hello\n\n\n")
        assert lines == [
            "  foo: |",
            "    Hello",
        ]


class TestInsertXpromptIntoConfig:
    """Tests for insert_xprompt_into_config."""

    def test_insert_into_existing_section(self, tmp_path: Path) -> None:
        config = tmp_path / "sase.yml"
        config.write_text(
            "xprompts:\n"
            "  alpha: |\n"
            "    Alpha content\n"
            "\n"
            "  charlie: |\n"
            "    Charlie content\n"
        )
        result = insert_xprompt_into_config(str(config), "bravo", [], "Bravo content")
        assert result is True
        text = config.read_text()
        # All three should appear in alphabetical order
        alpha_pos = text.index("alpha:")
        bravo_pos = text.index("bravo:")
        charlie_pos = text.index("charlie:")
        assert alpha_pos < bravo_pos < charlie_pos

    def test_insert_first_alphabetically(self, tmp_path: Path) -> None:
        config = tmp_path / "sase.yml"
        config.write_text("xprompts:\n  bravo: |\n    Bravo content\n")
        result = insert_xprompt_into_config(str(config), "alpha", [], "Alpha content")
        assert result is True
        text = config.read_text()
        assert text.index("alpha:") < text.index("bravo:")

    def test_insert_last_alphabetically(self, tmp_path: Path) -> None:
        config = tmp_path / "sase.yml"
        config.write_text("xprompts:\n  alpha: |\n    Alpha content\n")
        result = insert_xprompt_into_config(str(config), "zulu", [], "Zulu content")
        assert result is True
        text = config.read_text()
        assert text.index("alpha:") < text.index("zulu:")

    def test_insert_into_empty_section(self, tmp_path: Path) -> None:
        config = tmp_path / "sase.yml"
        config.write_text("xprompts: {}\n")
        result = insert_xprompt_into_config(str(config), "foo", [], "Foo content")
        assert result is True
        text = config.read_text()
        assert "  foo: |" in text
        assert "    Foo content" in text

    def test_insert_no_xprompts_section(self, tmp_path: Path) -> None:
        config = tmp_path / "sase.yml"
        config.write_text("other_key: value\n")
        result = insert_xprompt_into_config(str(config), "foo", [], "Foo content")
        assert result is True
        text = config.read_text()
        assert "xprompts:" in text
        assert "  foo: |" in text

    def test_insert_with_inputs(self, tmp_path: Path) -> None:
        config = tmp_path / "sase.yml"
        config.write_text("xprompts:\n  existing: |\n    Hello\n")
        result = insert_xprompt_into_config(
            str(config), "greet", [("name", "word")], "Hello {{ name }}!"
        )
        assert result is True
        text = config.read_text()
        assert "  greet:" in text
        assert "    input:" in text
        assert "      name: word" in text
        assert "    content: |" in text
        assert "      Hello {{ name }}!" in text

    def test_sorts_unsorted_entries(self, tmp_path: Path) -> None:
        config = tmp_path / "sase.yml"
        config.write_text(
            "xprompts:\n"
            "  charlie: |\n"
            "    Charlie content\n"
            "\n"
            "  alpha: |\n"
            "    Alpha content\n"
        )
        result = insert_xprompt_into_config(str(config), "bravo", [], "Bravo content")
        assert result is True
        text = config.read_text()
        alpha_pos = text.index("alpha:")
        bravo_pos = text.index("bravo:")
        charlie_pos = text.index("charlie:")
        assert alpha_pos < bravo_pos < charlie_pos

    def test_preserves_other_sections(self, tmp_path: Path) -> None:
        config = tmp_path / "sase.yml"
        config.write_text(
            "ace:\n"
            "  key: value\n"
            "\n"
            "xprompts:\n"
            "  existing: |\n"
            "    Content\n"
            "\n"
            "other:\n"
            "  foo: bar\n"
        )
        result = insert_xprompt_into_config(str(config), "new_one", [], "New content")
        assert result is True
        text = config.read_text()
        assert "ace:" in text
        assert "  key: value" in text
        assert "other:" in text
        assert "  foo: bar" in text

    def test_insert_with_slash_name(self, tmp_path: Path) -> None:
        config = tmp_path / "sase.yml"
        config.write_text("xprompts:\n  aaa: |\n    Content\n")
        result = insert_xprompt_into_config(
            str(config), "bd/next", [("prompt", "text")], "Do the thing {{ prompt }}"
        )
        assert result is True
        text = config.read_text()
        assert "  bd/next:" in text
        assert "      prompt: text" in text

    def test_long_form_entry_preserved(self, tmp_path: Path) -> None:
        """Existing long-form entries should be preserved during sort."""
        config = tmp_path / "sase.yml"
        config.write_text(
            "xprompts:\n"
            "  existing:\n"
            "    input:\n"
            "      bar: word\n"
            "    content: |\n"
            "      Hello {{ bar }}\n"
        )
        result = insert_xprompt_into_config(str(config), "aaa", [], "Simple content")
        assert result is True
        text = config.read_text()
        # aaa should come first
        assert text.index("aaa:") < text.index("existing:")
        # existing entry should still have its input block
        assert "      bar: word" in text
        assert "      Hello {{ bar }}" in text
