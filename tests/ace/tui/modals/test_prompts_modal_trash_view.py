"""Pilot coverage for the Stash Trash view, `@`, and remembered views."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.modals.prompts_modal import (
    PromptsModal,
    PromptsOrigin,
    PromptsResult,
    PromptsTab,
)
from sase.ace.tui.modals.prompts_tab_bar import PromptsTabBar
from tests.ace.tui.modals.stashed_prompts_modal_test_helpers import make_entry
from tests.ace.tui.modals.test_trash_pane import make_record


class TrashViewHost(App[None]):
    """Push the overlay and capture its dismiss result."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        entries: list | None = None,
        *,
        trash: list | None = None,
        trash_limit: int = 100,
        initial_tab: PromptsTab = PromptsTab.STASH,
    ) -> None:
        super().__init__()
        self._entries = list(entries) if entries is not None else []
        self._trash = list(trash) if trash is not None else []
        self._trash_limit = trash_limit
        self._initial_tab = initial_tab
        self.result: object = "UNSET"

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(
            PromptsModal(
                self._entries,
                origin=PromptsOrigin(),
                initial_tab=self._initial_tab,
                trash=self._trash,
                trash_limit=self._trash_limit,
            ),
            lambda result: setattr(self, "result", result),
        )


def _entries() -> list:
    return [
        make_entry("a", text="first draft", created_at="2026-06-16T12:00:00"),
        make_entry("b", text="second draft", created_at="2026-06-16T11:00:00"),
    ]


def _record_history_io(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from sase.history.prompt_history_project_filter import PromptHistoryProjectCatalog
    from sase.history.prompt_catalog import PromptHistoryPage

    def _empty_catalog() -> object:
        return PromptHistoryProjectCatalog(entries=())

    def _empty_page(**kwargs: object) -> object:
        return PromptHistoryPage(records=[], next_cursor=None, exhausted=True)

    monkeypatch.setattr(
        "sase.history.prompt_history_project_filter.PromptHistoryProjectCatalog.load",
        staticmethod(_empty_catalog),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.history_pane.load_prompt_record_page",
        _empty_page,
    )


async def test_t_opens_trash_and_returns() -> None:
    app = TrashViewHost(_entries(), trash=[make_record("t1")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        assert modal._active_tab is PromptsTab.STASH
        await pilot.press("t")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.TRASH
        assert modal.query_one("#trash-list", OptionList)
        await pilot.press("t")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH
        assert modal.query_one("#stashed-prompts-list", OptionList)


async def test_esc_returns_and_q_closes_from_trash() -> None:
    app = TrashViewHost(_entries(), trash=[make_record("t1")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("t")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.TRASH
        await pilot.press("escape")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH
        assert app.result == "UNSET"
        assert modal.is_mounted

    app = TrashViewHost(_entries(), trash=[make_record("t1")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
    assert app.result is None


async def test_click_chip_and_stash_label() -> None:
    app = TrashViewHost(_entries(), trash=[make_record("t1")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        bar = modal.query_one("#prompts-modal-tabs", PromptsTabBar)

        def _offset(surface: str) -> tuple[int, int]:
            hits = {sid: (s, e) for s, e, sid in bar._hits}
            start, end = hits[surface]
            return ((start + end) // 2, 0)

        await pilot.click("#prompts-modal-tabs", offset=_offset("trash"))
        await pilot.pause()
        assert modal._active_tab is PromptsTab.TRASH
        await pilot.click("#prompts-modal-tabs", offset=_offset("stash"))
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH


async def test_brackets_restore_remembered_stash_view(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _record_history_io(monkeypatch)
    app = TrashViewHost(_entries(), trash=[make_record("t1")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("t")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.TRASH
        await pilot.press("]")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.HISTORY
        await pilot.press("[")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.TRASH
        await pilot.press("t")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH
        await pilot.press("]")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.HISTORY
        await pilot.press("[")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH


async def test_at_restores_newest_unpinned() -> None:
    app = TrashViewHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("@")
        await pilot.pause()
    assert isinstance(app.result, PromptsResult)
    assert app.result.tab is PromptsTab.STASH
    assert app.result.stash is not None
    assert app.result.stash.pop_ids == ["a"]
    assert app.result.stash.keep_ids == []


async def test_at_keeps_pinned_newest() -> None:
    entries = [
        make_entry(
            "a", text="newest pinned", created_at="2026-06-16T12:00:00", pinned=True
        ),
        make_entry("b", text="older", created_at="2026-06-16T11:00:00"),
    ]
    app = TrashViewHost(entries)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("@")
        await pilot.pause()
    assert isinstance(app.result, PromptsResult)
    assert app.result.stash is not None
    assert app.result.stash.keep_ids == ["a"]
    assert app.result.stash.pop_ids == []


async def test_at_ignores_staged_marks() -> None:
    app = TrashViewHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("j")  # highlight older "b"
        await pilot.press("d")  # stage "b" for trash
        await pilot.pause()
        assert modal._stash_pane._deleted == {"b"}
        await pilot.press("@")
        await pilot.pause()
    assert isinstance(app.result, PromptsResult)
    assert app.result.stash is not None
    assert app.result.stash.pop_ids == ["a"]


async def test_at_noop_on_empty_stash() -> None:
    app = TrashViewHost([])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("@")
        await pilot.pause()
        assert app.result == "UNSET"
        assert app.screen.is_mounted


async def test_at_noop_on_trash_and_history(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _record_history_io(monkeypatch)
    app = TrashViewHost(_entries(), trash=[make_record("t1")])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("t")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.TRASH
        await pilot.press("@")
        await pilot.pause()
        assert app.result == "UNSET"
        assert modal._active_tab is PromptsTab.TRASH
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("]")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.HISTORY
        # Focus is in the filter; "@" must type instead of restoring.
        filter_input = modal.query_one("#prompt-history-filter-input", Input)
        assert filter_input.has_focus
        await pilot.press("@")
        await pilot.pause()
        assert "@" in filter_input.value
        assert app.result == "UNSET"


async def test_bar_state_follows_snapshot() -> None:
    app = TrashViewHost(
        _entries(), trash=[make_record("t1", trashed_at="2026-06-16T10:00:00")]
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        bar = modal.query_one("#prompts-modal-tabs", PromptsTabBar)
        assert bar.state.stash_count == 2
        assert bar.state.trash_count == 1
        modal.apply_lifecycle_snapshot(
            [make_entry("b", text="second draft", created_at="2026-06-16T11:00:00")],
            [make_record("a", text="first draft", trashed_at="2026-06-16T13:00:00")],
        )
        await pilot.pause()
        assert bar.state.stash_count == 1
        assert bar.state.trash_count == 1
