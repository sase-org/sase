"""Filtering, navigation, dismissal, and asynchronous preview for the finder."""

from __future__ import annotations

import asyncio
from threading import Event

import pytest
from rich.text import Text
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.existing_definition_entries import ExistingDefinitionEntry
from sase.ace.tui.modals.existing_definition_finder_modal import (
    ExistingDefinitionFinderModal,
    ExistingDefinitionPick,
    ExistingFinderBack,
)


class _ModalHost(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, modal: ExistingDefinitionFinderModal) -> None:
        super().__init__()
        self.modal = modal

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(self.modal)


def _entry(
    entry_id: str,
    name: str,
    *,
    kind: str = "macro",
    status: str = "active",
    path: str | None = None,
    shadowed_by: str | None = None,
    reason: str | None = None,
    preview: str | None = None,
    chip: str | None = None,
) -> ExistingDefinitionEntry:
    reference = f"#{name}" if kind == "macro" else f"⇥ {name}"
    return ExistingDefinitionEntry(
        entry_id=entry_id,
        kind=kind,  # type: ignore[arg-type]
        name=name,
        reference=reference,
        display_path=path or f"/defs/{name}.md",
        origin_label="built-in" if status == "read_only" else None,
        status=status,  # type: ignore[arg-type]
        shadowed_by=shadowed_by,
        shadows=None,
        reason=reason,
        precedence=0,
        preview_text=preview,
        chip=chip,
    )


def _modal(*entries: ExistingDefinitionEntry, kind: str = "macro", **kwargs: object):
    return ExistingDefinitionFinderModal(
        kind,
        entries,
        **kwargs,  # type: ignore[arg-type]
    )


def _plain(modal: ExistingDefinitionFinderModal, selector: str) -> str:
    content = modal.query_one(selector, Static).content
    if isinstance(content, Text):
        return content.plain
    if isinstance(content, Syntax):
        return content.code
    return str(content)


@pytest.mark.asyncio
async def test_filters_rows_and_updates_counter_with_input() -> None:
    modal = _modal(
        _entry("review", "review"),
        _entry("reviewer", "reviewer"),
        _entry("todo", "todo", kind="snippet", preview="template"),
    )

    async with _ModalHost(modal).run_test(size=(120, 40)) as pilot:
        query = modal.query_one("#existing-finder-query", Input)
        assert query.has_focus
        await pilot.press("r", "e", "v")
        option_list = modal.query_one("#existing-finder-list", OptionList)
        assert option_list.option_count == 2
        assert "2 / 2" in _plain(modal, "#existing-finder-counter")
        assert "review" in str(option_list.get_option_at_index(0).prompt)


@pytest.mark.asyncio
async def test_navigation_keeps_query_focused_and_enter_returns_identity() -> None:
    entries = (_entry("alpha", "alpha"), _entry("beta", "beta"))
    modal = _modal(*entries)
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]

    async with _ModalHost(modal).run_test(size=(120, 40)) as pilot:
        await pilot.press("down")
        assert modal._selected_index == 1
        assert modal.query_one("#existing-finder-query", Input).has_focus
        await pilot.press("enter")
        assert dismissed == [ExistingDefinitionPick("beta", "")]


@pytest.mark.asyncio
async def test_shift_tab_and_escape_return_back_and_cancel_results() -> None:
    entry = _entry("alpha", "alpha")
    back_modal = _modal(entry, initial_query="alp")
    back_dismissed: list[object] = []
    back_modal.dismiss = back_dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(back_modal).run_test(size=(120, 40)) as pilot:
        await pilot.press("shift+tab")
        assert back_dismissed == [ExistingFinderBack("alp")]

    cancel_modal = _modal(entry)
    cancel_dismissed: list[object] = []
    cancel_modal.dismiss = cancel_dismissed.append  # type: ignore[method-assign]
    async with _ModalHost(cancel_modal).run_test(size=(120, 40)) as pilot:
        await pilot.press("escape")
        assert cancel_dismissed == [None]


@pytest.mark.asyncio
async def test_enter_refuses_incompatible_definition_without_dismissing() -> None:
    modal = _modal(
        _entry(
            "swarm",
            "sase/review_swarm",
            status="incompatible",
            reason="macro swarms cannot be opened",
            chip="swarm",
        )
    )
    dismissed: list[object] = []
    modal.dismiss = dismissed.append  # type: ignore[method-assign]

    async with _ModalHost(modal).run_test(size=(120, 40)) as pilot:
        await pilot.press("enter")
        assert dismissed == []
        assert "Cannot open #sase/review_swarm" in _plain(
            modal, "#existing-finder-verdict"
        )


@pytest.mark.asyncio
async def test_empty_states_include_back_path() -> None:
    modal = _modal()
    async with _ModalHost(modal).run_test(size=(120, 40)):
        assert "No macros yet" in str(
            modal.query_one("#existing-finder-list", OptionList)
            .get_option_at_index(0)
            .prompt
        )
        assert "⇧tab to create one" in _plain(modal, "#existing-finder-verdict")


@pytest.mark.asyncio
async def test_preview_cache_reuses_loaded_body() -> None:
    first = _entry("alpha", "alpha")
    second = _entry("beta", "beta")
    calls: list[str] = []

    def loader(entry_id: str) -> str:
        calls.append(entry_id)
        return f"body for {entry_id}"

    modal = _modal(first, second, preview_loader=loader)
    async with _ModalHost(modal).run_test(size=(120, 40)) as pilot:
        await wait_for(
            pilot,
            lambda: _plain(modal, "#existing-finder-preview-body") == "body for alpha",
        )
        await pilot.press("down")
        await wait_for(
            pilot,
            lambda: _plain(modal, "#existing-finder-preview-body") == "body for beta",
        )
        await pilot.press("up")
        assert _plain(modal, "#existing-finder-preview-body") == "body for alpha"
        assert calls.count("alpha") == 1
        assert calls.count("beta") == 1


@pytest.mark.asyncio
async def test_stale_preview_result_does_not_replace_current_selection() -> None:
    started = Event()
    release = Event()
    first = _entry("alpha", "alpha")
    second = _entry("beta", "beta")

    def loader(entry_id: str) -> str:
        if entry_id == "alpha":
            started.set()
            release.wait(5)
        return f"body for {entry_id}"

    modal = _modal(first, second, preview_loader=loader)
    async with _ModalHost(modal).run_test(size=(120, 40)) as pilot:
        try:
            assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5), timeout=6)
            await pilot.press("down")
            await wait_for(
                pilot,
                lambda: (
                    _plain(modal, "#existing-finder-preview-body") == "body for beta"
                ),
            )
            release.set()
            await pilot.pause(0.1)
            assert _plain(modal, "#existing-finder-preview-body") == "body for beta"
        finally:
            release.set()


@pytest.mark.asyncio
async def test_snippet_preview_is_plain_text_and_path_matches_are_ranked() -> None:
    snippet = _entry(
        "snippet",
        "todo",
        kind="snippet",
        preview="{{ input }}",
        path="/docs/review-snippets.yml",
    )
    modal = _modal(snippet, kind="snippet")
    async with _ModalHost(modal).run_test(size=(120, 40)) as pilot:
        await pilot.press("d", "o", "c", "s")
        assert modal._selected_entry() == snippet
        body = modal.query_one("#existing-finder-preview-body", Static)
        assert body.render().plain == "{{ input }}"
        assert "snippet" in _plain(modal, "#existing-finder-title")
