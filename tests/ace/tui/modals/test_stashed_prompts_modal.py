"""Tests for the Phase 3 prompt-stash restore picker.

Covers the pure row helpers (preview truncation, project chip, marker styling)
and the modal's selection model: ``space`` toggles, ``a`` toggles all, ``d``
marks for deletion, ``enter`` confirms (the toggled set, or the highlighted row
when nothing is toggled), and ``esc`` cancels.  The modal is presentation-only,
so confirm yields a :class:`StashRestoreResult` of ids — no store access here.
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
    plain_selected = _stash_row_label(
        entry, selected=True, marked_for_delete=False, age="2m ago"
    ).plain
    plain_deleted = _stash_row_label(
        entry, selected=False, marked_for_delete=True, age="2m ago"
    ).plain
    plain_plain = _stash_row_label(
        entry, selected=False, marked_for_delete=False, age="2m ago"
    ).plain
    assert plain_selected.startswith("✓")
    assert plain_deleted.startswith("✗")
    assert plain_plain.startswith("  ")
    assert "2m ago" in plain_plain and "proj" in plain_plain and "hello" in plain_plain


# --- modal interaction (pilot) ---------------------------------------------


class _ModalHost(App[None]):
    """Pushes the restore picker and captures its dismiss result."""

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
    assert app.result.restore_ids == ["a"]
    assert app.result.delete_ids == []


async def test_space_toggles_then_enter_restores_selected_set() -> None:
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
    assert set(app.result.restore_ids) == {"a", "c"}
    assert app.result.delete_ids == []


async def test_toggle_all_then_enter_restores_everything() -> None:
    app = _ModalHost([_entry("a"), _entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("a")  # toggle all
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert set(app.result.restore_ids) == {"a", "b"}


async def test_delete_mark_returns_delete_ids_not_restore() -> None:
    app = _ModalHost([_entry("a"), _entry("b")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("d")  # mark "a" for deletion
        await pilot.press("j")  # highlight "b"
        await pilot.press("enter")  # confirm: restore highlighted "b", delete "a"
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.restore_ids == ["b"]
    assert app.result.delete_ids == ["a"]


async def test_delete_wins_over_prior_selection() -> None:
    app = _ModalHost([_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("space")  # select "a"
        await pilot.press("d")  # then mark it for deletion (clears selection)
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, StashRestoreResult)
    assert app.result.restore_ids == []
    assert app.result.delete_ids == ["a"]


async def test_escape_cancels_with_none() -> None:
    app = _ModalHost([_entry("a")])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app.result is None
