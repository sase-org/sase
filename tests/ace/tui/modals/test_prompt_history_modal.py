"""Tests for the ACE prompt history modal."""

from __future__ import annotations

import asyncio
import inspect
from threading import Event

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Input

from sase.ace.testing import wait_for
import sase.ace.tui.modals.prompt_history_modal as prompt_history_modal
import sase.history.prompt_metadata as prompt_metadata
import sase.xprompt._parsing as xprompt_parsing
from sase.ace.tui.modals.prompt_history_modal import (
    _MIN_PREVIEW_WIDTH,
    _OPTION_HORIZONTAL_PADDING_WIDTH,
    _PROMPT_COL_START,
    _PromptDisplayItem,
    PromptHistoryModal,
    _create_prompt_history_label,
    _ellipsize_right,
    _format_history_timestamp,
    _prompt_history_header_text,
    _prompt_preview_width_for_list_content,
)
from sase.history.prompt_catalog import PromptHistoryPage, record_from_entry
from sase.history.prompt_store import PromptEntry
from sase.history.prompt_metadata import PromptListSummary


class _PromptHistoryTestApp(App[None]):
    """Minimal app harness for prompt-history modal pilot tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def test_prompt_history_mount_handler_is_synchronous() -> None:
    assert not inspect.iscoroutinefunction(PromptHistoryModal.on_mount)


async def test_prompt_history_opens_while_initial_disk_load_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()

    def slow_load_prompt_record_page(**_kwargs: object) -> PromptHistoryPage:
        started.set()
        release.wait()
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    monkeypatch.setattr(
        prompt_history_modal,
        "load_prompt_record_page",
        slow_load_prompt_record_page,
    )
    modal = PromptHistoryModal()

    async with _PromptHistoryTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        try:
            assert await asyncio.wait_for(
                asyncio.to_thread(started.wait, 10.0), timeout=11.0
            )
            filter_input = modal.query_one("#prompt-history-filter-input", Input)
            assert filter_input.has_focus
            await pilot.press("a")
            assert filter_input.value == "a"
            assert not modal._history_loaded_once
        finally:
            release.set()
            await wait_for(pilot, lambda: modal._history_loaded_once)
            assert modal._history_loaded_once


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


def test_prompt_history_filter_matches_prompt_text_only() -> None:
    matching_item = _item(text="fix the tests", context="main")
    context_only_item = _item(text="ship the change", context="feature/tests")
    modal = object.__new__(PromptHistoryModal)
    modal._all_items = [matching_item, context_only_item]
    modal._show_cancelled = False

    assert modal._get_filtered_items("tests") == [matching_item]


def test_prompt_history_filter_matches_display_and_canonical_text() -> None:
    item = _item(text="#gh:gh_acme__widgets Fix parser")
    item.display_text = "#gh:widgets Fix parser"
    modal = object.__new__(PromptHistoryModal)
    modal._all_items = [item]
    modal._show_cancelled = False

    assert modal._get_filtered_items("widgets") == [item]
    assert modal._get_filtered_items("gh_acme__widgets") == [item]


def test_prompt_history_selected_prompt_uses_display_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeOptionList:
        highlighted = 0

    item = _item(text="#gh:gh_acme__widgets Fix parser")
    item.display_text = "#gh:widgets Fix parser"
    modal = object.__new__(PromptHistoryModal)
    modal._filtered_items = [item]
    monkeypatch.setattr(
        modal,
        "query_one",
        lambda _selector, _widget_type: FakeOptionList(),
    )

    assert modal._get_selected_prompt_text() == "#gh:widgets Fix parser"


def test_prompt_history_initial_filter_prefilters_items(monkeypatch) -> None:
    entries = [
        _item(text="fix auth login").entry,
        _item(text="update docs").entry,
    ]

    modal = PromptHistoryModal(initial_filter="auth")
    modal._append_page(
        PromptHistoryPage(
            records=[record_from_entry(entry) for entry in entries],
            next_cursor=None,
            exhausted=True,
        )
    )
    modal._filtered_items = modal._get_filtered_items(modal._initial_filter)

    assert modal._initial_filter == "auth"
    assert [item.entry.text for item in modal._filtered_items] == ["fix auth login"]


def test_prompt_history_append_page_keeps_canonical_entry_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "#gh:gh_acme__widgets Fix parser"
    monkeypatch.setattr(
        prompt_history_modal,
        "humanize_vcs_refs_in_text",
        lambda text: text.replace("gh_acme__widgets", "widgets"),
    )
    modal = PromptHistoryModal()

    modal._append_page(
        PromptHistoryPage(
            records=[record_from_entry(_item(text=raw).entry)],
            next_cursor=None,
            exhausted=True,
        )
    )

    assert modal._all_items[0].entry.text == raw
    assert modal._all_items[0].display_text == "#gh:widgets Fix parser"


def test_prompt_history_count_label_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLabel:
        def __init__(self) -> None:
            self.value = ""

        def update(self, value: str) -> None:
            self.value = value

    label = FakeLabel()
    modal = object.__new__(PromptHistoryModal)
    modal._all_items = [
        _item(text="fix auth"),
        _item(text="update docs"),
        _item(text="cancelled", cancelled=True),
    ]
    modal._filtered_items = [modal._all_items[0]]
    modal._history_loaded_once = True
    modal._history_loading = False
    modal._history_exhausted = True

    monkeypatch.setattr(
        modal,
        "query_one",
        lambda _selector, _widget_type: label,
    )

    modal._update_history_count_label()

    assert label.value == "History · 1 / 3 total"

    modal._history_exhausted = False
    modal._update_history_count_label()

    assert label.value == "History · 1 / 3 loaded · ^k +250 older"


def test_prompt_history_load_more_bound_to_ctrl_k_not_ctrl_d() -> None:
    key_action_pairs = [
        (binding[0], binding[1])
        if isinstance(binding, tuple)
        else (binding.key, binding.action)
        for binding in PromptHistoryModal.BINDINGS
    ]

    assert ("ctrl+k", "load_more") in key_action_pairs
    assert all(key != "ctrl+d" for key, _ in key_action_pairs)


async def test_ctrl_k_loads_more_without_deleting_filter_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_cursor = prompt_history_modal.PromptHistoryPageCursor(offset=1)
    pages = [
        PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha first loaded prompt").entry,
                )
            ],
            next_cursor=first_cursor,
            exhausted=False,
        ),
        PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha second older prompt").entry,
                )
            ],
            next_cursor=None,
            exhausted=True,
        ),
    ]
    calls: list[dict[str, object]] = []

    def fake_load_prompt_record_page(**kwargs: object) -> PromptHistoryPage:
        calls.append(kwargs)
        if pages:
            return pages.pop(0)
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    monkeypatch.setattr(
        prompt_history_modal,
        "load_prompt_record_page",
        fake_load_prompt_record_page,
    )

    modal = PromptHistoryModal(initial_filter="alpha")
    async with _PromptHistoryTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await wait_for(
            pilot, lambda: len(modal._all_items) == 1 and not modal._history_loading
        )

        filter_input = modal.query_one("#prompt-history-filter-input", Input)
        assert filter_input.has_focus
        assert filter_input.value == "alpha"

        filter_input.cursor_position = 0
        await pilot.press("ctrl+k")
        await wait_for(
            pilot, lambda: len(modal._all_items) == 2 and not modal._history_loading
        )

        assert filter_input.value == "alpha"
        assert [item.entry.text for item in modal._all_items] == [
            "alpha first loaded prompt",
            "alpha second older prompt",
        ]
        assert calls[1]["cursor"] == first_cursor


async def test_ctrl_d_no_longer_loads_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_cursor = prompt_history_modal.PromptHistoryPageCursor(offset=1)
    pages = [
        PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha first loaded prompt").entry,
                )
            ],
            next_cursor=first_cursor,
            exhausted=False,
        ),
        PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha second older prompt").entry,
                )
            ],
            next_cursor=None,
            exhausted=True,
        ),
    ]

    def fake_load_prompt_record_page(**kwargs: object) -> PromptHistoryPage:
        if pages:
            return pages.pop(0)
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    monkeypatch.setattr(
        prompt_history_modal,
        "load_prompt_record_page",
        fake_load_prompt_record_page,
    )

    modal = PromptHistoryModal(initial_filter="alpha")
    async with _PromptHistoryTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await wait_for(
            pilot, lambda: len(modal._all_items) == 1 and not modal._history_loading
        )

        await pilot.press("ctrl+d")
        for _ in range(20):
            await pilot.pause(0.01)

        assert [item.entry.text for item in modal._all_items] == [
            "alpha first loaded prompt",
        ]


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
