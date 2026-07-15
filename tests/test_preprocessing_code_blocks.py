"""Tests for fenced code block protection in preprocessing."""

from typing import Any
from unittest.mock import MagicMock, patch

from sase.llm_provider.preprocessing import preprocess_prompt, preprocess_prompt_late
from sase.xprompt._fenced_blocks import (
    fenced_block_details,
    fenced_block_ranges,
    protect_fenced_blocks,
    protect_fenced_blocks_only,
    unprotect_fenced_blocks,
)
from sase.xprompt.directives import PromptDirectives

_BOXED_INNER_FENCE_PROMPT = (
    "before\n"
    "```\n"
    "outer snapshot\n"
    "| prompt displays an inner fence:\n"
    "|  ```\n"
    "|  @a9q.cdx\n"
    "|  @a9y.f1\n"
    "|  @a9f.w1\n"
    "still inside the outer snapshot\n"
    "```\n"
    "after\n"
)

_BOXED_INNER_FENCE_BLOCK = (
    "```\n"
    "outer snapshot\n"
    "| prompt displays an inner fence:\n"
    "|  ```\n"
    "|  @a9q.cdx\n"
    "|  @a9y.f1\n"
    "|  @a9f.w1\n"
    "still inside the outer snapshot\n"
    "```"
)


class TestProtectFencedBlocks:
    """Tests for protect_fenced_blocks()."""

    def test_protects_boxed_displayed_inner_fence(self) -> None:
        """Displayed backticks inside a capture are not Markdown closers."""
        blocks: list[str] = []

        protected = protect_fenced_blocks(_BOXED_INNER_FENCE_PROMPT, blocks)

        assert blocks == [_BOXED_INNER_FENCE_BLOCK]
        assert protected == "before\n\x00XPF_0\x00\nafter\n"
        assert "@a9q.cdx" not in protected

    def test_protects_tilde_fence(self) -> None:
        blocks: list[str] = []
        prompt = "before\n~~~ text\ninside\n~~~\nafter\n"

        protected = protect_fenced_blocks(prompt, blocks)

        assert blocks == ["~~~ text\ninside\n~~~"]
        assert protected == "before\n\x00XPF_0\x00\nafter\n"

    def test_fence_only_protection_leaves_inline_code_visible(self) -> None:
        blocks: list[str] = []
        prompt = "before `#inline`\n```\n#fenced\n```\nafter"

        protected = protect_fenced_blocks_only(prompt, blocks)

        assert blocks == ["```\n#fenced\n```"]
        assert "`#inline`" in protected
        assert "#fenced" not in protected


class TestUnprotectFencedBlocks:
    """Tests for unprotect_fenced_blocks()."""

    def test_unprotects_protected_fence(self) -> None:
        blocks: list[str] = []
        protected = protect_fenced_blocks(_BOXED_INNER_FENCE_PROMPT, blocks)

        unprotected = unprotect_fenced_blocks(protected, blocks)

        assert unprotected == _BOXED_INNER_FENCE_PROMPT


def test_fenced_block_ranges_include_boxed_displayed_inner_fence() -> None:
    start = len("before\n")
    end = start + len(_BOXED_INNER_FENCE_BLOCK)

    assert fenced_block_ranges(_BOXED_INNER_FENCE_PROMPT) == [(start, end)]


def test_fenced_block_ranges_unclosed_fence_runs_to_end() -> None:
    prompt = "before\n```\n@missing.md\n"
    start = len("before\n")

    assert fenced_block_ranges(prompt) == [(start, len(prompt))]


def test_fenced_block_details_share_closed_fence_scanner_offsets() -> None:
    prompt = "before\n  ~~~~ python title=demo\nprint('hi')\n ~~~~~  \nafter"

    [details] = fenced_block_details(prompt)

    assert prompt[slice(*details.opening_fence)] == "~~~~"
    assert details.info_string is not None
    assert prompt[slice(*details.info_string)] == "python title=demo"
    assert prompt[slice(*details.content_range)] == "print('hi')\n"
    assert details.closing_fence is not None
    assert prompt[slice(*details.closing_fence)] == "~~~~~"
    assert [details.block_range] == fenced_block_ranges(prompt)


def test_fenced_block_details_expose_live_unclosed_content_to_eof() -> None:
    prompt = "```py\nvalue = 1"

    [details] = fenced_block_details(prompt)

    assert details.closing_fence is None
    assert details.content_range == (len("```py\n"), len(prompt))
    assert details.block_range == (0, len(prompt))


def _passthrough(x: str, **_kw: Any) -> str:
    return x


class TestPreprocessPromptCodeBlockProtection:
    """Integration tests verifying code block content bypasses processors."""

    # Late-phase processors (command sub, file refs, prettier, HTML strip)
    # are protected by the late phase's own fenced-block protection.
    # process_xprompt_references handles its own protection internally.
    @patch("sase.file_references.strip_html_comments")
    @patch("sase.file_references.format_with_prettier")
    @patch("sase.file_references.process_file_references")
    @patch("sase.file_references.process_command_substitution")
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

    def test_late_preprocessing_ignores_file_refs_after_displayed_inner_fence(
        self,
    ) -> None:
        """Agent labels inside the true outer fence are not @path references."""
        result = preprocess_prompt_late(
            _BOXED_INNER_FENCE_PROMPT,
            file_ref_mode="validate",
        )

        assert "@a9q.cdx" in result
