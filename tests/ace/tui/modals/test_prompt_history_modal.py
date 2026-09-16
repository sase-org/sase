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
from sase.core.prompt_history_filter_wire import PromptHistoryProjectIdentity
from sase.history.prompt_catalog import PromptHistoryPage, record_from_entry
from sase.history.prompt_history_project_filter import (
    PromptHistoryProjectCatalog,
    prepare_prompt_history_row_facts,
)
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
    prompt_metadata.known_workflow_names.cache_clear()
    xprompt_parsing._VCS_TAG_PATTERN = None
    xprompt_parsing._VCS_TAG_EMBEDDED_PATTERN = None
    yield
    prompt_metadata.known_workflow_names.cache_clear()
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

    assert label.value == "History · 1 / 3 loaded · ^j +100 older"


def test_prompt_history_paging_bound_to_ctrl_j_and_ctrl_k() -> None:
    key_action_pairs = [
        (binding[0], binding[1])
        if isinstance(binding, tuple)
        else (binding.key, binding.action)
        for binding in PromptHistoryModal.BINDINGS
    ]

    assert ("ctrl+j", "load_more") in key_action_pairs
    assert ("ctrl+k", "unload") in key_action_pairs
    assert all(key != "ctrl+d" for key, _ in key_action_pairs)


async def test_ctrl_j_loads_more_without_deleting_filter_text(
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
        await pilot.press("ctrl+j")
        await wait_for(
            pilot, lambda: len(modal._all_items) == 2 and not modal._history_loading
        )

        assert filter_input.value == "alpha"
        assert [item.entry.text for item in modal._all_items] == [
            "alpha first loaded prompt",
            "alpha second older prompt",
        ]
        assert calls[1]["cursor"] == first_cursor
        assert calls[0]["page_size"] == modal._page_size


async def test_ctrl_k_unloads_last_page_and_next_load_refetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_cursor = prompt_history_modal.PromptHistoryPageCursor(offset=1)
    pages_by_cursor = {
        None: PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha first loaded prompt").entry,
                )
            ],
            next_cursor=first_cursor,
            exhausted=False,
        ),
        first_cursor: PromptHistoryPage(
            records=[
                record_from_entry(
                    _item(text="alpha second older prompt").entry,
                )
            ],
            next_cursor=None,
            exhausted=True,
        ),
    }
    calls: list[dict[str, object]] = []

    def fake_load_prompt_record_page(**kwargs: object) -> PromptHistoryPage:
        calls.append(kwargs)
        cursor = kwargs.get("cursor")
        return pages_by_cursor.get(
            cursor,  # type: ignore[arg-type]
            PromptHistoryPage(records=[], next_cursor=None, exhausted=True),
        )

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

        await pilot.press("ctrl+k")
        await pilot.pause()
        assert len(modal._all_items) == 1
        assert len(calls) == 1

        await pilot.press("ctrl+j")
        await wait_for(
            pilot, lambda: len(modal._all_items) == 2 and not modal._history_loading
        )
        assert [item.entry.text for item in modal._all_items] == [
            "alpha first loaded prompt",
            "alpha second older prompt",
        ]

        await pilot.press("ctrl+k")
        await wait_for(pilot, lambda: len(modal._all_items) == 1)
        assert [item.entry.text for item in modal._all_items] == [
            "alpha first loaded prompt",
        ]
        assert modal._history_exhausted is False
        assert modal._next_cursor == first_cursor

        await pilot.press("ctrl+j")
        await wait_for(
            pilot, lambda: len(modal._all_items) == 2 and not modal._history_loading
        )
        assert calls[2]["cursor"] == first_cursor
        assert [item.entry.text for item in modal._all_items] == [
            "alpha first loaded prompt",
            "alpha second older prompt",
        ]


async def test_prompt_history_uses_configured_page_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prompt_history_modal, "get_ace_page_size", lambda: 25)
    calls: list[dict[str, object]] = []

    def fake_load_prompt_record_page(**kwargs: object) -> PromptHistoryPage:
        calls.append(kwargs)
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    monkeypatch.setattr(
        prompt_history_modal,
        "load_prompt_record_page",
        fake_load_prompt_record_page,
    )

    modal = PromptHistoryModal()
    async with _PromptHistoryTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._history_loaded_once)

    assert modal._page_size == 25
    assert calls[0]["page_size"] == 25
    assert "^j/+25" in modal._hints_text()
    assert "^k/-25" in modal._hints_text()


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
    page_loads = 0

    def fake_load_prompt_record_page(**kwargs: object) -> PromptHistoryPage:
        nonlocal page_loads
        page_loads += 1
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
        await pilot.pause()

        assert page_loads == 1
        assert not modal._history_loading
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


def _catalog(*entries: PromptHistoryProjectIdentity) -> PromptHistoryProjectCatalog:
    return PromptHistoryProjectCatalog(entries=tuple(entries))


def _modal_with_catalog(
    catalog: PromptHistoryProjectCatalog,
    items: list[_PromptDisplayItem],
    *,
    show_cancelled: bool = False,
) -> PromptHistoryModal:
    modal = object.__new__(PromptHistoryModal)
    modal._catalog = catalog
    modal._all_items = items
    modal._show_cancelled = show_cancelled
    modal._row_facts = [
        prepare_prompt_history_row_facts(
            index, item.entry.text, _display_text_for_item(item), catalog
        )
        for index, item in enumerate(items)
    ]
    return modal


def _display_text_for_item(item: _PromptDisplayItem) -> str:
    return item.display_text if item.display_text is not None else item.entry.text


def test_project_filter_matches_complete_identity_not_prefix_or_prose() -> None:
    sase_item = _item(text="#gh:sase fix parser")
    core_item = _item(text="#gh:sase-core fix parser")
    prose_item = _item(text="mentions sase-core in prose")
    modal = _modal_with_catalog(
        _catalog(
            PromptHistoryProjectIdentity(key="sase"),
            PromptHistoryProjectIdentity(key="sase-core"),
        ),
        [sase_item, core_item, prose_item],
    )

    assert modal._get_filtered_items("project:sase") == [sase_item]


def test_project_and_text_filter_combine_with_and() -> None:
    matches = _item(text="#gh:sase fix parser")
    project_only = _item(text="#gh:sase update docs")
    text_only = _item(text="#gh:other-project fix parser")
    modal = _modal_with_catalog(
        _catalog(
            PromptHistoryProjectIdentity(key="sase"),
            PromptHistoryProjectIdentity(key="other-project"),
        ),
        [matches, project_only, text_only],
    )

    assert modal._get_filtered_items("project:sase fix parser") == [matches]


def test_alias_equivalent_rows_match_by_canonical_key() -> None:
    canonical_item = _item(text="#gh:gh_sase-org__sase fix parser")
    display_item = _item(text="#gh:sase fix parser")
    modal = _modal_with_catalog(
        _catalog(
            PromptHistoryProjectIdentity(
                key="gh_sase-org__sase",
                label="sase",
                raw_refs=["sase-org/sase"],
            )
        ),
        [canonical_item, display_item],
    )

    assert modal._get_filtered_items("project:sase") == [
        canonical_item,
        display_item,
    ]
    assert modal._get_filtered_items("project:gh_sase-org__sase") == [
        canonical_item,
        display_item,
    ]
    assert modal._get_filtered_items("project:sase-org/sase") == [
        canonical_item,
        display_item,
    ]


def test_ambiguous_project_label_disables_selection_and_reports_diagnostic() -> None:
    item_a = _item(text="#gh:widget-a fix")
    item_b = _item(text="#gh:widget-b fix")
    modal = _modal_with_catalog(
        _catalog(
            PromptHistoryProjectIdentity(key="widget-a", label="widgets"),
            PromptHistoryProjectIdentity(key="widget-b", label="widgets"),
        ),
        [item_a, item_b],
    )

    assert modal._get_filtered_items("project:widgets") == []
    assert modal._last_compiled_query is not None
    assert modal._last_compiled_query.diagnostic is not None


def test_malformed_project_qualifier_disables_selection() -> None:
    modal = _modal_with_catalog(
        _catalog(PromptHistoryProjectIdentity(key="sase")),
        [_item(text="#gh:sase fix parser")],
    )

    for query in ["project:", 'project:"unterminated']:
        assert modal._get_filtered_items(query) == []
        assert modal._last_compiled_query is not None
        assert modal._last_compiled_query.valid is False


def test_unresolved_project_value_matches_raw_historical_ref() -> None:
    deleted_ref_item = _item(text="#gh:deleted-project fix parser")
    other_item = _item(text="#gh:sase fix parser")
    modal = _modal_with_catalog(
        _catalog(PromptHistoryProjectIdentity(key="sase")),
        [deleted_ref_item, other_item],
    )

    assert modal._get_filtered_items("project:deleted-project") == [deleted_ref_item]


def test_unknown_project_value_is_ordinary_empty_not_an_error() -> None:
    modal = _modal_with_catalog(
        _catalog(PromptHistoryProjectIdentity(key="sase")),
        [_item(text="#gh:sase fix parser")],
    )

    assert modal._get_filtered_items("project:totally-unregistered") == []
    assert modal._last_compiled_query is not None
    assert modal._last_compiled_query.diagnostic is None


def test_legacy_record_with_no_active_ref_stays_unscoped() -> None:
    item = _item(text="fix parser without any tag")
    modal = _modal_with_catalog(
        _catalog(PromptHistoryProjectIdentity(key="sase")),
        [item],
    )

    assert modal._get_filtered_items("fix parser") == [item]


def test_clearing_project_filter_restores_full_results() -> None:
    scoped_item = _item(text="#gh:sase fix parser")
    other_item = _item(text="#gh:other update docs")
    modal = _modal_with_catalog(
        _catalog(
            PromptHistoryProjectIdentity(key="sase"),
            PromptHistoryProjectIdentity(key="other"),
        ),
        [scoped_item, other_item],
    )

    assert modal._get_filtered_items("project:sase") == [scoped_item]
    assert modal._get_filtered_items("") == [scoped_item, other_item]


class _FakeScopeHint:
    """Fake ``Static`` recording updates/class toggles for hint assertions."""

    def __init__(self) -> None:
        self.value: object = None
        self.added: list[str] = []
        self.removed: list[str] = []

    def update(self, value: object) -> None:
        self.value = value

    def add_class(self, name: str) -> None:
        self.added.append(name)

    def remove_class(self, name: str) -> None:
        self.removed.append(name)


def _plain(value: object) -> str:
    return value.plain if hasattr(value, "plain") else str(value)


def test_scope_hint_shows_project_label_when_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hint = _FakeScopeHint()
    modal = object.__new__(PromptHistoryModal)
    catalog = _catalog(PromptHistoryProjectIdentity(key="sase", label="sase"))
    modal._last_compiled_query = catalog.compile_query("project:sase fix")
    modal._seed_hint_text = None
    modal._seed_applied_value = None
    monkeypatch.setattr(
        modal,
        "query_one",
        lambda selector, _cls=None: (
            hint
            if selector == "#prompt-history-scope-hint"
            else (_ for _ in ()).throw(LookupError)
        ),
    )

    modal._update_scope_hint()

    assert "Project: sase" in _plain(hint.value)
    assert "-scoped" in hint.added


def test_scope_hint_shows_diagnostic_for_malformed_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hint = _FakeScopeHint()
    modal = object.__new__(PromptHistoryModal)
    catalog = _catalog()
    modal._last_compiled_query = catalog.compile_query("project:")
    modal._seed_hint_text = None
    modal._seed_applied_value = None
    monkeypatch.setattr(
        modal,
        "query_one",
        lambda selector, _cls=None: (
            hint
            if selector == "#prompt-history-scope-hint"
            else (_ for _ in ()).throw(LookupError)
        ),
    )

    modal._update_scope_hint()

    assert "-error" in hint.added
    assert "project:" in _plain(hint.value)


def test_scope_hint_shows_seed_hint_until_user_edits_away(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hint = _FakeScopeHint()

    class _FakeFilterInput:
        value = "fix parser"

    filter_input = _FakeFilterInput()
    modal = object.__new__(PromptHistoryModal)
    catalog = _catalog()
    modal._last_compiled_query = catalog.compile_query("fix parser")
    modal._seed_hint_text = "Project scope unavailable; searching all loaded prompts"
    modal._seed_applied_value = "fix parser"

    def fake_query_one(selector: str, _cls: object = None) -> object:
        if selector == "#prompt-history-scope-hint":
            return hint
        if selector == "#prompt-history-filter-input":
            return filter_input
        raise LookupError(selector)

    monkeypatch.setattr(modal, "query_one", fake_query_one)

    modal._update_scope_hint()
    assert "Project scope unavailable" in _plain(hint.value)

    filter_input.value = "fix parser more"
    modal._update_scope_hint()
    assert "Type project:" in _plain(hint.value)


async def test_typing_during_seed_resolution_wins_over_the_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = Event()

    def slow_build_seed(
        _draft: str, _catalog: PromptHistoryProjectCatalog
    ) -> prompt_history_modal.PromptHistorySeed:
        release.wait(10.0)
        return prompt_history_modal.PromptHistorySeed(
            seed_text="project:sase fix parser", hint=None
        )

    monkeypatch.setattr(
        prompt_history_modal.PromptHistoryProjectCatalog,
        "load",
        classmethod(lambda cls: cls(entries=())),
    )
    monkeypatch.setattr(
        prompt_history_modal,
        "build_prompt_history_seed_from_draft",
        slow_build_seed,
    )
    monkeypatch.setattr(
        prompt_history_modal,
        "load_prompt_record_page",
        lambda **_kwargs: PromptHistoryPage(
            records=[], next_cursor=None, exhausted=True
        ),
    )

    modal = PromptHistoryModal(prompt_seed="#gh:sase fix parser")
    async with _PromptHistoryTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        filter_input = modal.query_one("#prompt-history-filter-input", Input)
        await wait_for(pilot, lambda: filter_input.has_focus)

        await pilot.press("x")
        assert filter_input.value == "x"

        release.set()
        await wait_for(pilot, lambda: modal._history_loaded_once)

        assert filter_input.value == "x"
