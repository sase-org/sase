"""Tests for fenced code block protection in preprocessing."""

from typing import Any
from unittest.mock import MagicMock, patch

from sase.llm_provider.preprocessing import preprocess_prompt
from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from sase.xprompt.directives import PromptDirectives


class TestProtectFencedBlocks:
    """Tests for protect_fenced_blocks()."""

    def test_no_code_blocks(self) -> None:
        text = "Hello world"
        blocks: list[str] = []
        result = protect_fenced_blocks(text, blocks)
        assert result == "Hello world"
        assert blocks == []

    def test_single_code_block(self) -> None:
        text = "before\n```python\ncode here\n```\nafter"
        blocks: list[str] = []
        result = protect_fenced_blocks(text, blocks)
        assert len(blocks) == 1
        assert blocks[0] == "```python\ncode here\n```"
        assert "code here" not in result
        assert "before" in result
        assert "after" in result

    def test_multiple_code_blocks(self) -> None:
        text = "a\n```\nblock1\n```\nb\n```js\nblock2\n```\nc"
        blocks: list[str] = []
        result = protect_fenced_blocks(text, blocks)
        assert len(blocks) == 2
        assert "block1" in blocks[0]
        assert "block2" in blocks[1]
        assert "block1" not in result
        assert "block2" not in result

    def test_code_block_with_special_syntax(self) -> None:
        text = "text\n```\n#xprompt $(echo hi) @file {{ var }}\n```\nmore"
        blocks: list[str] = []
        result = protect_fenced_blocks(text, blocks)
        assert len(blocks) == 1
        assert "#xprompt $(echo hi) @file {{ var }}" in blocks[0]
        assert "#xprompt" not in result


class TestUnprotectFencedBlocks:
    """Tests for unprotect_fenced_blocks()."""

    def test_round_trip(self) -> None:
        original = "before\n```python\ncode here\n```\nafter"
        blocks: list[str] = []
        text = protect_fenced_blocks(original, blocks)
        restored = unprotect_fenced_blocks(text, blocks)
        assert restored == original

    def test_multiple_blocks_round_trip(self) -> None:
        original = "a\n```\nblock1\n```\nb\n```js\nblock2\n```\nc"
        blocks: list[str] = []
        text = protect_fenced_blocks(original, blocks)
        restored = unprotect_fenced_blocks(text, blocks)
        assert restored == original

    def test_empty_blocks_list(self) -> None:
        text = "no placeholders here"
        assert unprotect_fenced_blocks(text, []) == text


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
    def test_code_block_content_not_passed_to_late_processors(
        self,
        mock_directives: MagicMock,
        mock_xprompt: MagicMock,
        mock_cmd_sub: MagicMock,
        mock_file_refs: MagicMock,
        mock_prettier: MagicMock,
        mock_strip: MagicMock,
    ) -> None:
        """Late-phase processors should never see the raw code block content."""
        for mock in [
            mock_xprompt,
            mock_cmd_sub,
            mock_file_refs,
            mock_prettier,
            mock_strip,
        ]:
            mock.side_effect = _passthrough
        mock_directives.side_effect = lambda x: (x, PromptDirectives())

        code_block_content = "#xprompt $(echo hi) @file %directive {{ jinja }}"
        prompt = f"normal text\n```\n{code_block_content}\n```\nmore text"

        result = preprocess_prompt(prompt)

        # The code block content should appear in the final output untouched
        assert code_block_content in result.prompt

        # Late-phase processors should have received text WITHOUT code block content
        # (process_xprompt_references handles its own fenced block protection)
        late_mocks = [mock_cmd_sub, mock_file_refs, mock_prettier, mock_strip]
        for mock in late_mocks:
            for call in mock.call_args_list:
                processed_text = call[0][0]
                assert code_block_content not in processed_text

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
        mock_directives.side_effect = lambda x: (x, PromptDirectives())

        prompt = "outside text\n```\ninside block\n```\nmore outside"
        preprocess_prompt(prompt)

        # Late-phase processor (command sub) should see "outside text"
        first_call_text = mock_cmd_sub.call_args[0][0]
        assert "outside text" in first_call_text
        assert "more outside" in first_call_text
