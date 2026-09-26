"""Tests for the Trash tab and the Stash-to-Trash flow in the overlay."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from sase.ace.tui.modals.prompts_modal import (
    PromptsModal,
    PromptsOrigin,
    PromptsResult,
    PromptsTab,
)
from sase.ace.tui.modals.stash_pane import (
    StashPane,
    StashRestoreResult,
    TrashRequested,
    preview_trash_commit,
    stash_empty_text,
    trash_commit_confirm_text,
    trash_outcome_text,
)
from sase.ace.tui.modals.trash_pane import TrashPane
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from tests.ace.tui.modals.stashed_prompts_modal_test_helpers import make_entry
from tests.ace.tui.modals.test_trash_pane import make_record


class TrashFlowHost(App[None]):
    """Push the full overlay and capture stash/trash requests + result."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        entries: list | None = None,
        *,
        trash: list | None = None,
        trash_limit: int = 20,
        initial_tab: PromptsTab = PromptsTab.STASH,
        origin: PromptsOrigin | None = None,
    ) -> None:
        super().__init__()
        self._entries = list(entries) if entries is not None else []
        self._trash = list(trash) if trash is not None else []
        self._trash_limit = trash_limit
        self._initial_tab = initial_tab
        self._origin = origin
        self.result: object = "UNSET"
        self.trash_requests: list[TrashRequested] = []
        self.delete_events: list = []

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(
            PromptsModal(
                self._entries,
                origin=self._origin,
                initial_tab=self._initial_tab,
                trash=self._trash,
                trash_limit=self._trash_limit,
            ),
            lambda result: setattr(self, "result", result),
        )

    def on_stashed_prompts_modal_trash_requested(self, event: TrashRequested) -> None:
        self.trash_requests.append(event)

    def on_stashed_prompts_modal_delete_requested(self, event: object) -> None:
        self.delete_events.append(event)


def _entries() -> list:
    return [
        make_entry("a", text="first draft", created_at="2026-06-16T12:00:00"),
        make_entry("b", text="second draft", created_at="2026-06-16T11:00:00"),
    ]


def _refuse_history_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse_catalog() -> object:
        raise AssertionError("history catalog must not load before activation")

    def _refuse_page(**kwargs: object) -> object:
        raise AssertionError("history pages must not load before activation")

    monkeypatch.setattr(
        "sase.history.prompt_history_project_filter.PromptHistoryProjectCatalog.load",
        staticmethod(_refuse_catalog),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.history_pane.load_prompt_record_page",
        _refuse_page,
    )


# -- tab strip and cycling ---------------------------------------------------


async def test_trash_tab_shows_count_over_limit() -> None:
    app = TrashFlowHost(_entries(), trash=[make_record("t1"), make_record("t2")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        strip = modal.query_one("#prompts-modal-tabs", PanelTabStrip)
        assert [tab.label for tab in strip._tabs] == [
            "Stash 2",
            "History",
            "Trash 2/20",
        ]
        assert [tab.accent_color for tab in strip._tabs] == [
            "orchid",
            "cyan",
            "#EBC04F",
        ]


async def test_trash_footer_names_restore_and_purge_verbs() -> None:
    app = TrashFlowHost(
        _entries(), trash=[make_record("t1")], initial_tab=PromptsTab.TRASH
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        footer = modal.query_one("#prompts-modal-footer", Static)
        content = str(footer.content)
        assert "Enter: restore to Stash" in content
        assert "permanently delete" in content


async def test_open_on_trash_skips_history_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _refuse_history_io(monkeypatch)
    app = TrashFlowHost(_entries(), initial_tab=PromptsTab.TRASH)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        assert modal._active_tab is PromptsTab.TRASH
        assert modal.query_one("#trash-list", OptionList)
        assert modal._history_pane is None


async def test_brackets_cycle_three_tabs_with_wraparound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.ace.tui.modals.test_prompts_modal import _record_history_io

    _record_history_io(monkeypatch)
    app = TrashFlowHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("]")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.HISTORY
        await pilot.press("]")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.TRASH
        assert modal.query_one("#trash-list", OptionList)
        await pilot.press("]")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH
        await pilot.press("[")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.TRASH
        await pilot.press("[")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.HISTORY


# -- stash-to-trash flow -----------------------------------------------------


async def test_stash_delete_posts_trash_request_and_holds_pending() -> None:
    app = TrashFlowHost(_entries(), trash=[make_record("t1")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("d")  # mark "a" for Trash
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.trash_requests) == 1
        assert app.trash_requests[0].entry_ids == ["a"]
        assert app.result == "UNSET"
        # Pending state: rows and marks survive until authoritative repaint.
        assert [e.id for e in modal._stash_pane._entries] == ["a", "b"]
        assert modal._stash_pane._deleted == {"a"}


async def test_stash_combined_restore_and_trash_dismisses() -> None:
    app = TrashFlowHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("tab")  # restore "a"
        await pilot.press("j")  # highlight "b"
        await pilot.press("d")  # trash "b"
        await pilot.press("enter")
        await pilot.pause()
    assert isinstance(app.result, PromptsResult)
    assert app.result.tab is PromptsTab.STASH
    assert isinstance(app.result.stash, StashRestoreResult)
    assert app.result.stash.pop_ids == ["a"]
    assert app.result.stash.trash_ids == ["b"]
    assert app.result.stash.delete_ids == []
    assert app.trash_requests == []


async def test_unpinned_restore_moves_nothing_to_trash() -> None:
    app = TrashFlowHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("enter")  # restore highlighted "a", no marks
        await pilot.pause()
    assert isinstance(app.result, PromptsResult)
    assert app.result.stash is not None
    assert app.result.stash.pop_ids == ["a"]
    assert app.result.stash.trash_ids == []
    assert app.result.stash.delete_ids == []


async def test_zero_limit_stash_delete_stays_permanent() -> None:
    app = TrashFlowHost(_entries(), trash_limit=0)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("d")  # mark "a"
        await pilot.press("enter")
        await pilot.pause()
        # Zero disables recovery: legacy permanent path, not Trash.
        assert app.trash_requests == []
        assert len(app.delete_events) == 1
        assert [e.id for e in modal._stash_pane._entries] == ["b"]


# -- authoritative repaint ---------------------------------------------------


async def test_apply_lifecycle_snapshot_repaints_panes_and_counts() -> None:
    app = TrashFlowHost(
        _entries(), trash=[make_record("t1", trashed_at="2026-06-16T10:00:00")]
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("d")  # stage "a" for Trash
        await pilot.pause()
        assert modal._stash_pane._deleted == {"a"}
        # Authoritative outcome: "a" trashed, "t1" evicted by the limit.
        modal.apply_lifecycle_snapshot(
            [make_entry("b", text="second draft", created_at="2026-06-16T11:00:00")],
            [make_record("a", text="first draft", trashed_at="2026-06-16T13:00:00")],
        )
        await pilot.pause()
        assert [e.id for e in modal._stash_pane._entries] == ["b"]
        assert modal._stash_pane._deleted == set()
        strip = modal.query_one("#prompts-modal-tabs", PanelTabStrip)
        assert [tab.label for tab in strip._tabs] == [
            "Stash 1",
            "History",
            "Trash 1/20",
        ]
        # Trash pane picks up the snapshot when it mounts.
        await pilot.press("]")
        await pilot.pause()
        await pilot.press("]")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.TRASH
        trash_pane = modal._ensure_trash_pane()
        assert isinstance(trash_pane, TrashPane)
        assert trash_pane.record_ids == ["a"]


async def test_apply_store_failure_keeps_marks_truthful() -> None:
    app = TrashFlowHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("d")
        await pilot.pause()
        modal.apply_store_failure()
        await pilot.pause()
        assert [e.id for e in modal._stash_pane._entries] == ["a", "b"]
        assert modal._stash_pane._deleted == {"a"}


async def test_empty_stash_points_to_trash() -> None:
    app = TrashFlowHost([], trash=[make_record("t1"), make_record("t2")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        pane = modal._stash_pane
        assert isinstance(pane, StashPane)
        assert pane._entries == []
        assert "Trash holds 2 discarded drafts" in (pane._placeholder_text() or "")


async def test_empty_stash_without_trash_has_no_pointer() -> None:
    app = TrashFlowHost([])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        text = modal._stash_pane._placeholder_text() or ""
        assert "No stashed drafts" in text
        assert "Trash holds" not in text


# -- preview and confirmation text -------------------------------------------


def test_preview_counts_evictions_and_pins() -> None:
    entries = [
        make_entry("a", pinned=True),
        make_entry("b"),
        make_entry("c"),
    ]
    preview = preview_trash_commit(["a", "b"], entries, trash_count=19, trash_limit=20)
    assert preview.marked_ids == ("a", "b")
    assert preview.pinned_ids == ("a",)
    assert preview.expected_evictions == 1
    text = trash_commit_confirm_text(preview)
    assert "Move 2 drafts to Trash?" in text
    assert "pinned" in text
    assert "permanently deleted" in text


def test_preview_batch_larger_than_limit_counts_all_overflow() -> None:
    entries = [make_entry(f"id{i}") for i in range(5)]
    preview = preview_trash_commit(
        [f"id{i}" for i in range(5)], entries, trash_count=20, trash_limit=20
    )
    assert preview.expected_evictions == 5
    assert preview.pinned_ids == ()


def test_preview_limit_one_and_zero() -> None:
    entries = [make_entry("a"), make_entry("b")]
    one = preview_trash_commit(["a"], entries, trash_count=1, trash_limit=1)
    assert one.expected_evictions == 1
    zero = preview_trash_commit(["a"], entries, trash_count=0, trash_limit=0)
    assert zero.expected_evictions == 0


def test_preview_drops_stale_ids() -> None:
    entries = [make_entry("a")]
    preview = preview_trash_commit(
        ["a", "ghost"], entries, trash_count=0, trash_limit=20
    )
    assert preview.marked_ids == ("a",)
    assert preview.expected_evictions == 0


def test_outcome_text_names_actual_evictions() -> None:
    assert trash_outcome_text(3, []) == "Moved 3 drafts to Trash"
    assert (
        trash_outcome_text(2, ["x", "y"])
        == "Moved 2 drafts to Trash (permanently deleted 2 oldest drafts: x, y)"
    )


def test_stash_empty_text_pointer() -> None:
    assert "Trash holds" not in stash_empty_text(trash_count=0)
    assert "Trash holds 1 discarded draft" in stash_empty_text(trash_count=1)


def test_trash_result_carries_origin() -> None:
    origin = PromptsOrigin(kind="home_mru")
    result = PromptsResult(tab=PromptsTab.TRASH, origin=origin, trash=None)
    assert result.origin == origin
    assert result.history is None
    assert result.stash is None
