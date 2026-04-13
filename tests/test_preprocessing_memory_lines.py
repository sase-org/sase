"""Tests for DYNAMIC MEMORY line protection in preprocessing."""

from unittest.mock import MagicMock, patch

from sase.llm_provider.preprocessing import (
    _protect_memory_lines,
    _unprotect_memory_lines,
    preprocess_prompt_late,
)


class TestProtectUnprotectMemoryLines:
    """Unit tests for _protect_memory_lines / _unprotect_memory_lines."""

    def test_basic_roundtrip(self) -> None:
        text = "before\nDYNAMIC MEMORY: @/tmp/sase_dynamic_memory_abc_.md\nafter"
        lines: list[str] = []
        protected = _protect_memory_lines(text, lines)
        assert "DYNAMIC MEMORY" not in protected
        assert "before" in protected
        assert "after" in protected
        assert len(lines) == 1
        restored = _unprotect_memory_lines(protected, lines)
        assert restored == text

    def test_no_memory_lines(self) -> None:
        text = "just a normal prompt\nwith no memory lines"
        lines: list[str] = []
        protected = _protect_memory_lines(text, lines)
        assert protected == text
        assert len(lines) == 0

    def test_multiple_memory_lines(self) -> None:
        text = "DYNAMIC MEMORY: @/tmp/file1.md\nmiddle\nDYNAMIC MEMORY: @/tmp/file2.md"
        lines: list[str] = []
        protected = _protect_memory_lines(text, lines)
        assert "DYNAMIC MEMORY" not in protected
        assert "middle" in protected
        assert len(lines) == 2
        restored = _unprotect_memory_lines(protected, lines)
        assert restored == text


class TestPreprocessPromptLateMemoryProtection:
    """Integration: DYNAMIC MEMORY lines survive Prettier processing."""

    @patch(
        "sase.gemini_wrapper.file_references.process_command_substitution",
        side_effect=lambda x: x,
    )
    @patch("sase.gemini_wrapper.file_references.format_with_prettier")
    @patch(
        "sase.gemini_wrapper.file_references.strip_html_comments",
        side_effect=lambda x: x,
    )
    @patch("sase.xprompt.is_jinja2_template", return_value=False)
    def test_underscore_path_survives_prettier(
        self,
        _mock_jinja: MagicMock,
        _mock_html: MagicMock,
        mock_prettier: MagicMock,
        _mock_cmd_sub: MagicMock,
    ) -> None:
        """Prettier should never see the DYNAMIC MEMORY line.

        Simulates Prettier converting _text_ to *text* — the memory line
        must be restored intact afterward.
        """

        def fake_prettier(text: str) -> str:
            # Simulate Prettier's emphasis normalization
            return text.replace("_dynamic_memory_ghsbpnu_", "*dynamic_memory_ghsbpnu*")

        mock_prettier.side_effect = fake_prettier

        prompt = (
            "Some prompt text.\n\nDYNAMIC MEMORY: @/tmp/sase_dynamic_memory_ghsbpnu_.md"
        )
        result = preprocess_prompt_late(prompt, file_ref_mode="skip")
        assert "DYNAMIC MEMORY: @/tmp/sase_dynamic_memory_ghsbpnu_.md" in result
        assert "*" not in result

    @patch(
        "sase.gemini_wrapper.file_references.process_command_substitution",
        side_effect=lambda x: x,
    )
    @patch(
        "sase.gemini_wrapper.file_references.format_with_prettier",
        side_effect=lambda x: x,
    )
    @patch(
        "sase.gemini_wrapper.file_references.strip_html_comments",
        side_effect=lambda x: x,
    )
    @patch("sase.xprompt.is_jinja2_template", return_value=False)
    def test_memory_line_preserved_with_passthrough_prettier(
        self,
        _mock_jinja: MagicMock,
        _mock_html: MagicMock,
        _mock_prettier: MagicMock,
        _mock_cmd_sub: MagicMock,
    ) -> None:
        """Memory line passes through intact even with no-op Prettier."""
        prompt = (
            "prompt text\n\n"
            "DYNAMIC MEMORY: @/home/user/tmp/sase/sase_dynamic_memory_abc_.md"
        )
        result = preprocess_prompt_late(prompt, file_ref_mode="skip")
        assert (
            "DYNAMIC MEMORY: @/home/user/tmp/sase/sase_dynamic_memory_abc_.md" in result
        )
