"""Tests for fenced code block protection in preprocessing."""

from typing import Any
from unittest.mock import MagicMock, patch

from sase.llm_provider.preprocessing import preprocess_prompt
from sase.xprompt.directives import PromptDirectives


class TestProtectFencedBlocks:
    """Tests for protect_fenced_blocks()."""


class TestUnprotectFencedBlocks:
    """Tests for unprotect_fenced_blocks()."""


def _passthrough(x: str, **_kw: Any) -> str:
    return x


class TestPreprocessPromptCodeBlockProtection:
    """Integration tests verifying code block content bypasses processors."""

    # Late-phase processors (command sub, file refs, prettier, HTML strip)
    # are protected by the late phase's own fenced-block protection.
    # process_xprompt_references handles its own protection internally.
    @patch("sase.gemini_wrapper.file_references.strip_html_comments")
    @patch("sase.gemini_wrapper.file_references.format_with_prettier")
    @patch("sase.gemini_wrapper.file_references.process_file_references")
    @patch("sase.gemini_wrapper.file_references.process_command_substitution")
    @patch("sase.xprompt.process_xprompt_references")
    @patch("sase.llm_provider.preprocessing.extract_prompt_directives")
    def test_text_outside_code_blocks_still_processed(
        self,
        mock_directives: MagicMock,
        mock_xprompt: MagicMock,
        mock_cmd_sub: MagicMock,
        mock_file_refs: MagicMock,
        mock_prettier: MagicMock,
        mock_strip: MagicMock,
    ) -> None:
        """Text outside code blocks should still go through processors."""
        for mock in [
            mock_xprompt,
            mock_cmd_sub,
            mock_file_refs,
            mock_prettier,
            mock_strip,
        ]:
            mock.side_effect = _passthrough
        mock_directives.side_effect = lambda x, **_kw: (x, PromptDirectives())

        prompt = "outside text\n```\ninside block\n```\nmore outside"
        preprocess_prompt(prompt)

        # Late-phase processor (command sub) should see "outside text"
        first_call_text = mock_cmd_sub.call_args[0][0]
        assert "outside text" in first_call_text
        assert "more outside" in first_call_text
