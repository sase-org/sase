"""Tests for fenced code block protection in preprocessing."""

from pathlib import Path
from typing import Any

import pytest

from sase.macro import _fenced_blocks
from sase.llm_provider.preprocessing import preprocess_prompt, preprocess_prompt_late
from sase.macro._fenced_blocks import (
    fenced_block_details,
    fenced_block_ranges,
    protect_fenced_blocks,
    protect_fenced_blocks_only,
    unprotect_fenced_blocks,
)

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


def test_fenced_block_details_batch_converts_unicode_offsets(
    monkeypatch: Any,
) -> None:
    calls: list[list[int]] = []
    real_convert = _fenced_blocks._byte_offsets_to_character_offsets

    def counted(text: str, offsets: Any) -> dict[int, int]:
        values = list(offsets)
        calls.append(values)
        return real_convert(text, values)

    monkeypatch.setattr(
        _fenced_blocks,
        "_byte_offsets_to_character_offsets",
        counted,
    )
    prompt = ("é before\n```python title=demo\nprint('値')\n```\nafter\n") * 25

    details = fenced_block_details(prompt)

    assert len(details) == 25
    assert len(calls) == 1
    assert len(calls[0]) <= len(details) * 10
    assert all(prompt[slice(*detail.opening_fence)] == "```" for detail in details)


class TestPreprocessPromptCodeBlockProtection:
    """Integration tests verifying code block content bypasses processors."""

    def test_text_outside_code_blocks_still_processed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Commands outside fences execute at the source boundary; fenced ones stay literal.

        Phase sase-1tc.1.1.2 moved command substitution from the late phase
        to the early source boundary, so this previously mock-based test now
        drives the real boundary with marker files: outside-fence commands
        execute exactly once while fenced content is never planned.
        """
        monkeypatch.chdir(tmp_path)
        prompt = (
            "outside $(touch outside-marker)\n"
            "```\n"
            "$(touch inside-marker)\n"
            "```\n"
            "more $(touch more-marker)"
        )
        result = preprocess_prompt(prompt, agent_authored=False)

        assert (tmp_path / "outside-marker").exists()
        assert (tmp_path / "more-marker").exists()
        assert not (tmp_path / "inside-marker").exists()
        assert "$(touch outside-marker)" not in result.prompt
        assert "$(touch more-marker)" not in result.prompt
        assert "$(touch inside-marker)" in result.prompt

    def test_late_preprocessing_ignores_file_refs_after_displayed_inner_fence(
        self,
    ) -> None:
        """Agent labels inside the true outer fence are not @path references."""
        result = preprocess_prompt_late(
            _BOXED_INNER_FENCE_PROMPT,
            file_ref_mode="validate",
        )

        assert "@a9q.cdx" in result
