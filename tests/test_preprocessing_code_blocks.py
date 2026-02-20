"""Tests for fenced code block protection in preprocessing."""

from typing import Any
from unittest.mock import MagicMock, patch

from sase.llm_provider.preprocessing import (
    _extract_fenced_code_blocks,
    _restore_fenced_code_blocks,
    preprocess_prompt,
)
from sase.xprompt.directives import PromptDirectives


class TestExtractFencedCodeBlocks:
    """Tests for _extract_fenced_code_blocks()."""

    def test_no_code_blocks(self) -> None:
        text = "Hello world"
        result, blocks = _extract_fenced_code_blocks(text)
        assert result == "Hello world"
        assert blocks == []

    def test_single_code_block(self) -> None:
        text = "before\n```python\ncode here\n```\nafter"
        result, blocks = _extract_fenced_code_blocks(text)
        assert len(blocks) == 1
        assert blocks[0] == "```python\ncode here\n```"
        assert "code here" not in result
        assert "before" in result
        assert "after" in result

    def test_multiple_code_blocks(self) -> None:
        text = "a\n```\nblock1\n```\nb\n```js\nblock2\n```\nc"
        result, blocks = _extract_fenced_code_blocks(text)
        assert len(blocks) == 2
        assert "block1" in blocks[0]
        assert "block2" in blocks[1]
        assert "block1" not in result
        assert "block2" not in result

    def test_code_block_with_special_syntax(self) -> None:
        text = "text\n```\n#xprompt $(echo hi) @file {{ var }}\n```\nmore"
        result, blocks = _extract_fenced_code_blocks(text)
        assert len(blocks) == 1
        assert "#xprompt $(echo hi) @file {{ var }}" in blocks[0]
        assert "#xprompt" not in result


class TestRestoreFencedCodeBlocks:
    """Tests for _restore_fenced_code_blocks()."""

    def test_round_trip(self) -> None:
        original = "before\n```python\ncode here\n```\nafter"
        text, blocks = _extract_fenced_code_blocks(original)
        restored = _restore_fenced_code_blocks(text, blocks)
        assert restored == original

    def test_multiple_blocks_round_trip(self) -> None:
        original = "a\n```\nblock1\n```\nb\n```js\nblock2\n```\nc"
        text, blocks = _extract_fenced_code_blocks(original)
        restored = _restore_fenced_code_blocks(text, blocks)
        assert restored == original

    def test_empty_blocks_list(self) -> None:
        text = "no placeholders here"
        assert _restore_fenced_code_blocks(text, []) == text


def _passthrough(x: str, **_kw: Any) -> str:
    return x


class TestPreprocessPromptCodeBlockProtection:
    """Integration tests verifying code block content bypasses processors."""

    @patch("sase.llm_provider.preprocessing.process_xprompt_references")
    @patch("sase.llm_provider.preprocessing.process_command_substitution")
    @patch("sase.llm_provider.preprocessing.process_file_references")
    @patch("sase.llm_provider.preprocessing.format_with_prettier")
    @patch("sase.llm_provider.preprocessing.strip_html_comments")
    @patch("sase.llm_provider.preprocessing.extract_prompt_directives")
    def test_code_block_content_not_passed_to_processors(
        self,
        mock_directives: MagicMock,
        mock_strip: MagicMock,
        mock_prettier: MagicMock,
        mock_file_refs: MagicMock,
        mock_cmd_sub: MagicMock,
        mock_xprompt: MagicMock,
    ) -> None:
        """Processors should never see the raw code block content."""
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

        # Each processor should have received text WITHOUT the code block content
        for mock in [
            mock_xprompt,
            mock_cmd_sub,
            mock_file_refs,
            mock_prettier,
            mock_strip,
        ]:
            for call in mock.call_args_list:
                processed_text = call[0][0]
                assert code_block_content not in processed_text

    @patch("sase.llm_provider.preprocessing.process_xprompt_references")
    @patch("sase.llm_provider.preprocessing.process_command_substitution")
    @patch("sase.llm_provider.preprocessing.process_file_references")
    @patch("sase.llm_provider.preprocessing.format_with_prettier")
    @patch("sase.llm_provider.preprocessing.strip_html_comments")
    @patch("sase.llm_provider.preprocessing.extract_prompt_directives")
    def test_text_outside_code_blocks_still_processed(
        self,
        mock_directives: MagicMock,
        mock_strip: MagicMock,
        mock_prettier: MagicMock,
        mock_file_refs: MagicMock,
        mock_cmd_sub: MagicMock,
        mock_xprompt: MagicMock,
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

        # xprompt (first processor after directives) should see "outside text"
        first_call_text = mock_xprompt.call_args[0][0]
        assert "outside text" in first_call_text
        assert "more outside" in first_call_text
