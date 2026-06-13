"""Tests for the ACE prompt history modal."""

from __future__ import annotations

import sase.ace.tui.modals.prompt_history_modal as prompt_history_modal
from sase.ace.tui.modals.prompt_history_modal import (
    _PromptDisplayItem,
    PromptHistoryModal,
    _create_prompt_history_label,
    _ellipsize_right,
    _format_history_timestamp,
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
    )


def test_prompt_history_label_is_single_line_and_ellipsized() -> None:
    prompt = ("normalize whitespace " * 12) + "\nsecond line should stay in preview"

    label = _create_prompt_history_label(_item(text=prompt))

    assert label.no_wrap is True
    assert label.overflow == "ellipsis"
    assert "\n" not in label.plain
    assert "second line" not in label.plain
    assert _ellipsize_right("normalize whitespace " * 12, 96) in label.plain
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


def test_prompt_history_filter_matches_prompt_text_only() -> None:
    matching_item = _item(text="fix the tests", context="main")
    context_only_item = _item(text="ship the change", context="feature/tests")
    modal = object.__new__(PromptHistoryModal)
    modal._all_items = [matching_item, context_only_item]
    modal._show_cancelled = False

    assert modal._get_filtered_items("tests") == [matching_item]


def test_prompt_history_initial_filter_prefilters_items(monkeypatch) -> None:
    entries = [
        _item(text="fix auth login").entry,
        _item(text="update docs").entry,
    ]
    monkeypatch.setattr(
        prompt_history_modal,
        "get_prompts_for_fzf",
        lambda *, include_cancelled: [("", entry) for entry in entries],
    )

    modal = PromptHistoryModal(initial_filter="auth")

    assert modal._initial_filter == "auth"
    assert [item.entry.text for item in modal._filtered_items] == ["fix auth login"]
