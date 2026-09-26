"""Tests for the Trash pane: ordering, restore/purge flow, and repaint."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.prompts_modal import (
    PromptsModal,
    PromptsOrigin,
    PromptsResult,
    PromptsTab,
)
from sase.ace.tui.modals.prompt_stash_row import trash_row_label
from sase.ace.tui.modals.trash_pane import (
    PurgeRequested,
    TrashActionResult,
    TrashCopyRequested,
    TrashPane,
    TrashRestoreRequested,
    purge_confirm_text,
    sort_trash_records,
    trash_empty_text,
)
from sase.core.prompt_stash_wire import PromptStashTrashRecordWire
from tests.ace.tui.modals.stashed_prompts_modal_test_helpers import make_entry


def make_record(
    entry_id: str,
    text: str = "draft",
    *,
    trashed_at: str = "2026-06-16T12:00:00",
    **kwargs: object,
) -> PromptStashTrashRecordWire:
    return PromptStashTrashRecordWire(
        trashed_at=trashed_at,
        entry=make_entry(entry_id, text=text, **kwargs),
    )


class TrashOverlayHost(App[None]):
    """Push the Prompts overlay on Trash and capture requests + result."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        trash: list | None = None,
        *,
        trash_limit: int = 20,
    ) -> None:
        super().__init__()
        self._trash = list(trash) if trash is not None else []
        self._trash_limit = trash_limit
        self.result: object = "UNSET"
        self.restore_events: list[TrashRestoreRequested] = []
        self.purge_events: list[PurgeRequested] = []
        self.copy_events: list[TrashCopyRequested] = []

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(
            PromptsModal(
                [],
                origin=PromptsOrigin(),
                initial_tab=PromptsTab.TRASH,
                trash=self._trash,
                trash_limit=self._trash_limit,
            ),
            lambda result: setattr(self, "result", result),
        )

    def on_trash_pane_trash_restore_requested(
        self, event: TrashRestoreRequested
    ) -> None:
        self.restore_events.append(event)

    def on_trash_pane_purge_requested(self, event: PurgeRequested) -> None:
        self.purge_events.append(event)

    def on_trash_pane_trash_copy_requested(self, event: TrashCopyRequested) -> None:
        self.copy_events.append(event)


def _records() -> list:
    return [
        make_record("old", text="oldest draft", trashed_at="2026-06-16T10:00:00"),
        make_record("new", text="newest draft", trashed_at="2026-06-16T12:00:00"),
        make_record("mid", text="middle draft", trashed_at="2026-06-16T11:00:00"),
    ]


def _trash_pane(app: TrashOverlayHost) -> TrashPane:
    modal = app.screen
    assert isinstance(modal, PromptsModal)
    pane = modal._ensure_trash_pane()
    assert isinstance(pane, TrashPane)
    return pane


# -- pure helpers ------------------------------------------------------------


def test_sort_newest_first_with_stable_ties() -> None:
    records = [
        make_record("b", trashed_at="2026-06-16T12:00:00"),
        make_record("a", trashed_at="2026-06-16T12:00:00"),
        make_record("c", trashed_at="2026-06-16T09:00:00"),
    ]
    assert [r.entry.id for r in sort_trash_records(records)] == ["b", "a", "c"]


def test_trash_row_label_marks() -> None:
    record = make_record("x", text="hello")
    plain = trash_row_label(
        record,
        marked_for_restore=False,
        marked_for_purge=False,
        trashed_age="2h ago",
    ).plain
    assert "✗" not in plain and "✓" not in plain
    assert "2h ago" in plain and "hello" in plain
    restore = trash_row_label(
        record,
        marked_for_restore=True,
        marked_for_purge=False,
        trashed_age="2h ago",
    )
    assert "✓" in restore.plain
    purge = trash_row_label(
        record,
        marked_for_restore=False,
        marked_for_purge=True,
        trashed_age="2h ago",
    )
    assert "✗" in purge.plain


def test_trash_empty_text_variants() -> None:
    assert "disabled" in trash_empty_text(trash_limit=0)
    assert "0" in trash_empty_text(trash_limit=0)
    plain = trash_empty_text(trash_limit=20)
    assert "Stash d" in plain
    pointed = trash_empty_text(trash_limit=20, has_stash_rows=True)
    assert "Stash d moves" in pointed


def test_purge_confirm_text_names_count_and_rows() -> None:
    records = [
        make_record("a", text="first draft here"),
        make_record("b", text="second"),
    ]
    text = purge_confirm_text(["a", "b"], records)
    assert "Permanently delete 2 drafts" in text
    assert "cannot be undone" in text
    assert "first draft here" in text
    single = purge_confirm_text(["a"], records)
    assert "Permanently delete 1 draft?" in single


def test_purge_confirm_text_truncates_long_lists() -> None:
    records = [make_record(f"id{i}", text=f"draft {i}") for i in range(7)]
    text = purge_confirm_text([f"id{i}" for i in range(7)], records)
    assert "and 2 more" in text


# -- widget behavior ---------------------------------------------------------


async def test_restore_mark_enter_posts_restore_and_stays_open() -> None:
    app = TrashOverlayHost(_records())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = _trash_pane(app)
        assert pane.record_ids == ["new", "mid", "old"]
        await pilot.press("tab")  # stage "new" for restore
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.restore_events) == 1
        assert app.restore_events[0].entry_ids == ["new"]
        assert app.purge_events == []
        assert app.result == "UNSET"
        # Authoritative repaint has not run: rows and marks are intact.
        assert pane.record_ids == ["new", "mid", "old"]
        assert pane._restore == {"new"}


async def test_purge_partial_posts_purge_and_keeps_pending() -> None:
    app = TrashOverlayHost(_records())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = _trash_pane(app)
        await pilot.press("d")  # stage "new" for purge
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.purge_events) == 1
        assert app.purge_events[0].entry_ids == ["new"]
        assert app.restore_events == []
        assert app.result == "UNSET"
        assert pane.record_ids == ["new", "mid", "old"]
        assert pane._purge == {"new"}


async def test_digit_restores_highlighted_row_without_marks() -> None:
    app = TrashOverlayHost(_records())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("2")  # "mid" without staging anything
        await pilot.pause()
        assert len(app.restore_events) == 1
        assert app.restore_events[0].entry_ids == ["mid"]
        assert app.result == "UNSET"


async def test_purge_all_dismisses_with_result() -> None:
    app = TrashOverlayHost(_records())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("D")  # stage every row for purge
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, PromptsResult)
    assert app.result.tab is PromptsTab.TRASH
    assert isinstance(app.result.trash, TrashActionResult)
    assert sorted(app.result.trash.purge_ids) == ["mid", "new", "old"]
    assert app.result.trash.restore_ids == []
    assert app.purge_events == []


async def test_combined_restore_and_purge_posts_both() -> None:
    app = TrashOverlayHost(_records())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("tab")  # restore "new"
        await pilot.press("j")  # highlight "mid"
        await pilot.press("d")  # purge "mid"
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.restore_events) == 1
        assert app.restore_events[0].entry_ids == ["new"]
        assert len(app.purge_events) == 1
        assert app.purge_events[0].entry_ids == ["mid"]
        assert app.result == "UNSET"


async def test_no_pin_binding_in_trash() -> None:
    app = TrashOverlayHost(_records())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()
        assert app.restore_events == []
        assert app.purge_events == []
        assert app.result == "UNSET"


async def test_ctrl_y_posts_copy_request() -> None:
    app = TrashOverlayHost(_records())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+y")
        await pilot.pause()
        assert len(app.copy_events) == 1
        assert app.copy_events[0].entry.id == "new"
        assert app.result == "UNSET"


async def test_apply_snapshot_drops_stale_marks() -> None:
    app = TrashOverlayHost(_records())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = _trash_pane(app)
        await pilot.press("tab")  # stage "new"
        await pilot.pause()
        assert pane._restore == {"new"}
        # Authoritative outcome: "new" restored to Stash, "fresh" trashed
        # concurrently by another process; stale "new" mark must drop.
        pane.apply_snapshot(
            [
                make_record(
                    "mid", text="middle draft", trashed_at="2026-06-16T11:00:00"
                ),
                make_record(
                    "old", text="oldest draft", trashed_at="2026-06-16T10:00:00"
                ),
                make_record(
                    "fresh", text="fresh draft", trashed_at="2026-06-16T13:00:00"
                ),
            ]
        )
        await pilot.pause()
        assert pane._restore == set()
        assert pane.record_ids == ["fresh", "mid", "old"]


async def test_apply_store_failure_keeps_rows_and_marks() -> None:
    app = TrashOverlayHost(_records())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = _trash_pane(app)
        await pilot.press("d")
        await pilot.pause()
        assert pane._purge == {"new"}
        pane.apply_store_failure()
        await pilot.pause()
        assert pane.record_ids == ["new", "mid", "old"]
        assert pane._purge == {"new"}


async def test_empty_trash_shows_explanation() -> None:
    app = TrashOverlayHost([])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = _trash_pane(app)
        assert pane.record_ids == []
        assert "Discarded drafts" in pane._empty_text()
        await pilot.press("enter")
        await pilot.pause()
        assert app.restore_events == []
        assert app.result == "UNSET"


async def test_zero_limit_trash_shows_disabled() -> None:
    app = TrashOverlayHost([], trash_limit=0)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        pane = _trash_pane(app)
        assert "disabled" in pane._empty_text()
