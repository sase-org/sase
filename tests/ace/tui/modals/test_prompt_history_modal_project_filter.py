"""Tests for prompt-history modal project filtering and scope hints."""

from __future__ import annotations

from threading import Event

import pytest
from textual.widgets import Input

from sase.ace.testing import wait_for
import sase.ace.tui.modals.prompt_history_modal as prompt_history_modal
from sase.ace.tui.modals.prompt_history_modal import PromptHistoryModal
from sase.core.prompt_history_filter_wire import PromptHistoryProjectIdentity
from sase.history.prompt_catalog import PromptHistoryPage
from sase.history.prompt_history_project_filter import PromptHistoryProjectCatalog
from tests.ace.tui.modals.prompt_history_modal_test_helpers import (
    _FakeScopeHint,
    _PromptHistoryTestApp,
    _catalog,
    _item,
    _modal_with_catalog,
    _plain,
)


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
