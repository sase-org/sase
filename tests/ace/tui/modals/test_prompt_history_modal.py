"""Tests for the ACE prompt history modal."""

from __future__ import annotations

import pytest

import sase.ace.tui.modals.prompt_history_modal as prompt_history_modal
import sase.history.prompt_metadata as prompt_metadata
import sase.xprompt._parsing as xprompt_parsing
from sase.ace.tui.modals.prompt_history_modal import (
    _PromptDisplayItem,
    PromptHistoryModal,
    _create_prompt_history_label,
    _ellipsize_right,
    _format_history_timestamp,
)
from sase.history.prompt import PromptEntry
from sase.history.prompt_metadata import PromptListSummary


@pytest.fixture
def workflow_names(monkeypatch: pytest.MonkeyPatch):
    names = {"cd", "git"}
    monkeypatch.setattr(
        "sase.workspace_provider.get_workflow_names",
        lambda: names,
    )
    monkeypatch.setattr(
        "sase.workspace_provider._registry.get_workflow_names",
        lambda: names,
    )
    prompt_metadata._workflow_names.cache_clear()
    xprompt_parsing._VCS_TAG_PATTERN = None
    xprompt_parsing._VCS_TAG_EMBEDDED_PATTERN = None
    yield
    prompt_metadata._workflow_names.cache_clear()
    xprompt_parsing._VCS_TAG_PATTERN = None
    xprompt_parsing._VCS_TAG_EMBEDDED_PATTERN = None


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


def test_prompt_history_label_renders_project_tags_and_clean_preview(
    workflow_names: None,
) -> None:
    label = _create_prompt_history_label(
        _item(
            text="#gh:steveyegge/beads #fork %plan Fix the parser",
        )
    )

    assert "gh:beads" in label.plain
    assert "#fork" in label.plain
    assert "%p" in label.plain
    assert "Fix the parser" in label.plain
    assert "steveyegge/" not in label.plain
    assert "#gh:steveyegge/beads" not in label.plain
    assert "%plan" not in label.plain
    assert any("cyan" in str(span.style) for span in label.spans)
    assert any("green" in str(span.style) for span in label.spans)
    assert any("yellow" in str(span.style) for span in label.spans)


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


def test_prompt_history_label_caches_list_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_summary(text: str) -> PromptListSummary:
        nonlocal calls
        calls += 1
        return PromptListSummary(
            project_prefix="",
            project_ref_display="",
            xprompts=(),
            directive_token="",
            clean_preview=text,
        )

    monkeypatch.setattr(prompt_history_modal, "summarize_prompt_for_list", fake_summary)
    item = _item(text="cached preview")

    assert "cached preview" in _create_prompt_history_label(item).plain
    assert "cached preview" in _create_prompt_history_label(item).plain
    assert calls == 1


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


def test_prompt_history_preview_metadata_includes_prompt_metadata(
    workflow_names: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeStatic:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: object) -> None:
            self.value = value

    preview = FakeStatic()
    metadata = FakeStatic()
    modal = object.__new__(PromptHistoryModal)

    def fake_query_one(selector: str, _widget_type: object) -> FakeStatic:
        if selector == "#prompt-history-preview":
            return preview
        return metadata

    monkeypatch.setattr(modal, "query_one", fake_query_one)

    modal._update_preview(
        _item(
            text="%plan #gh:steveyegge/beads #fork(prev) Fix parser",
        )
    )

    assert preview.value == "%plan #gh:steveyegge/beads #fork(prev) Fix parser"
    assert "Project:    #gh:steveyegge/beads" in metadata.value.plain
    assert "Workflows:  #fork(prev)" in metadata.value.plain
    assert "Directives: %plan" in metadata.value.plain
    assert "Created:    260501_140000" in metadata.value.plain
    assert "Last Used:  260501_142530" in metadata.value.plain
