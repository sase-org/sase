"""Tests for the ACE prompt history modal."""

from __future__ import annotations

from sase.ace.tui.modals.prompt_history_modal import (
    _CONTEXT_WIDTH,
    _create_prompt_history_label,
    _ellipsize_right,
    _format_history_timestamp,
    _PromptDisplayItem,
)
from sase.history.prompt import PromptEntry


def _item(
    *,
    text: str = "fix the tests",
    context: str = "main",
    marker: str = " ",
    last_used: str = "260501_142530",
    cancelled: bool = False,
) -> _PromptDisplayItem:
    return _PromptDisplayItem(
        entry=PromptEntry(
            text=text,
            branch_or_workspace=context,
            timestamp="260501_140000",
            last_used=last_used,
            workspace="sase",
            cancelled=cancelled,
        ),
        marker=marker,
        display_context=context,
    )


def test_prompt_history_label_is_single_line_and_ellipsized() -> None:
    context = "feature/" + "very-long-branch-name-" * 4
    prompt = ("normalize whitespace " * 12) + "\nsecond line should stay in preview"

    label = _create_prompt_history_label(_item(text=prompt, context=context))

    assert label.no_wrap is True
    assert label.overflow == "ellipsis"
    assert "\n" not in label.plain
    assert "second line" not in label.plain
    assert _ellipsize_right(context, _CONTEXT_WIDTH) in label.plain
    assert "..." in label.plain


def test_format_history_timestamp_uses_compact_datetime() -> None:
    assert _format_history_timestamp("260501_142530") == "05-01 14:25"


def test_format_history_timestamp_falls_back_to_fixed_width_raw_text() -> None:
    assert _format_history_timestamp("not-a-valid-time") == "not-a-valid"
    assert _format_history_timestamp("bad") == "bad        "


def test_cancelled_prompt_history_label_is_marked_and_dimmed() -> None:
    label = _create_prompt_history_label(_item(cancelled=True))

    assert label.plain.startswith("x ")
    assert any(str(span.style) == "magenta" for span in label.spans)
    assert any("dim italic" in str(span.style) for span in label.spans)
