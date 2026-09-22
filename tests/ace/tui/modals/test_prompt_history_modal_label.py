"""Tests for prompt-history modal label rendering and preview content."""

from __future__ import annotations

import pytest

import sase.history.prompt_metadata as prompt_metadata
import sase.xprompt._parsing as xprompt_parsing
import sase.ace.tui.modals.prompt_history_modal as prompt_history_modal
from sase.ace.tui.modals.prompt_history_modal import (
    _MIN_PREVIEW_WIDTH,
    _OPTION_HORIZONTAL_PADDING_WIDTH,
    _PROMPT_COL_START,
    PromptHistoryModal,
    _create_prompt_history_label,
    _ellipsize_right,
    _format_history_timestamp,
    _prompt_history_header_text,
    _prompt_preview_width_for_list_content,
)
from sase.history.prompt_metadata import PromptListSummary
from tests.ace.tui.modals.prompt_history_modal_test_helpers import _item


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
    prompt_metadata.known_workflow_names.cache_clear()
    xprompt_parsing._VCS_TAG_PATTERN = None
    xprompt_parsing._VCS_TAG_EMBEDDED_PATTERN = None
    yield
    prompt_metadata.known_workflow_names.cache_clear()
    xprompt_parsing._VCS_TAG_PATTERN = None
    xprompt_parsing._VCS_TAG_EMBEDDED_PATTERN = None


def test_prompt_history_label_is_single_line_and_ellipsized() -> None:
    prompt = ("normalize whitespace " * 12) + "\nsecond line should stay in preview"
    preview_width = 112

    label = _create_prompt_history_label(
        _item(text=prompt),
        preview_width=preview_width,
    )

    assert label.no_wrap is True
    assert label.overflow == "ellipsis"
    assert "\n" not in label.plain
    assert "second line" not in label.plain
    assert _ellipsize_right("normalize whitespace " * 12, preview_width) in label.plain
    assert "..." in label.plain


def test_prompt_history_label_renders_project_tags_and_clean_preview(
    workflow_names: None,
) -> None:
    label = _create_prompt_history_label(
        _item(
            text="#gh:steveyegge/beads #fork %id Fix the parser",
        )
    )

    assert "gh:beads" in label.plain
    assert "#fork" in label.plain
    assert "%i" in label.plain
    assert "Fix the parser" in label.plain
    assert "steveyegge/" not in label.plain
    assert "#gh:steveyegge/beads" not in label.plain
    assert "%id" not in label.plain
    assert any("cyan" in str(span.style) for span in label.spans)
    assert any("green" in str(span.style) for span in label.spans)
    assert any("yellow" in str(span.style) for span in label.spans)


def test_prompt_history_label_summarizes_humanized_display_text(
    workflow_names: None,
) -> None:
    item = _item(text="#gh:gh_acme__widgets Fix the parser")
    item.display_text = "#gh:widgets Fix the parser"

    label = _create_prompt_history_label(item)

    assert "gh:widgets" in label.plain
    assert "gh_acme__widgets" not in label.plain


def test_prompt_history_label_uses_fixed_grid_for_prompt_column(
    workflow_names: None,
) -> None:
    without_tags = _create_prompt_history_label(
        _item(text="Plain prompt without control tokens"),
    )
    with_tags = _create_prompt_history_label(
        _item(text="#gh:steveyegge/beads #fork %id Tagged prompt"),
    )

    assert without_tags.plain.index("Plain prompt") == _PROMPT_COL_START
    assert with_tags.plain.index("Tagged prompt") == _PROMPT_COL_START


def test_prompt_history_header_matches_row_grid() -> None:
    header = _prompt_history_header_text()

    assert "WHEN" in header.plain
    assert "PROJECT" in header.plain
    assert "TAGS" in header.plain
    assert header.plain.index("PROMPT") == _PROMPT_COL_START


def test_prompt_history_preview_width_adapts_to_list_content_width() -> None:
    wide_prompt_width = 140
    wide_content_width = (
        _PROMPT_COL_START + _OPTION_HORIZONTAL_PADDING_WIDTH + wide_prompt_width
    )

    assert _prompt_preview_width_for_list_content(wide_content_width) == 140
    assert _prompt_preview_width_for_list_content(1) == _MIN_PREVIEW_WIDTH


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
            text="%model:opus #gh:steveyegge/beads #fork(prev) Fix parser",
        )
    )

    assert preview.value == "%model:opus #gh:steveyegge/beads #fork(prev) Fix parser"
    assert "Project:    #gh:steveyegge/beads" in metadata.value.plain
    assert "Workflows:  #fork(prev)" in metadata.value.plain
    assert "Directives: %model:opus" in metadata.value.plain
    assert "Created:    260501_140000" in metadata.value.plain
    assert "Last Used:  260501_142530" in metadata.value.plain


def test_prompt_history_preview_uses_display_text(
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
    item = _item(text="#gh:gh_acme__widgets Fix parser")
    item.display_text = "#gh:widgets Fix parser"

    def fake_query_one(selector: str, _widget_type: object) -> FakeStatic:
        if selector == "#prompt-history-preview":
            return preview
        return metadata

    monkeypatch.setattr(modal, "query_one", fake_query_one)

    modal._update_preview(item)

    assert preview.value == "#gh:widgets Fix parser"
    assert "Project:    #gh:widgets" in metadata.value.plain
    assert "gh_acme__widgets" not in metadata.value.plain
