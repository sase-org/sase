"""Tests for the unified prompt-stash panel.

Covers the pure row helpers (preview truncation, project chip, marker styling)
and the modal's selection model: ``space`` marks restore+pop, ``tab`` marks
restore+keep, ``a`` toggles all single-prompt rows for restore+pop, ``d`` marks
a row for deletion, ``enter`` confirms (the marked set, or the highlighted row
when nothing is marked), and ``esc`` cancels. The modal is presentation-only, so
confirm yields a :class:`StashRestoreResult` of ids — no store access here.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.stashed_prompts_modal import (
    StashRestoreResult,
    StashedPromptsModal,
    _first_line_preview,
    _project_chip,
    _stash_row_label,
)
from sase.core.prompt_stash_wire import PromptStashEntryWire


def _entry(
    entry_id: str,
    text: str = "draft",
    *,
    created_at: str = "2026-06-16T10:00:00",
    project: str | None = "proj",
    pane_index: int = 0,
) -> PromptStashEntryWire:
    return PromptStashEntryWire(
        id=entry_id,
        created_at=created_at,
        text=text,
        project=project,
        pane_index=pane_index,
    )


# --- pure helpers ----------------------------------------------------------


def test_first_line_preview_uses_first_nonblank_line() -> None:
    assert _first_line_preview("\n\n  hello  \nworld", 64) == "hello"


def test_first_line_preview_truncates_with_ellipsis() -> None:
    out = _first_line_preview("x" * 100, 10)
    assert out == "xxxxxxxxx…"
    assert len(out) == 10


def test_project_chip_pads_and_placeholders() -> None:
    assert _project_chip("proj") == "proj".ljust(14)
    assert _project_chip(None).strip() == "—"
    assert len(_project_chip("a-very-long-project-name")) == 14


def test_row_label_markers() -> None:
    entry = _entry("a", "hello")
    plain_pop = _stash_row_label(
        entry,
        marked_for_pop=True,
        marked_for_keep=False,
        marked_for_delete=False,
        age="2m ago",
    ).plain
    plain_keep = _stash_row_label(
        entry,
        marked_for_pop=False,
        marked_for_keep=True,
        marked_for_delete=False,
        age="2m ago",
    ).plain
    plain_deleted = _stash_row_label(
        entry,
        marked_for_pop=False,
        marked_for_keep=False,
        marked_for_delete=True,
        age="2m ago",
    ).plain
    plain_plain = _stash_row_label(
        entry,
        marked_for_pop=False,
        marked_for_keep=False,
        marked_for_delete=False,
        age="2m ago",
    ).plain
    assert plain_pop.startswith("✓")
    assert plain_keep.startswith("+")
    assert plain_deleted.startswith("✗")
    assert plain_plain.startswith("  ")
    assert "2m ago" in plain_plain and "proj" in plain_plain and "hello" in plain_plain


def test_row_label_shows_bundle_marker() -> None:
    entry = _entry("bundle", "one\n---\ntwo")
    plain = _stash_row_label(
        entry,
        marked_for_pop=False,
        marked_for_keep=False,
        marked_for_delete=False,
        age="2m ago",
        prompt_count=2,
    ).plain
    assert "2 prompts" in plain


# --- modal interaction (pilot) ---------------------------------------------


class _ModalHost(App[None]):
    """Pushes the stash panel and captures its dismiss result."""

    def __init__(self, entries: list[PromptStashEntryWire]) -> None:
        super().__init__()
        self._entries = entries
        self.result: object = "UNSET"

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(
            StashedPromptsModal(self._entries),
            lambda res: setattr(self, "result", res),
        )


async def test_newest_first_ordering() -> None:
    entries = [
        _entry("old", created_at="2026-06-16T09:00:00"),
        _entry("new", created_at="2026-06-16T11:00:00"),
        _entry("mid", created_at="2026-06-16T10:00:00"),
    ]
    app = _ModalHost(entries)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        assert [e.id for e in modal._entries] == ["new", "mid", "old"]


async def test_enter_with_no_toggle_restores_highlighted() -> None:
    app = _ModalHost([_entry("a"), _entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("enter")  # confirm highlighted (first row)
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["a"]
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_enter_with_no_toggle_restores_highlighted_bundle() -> None:
    app = _ModalHost([_entry("bundle", "one\n---\ntwo")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["bundle"]
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_space_toggles_then_enter_restores_pop_set() -> None:
    app = _ModalHost(
        [
            _entry("a", created_at="2026-06-16T12:00:00"),
            _entry("b", created_at="2026-06-16T11:00:00"),
            _entry("c", created_at="2026-06-16T10:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("space")  # toggle "a"
        await pilot.press("j")  # down to "b"
        await pilot.press("j")  # down to "c"
        await pilot.press("space")  # toggle "c"
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert set(app.result.pop_ids) == {"a", "c"}
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_space_is_inert_for_bundle_rows() -> None:
    app = _ModalHost(
        [
            _entry("bundle", "one\n---\ntwo", created_at="2026-06-16T12:00:00"),
            _entry("single", "solo", created_at="2026-06-16T11:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("space")  # highlighted bundle is not bulk-selectable
        await pilot.press("j")
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == ["single"]
    assert app.result.keep_ids == []
    assert app.result.delete_ids == []


async def test_tab_toggles_then_enter_restores_keep_set() -> None:
    app = _ModalHost(
        [
            _entry("a", created_at="2026-06-16T12:00:00"),
            _entry("b", created_at="2026-06-16T11:00:00"),
            _entry("c", created_at="2026-06-16T10:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("tab")  # keep "a"
        await pilot.press("j")
        await pilot.press("j")
        await pilot.press("tab")  # keep "c"
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert set(app.result.keep_ids) == {"a", "c"}
    assert app.result.delete_ids == []


async def test_space_and_tab_are_mutually_exclusive() -> None:
    app = _ModalHost([_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("space")
        await pilot.press("tab")
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == ["a"]
    assert app.result.delete_ids == []


async def test_toggle_all_then_enter_restores_everything() -> None:
    app = _ModalHost([_entry("a"), _entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("a")  # toggle all
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert set(app.result.pop_ids) == {"a", "b"}
    assert app.result.keep_ids == []


async def test_toggle_all_selects_only_single_prompt_rows() -> None:
    app = _ModalHost(
        [
            _entry("bundle", "one\n---\ntwo", created_at="2026-06-16T12:00:00"),
            _entry("a", "alpha", created_at="2026-06-16T11:00:00"),
            _entry("b", "beta", created_at="2026-06-16T10:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("a")
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert set(app.result.pop_ids) == {"a", "b"}
    assert "bundle" not in app.result.pop_ids


async def test_delete_mark_returns_delete_ids_not_restore() -> None:
    app = _ModalHost([_entry("a"), _entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("d")  # mark "a" for deletion
        await pilot.press("j")  # highlight "b"
        await pilot.press("enter")  # confirm only the marked deletion
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == []
    assert app.result.delete_ids == ["a"]


async def test_delete_wins_over_prior_pop_selection() -> None:
    app = _ModalHost([_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("space")  # select "a"
        await pilot.press("d")  # then mark it for deletion (clears selection)
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == []
    assert app.result.delete_ids == ["a"]


async def test_delete_wins_over_prior_keep_selection() -> None:
    app = _ModalHost([_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("tab")  # keep "a"
        await pilot.press("d")  # then mark it for deletion (clears keep)
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == []
    assert app.result.delete_ids == ["a"]


async def test_delete_mark_can_delete_bundle_row() -> None:
    app = _ModalHost([_entry("bundle", "one\n---\ntwo")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.pop_ids == []
    assert app.result.keep_ids == []
    assert app.result.delete_ids == ["bundle"]


async def test_escape_cancels_with_none() -> None:
    app = _ModalHost([_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None


async def test_title_and_hints_describe_unified_panel() -> None:
    app = _ModalHost([_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        assert modal._title_text() == "Stashed prompts (1)"
        hints = modal._hint_text()
        assert "restore+pop" in hints
        assert "restore+keep" in hints
        assert "delete" in hints
