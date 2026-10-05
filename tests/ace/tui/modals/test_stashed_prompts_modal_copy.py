"""Copy-highlighted-stash-prompt (``y``) behavior tests.

Covers the shared ``StashControllerMixin.action_copy_prompt`` in both stash
hosts: the standalone ``StashedPromptsModal`` and the tabbed overlay's
``StashPane`` (via ``PromptsModal``). Clipboard transports are stubbed; the
developer's real clipboard and stash store are never touched.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.copy_fallback_modal import CopyFallbackModal
from sase.ace.tui.modals.prompts_modal import (
    PromptsModal,
    PromptsOrigin,
    PromptsTab,
)
from sase.ace.tui.modals.stashed_prompts_modal import StashedPromptsModal
from sase.core.prompt_stash_wire import PromptStashEntryWire
from tests.ace.tui.modals.stashed_prompts_modal_test_helpers import (
    ModalHost,
    make_entry,
)


def _entries() -> list[PromptStashEntryWire]:
    return [
        make_entry("new", text="newest draft", created_at="2026-06-16T12:00:00"),
        make_entry("mid", text="middle draft", created_at="2026-06-16T11:00:00"),
        make_entry("old", text="oldest draft", created_at="2026-06-16T10:00:00"),
    ]


def _stub_clipboard_success(monkeypatch: pytest.MonkeyPatch, copied: list[str]) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )


async def _drain_clipboard_tasks(app: App[None]) -> None:
    while tasks := tuple(getattr(app, "_pump_free_clipboard_tasks", ())):
        await asyncio.gather(*tasks)
        await asyncio.sleep(0)


class PromptsHost(App[None]):
    """Push the Prompts overlay and capture its dismiss result."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        entries: list[PromptStashEntryWire],
        *,
        trash: list | None = None,
    ) -> None:
        super().__init__()
        self._entries = entries
        self._trash = list(trash) if trash is not None else []
        self.result: object = "UNSET"

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(
            PromptsModal(
                self._entries,
                origin=PromptsOrigin(),
                trash=self._trash,
            ),
            lambda result: setattr(self, "result", result),
        )


def _record_history_io(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.history.prompt_history_project_filter import PromptHistoryProjectCatalog
    from sase.history.prompt_catalog import PromptHistoryPage

    monkeypatch.setattr(
        "sase.history.prompt_history_project_filter.PromptHistoryProjectCatalog.load",
        staticmethod(lambda: PromptHistoryProjectCatalog(entries=())),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.history_pane.load_prompt_record_page",
        lambda **kwargs: PromptHistoryPage(
            records=[], next_cursor=None, exhausted=True
        ),
    )


async def test_y_copies_highlighted_row_only_and_keeps_panel_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    _stub_clipboard_success(monkeypatch, copied)
    app = ModalHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        # Stage a restore mark on the newest row, then move off it: ``y``
        # must copy the highlighted row, not the marked one.
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("j")
        await pilot.pause()
        option_list = modal.query_one("#stashed-prompts-list", OptionList)
        assert option_list.highlighted == 1
        assert modal._pop == {"new"}

        await pilot.press("y")
        await wait_for(pilot, lambda: len(copied) == 1)
        await _drain_clipboard_tasks(pilot.app)

        assert copied == ["middle draft"]
        # Panel stays open with highlight, rows, and marks intact.
        assert app.screen is modal
        assert app.result == "UNSET"
        assert option_list.highlighted == 1
        assert [entry.id for entry in modal._entries] == ["new", "mid", "old"]
        assert modal._pop == {"new"}
        assert modal._pinned == set()
        assert modal._deleted == set()


async def test_y_copies_exact_bundled_body_without_frontmatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "  first line  \n---\nünïcode #ref <tag>\n\ntrailing space  \n"
    entry = PromptStashEntryWire(
        id="bundle",
        created_at="2026-06-16T12:00:00",
        text=body,
        frontmatter="title: hidden\n",
        project="proj",
    )
    copied: list[str] = []
    _stub_clipboard_success(monkeypatch, copied)
    app = ModalHost([entry])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("y")
        await wait_for(pilot, lambda: len(copied) == 1)
        await _drain_clipboard_tasks(pilot.app)

    assert copied == [body]
    assert copied[0] != "title: hidden\n"
    assert "\n---\n" in copied[0]
    assert copied[0].endswith("\n")


async def test_y_copies_selected_empty_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    _stub_clipboard_success(monkeypatch, copied)
    entry = make_entry("empty", text="")
    app = ModalHost([entry])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("y")
        await wait_for(pilot, lambda: len(copied) == 1)
        await _drain_clipboard_tasks(pilot.app)

    # Guard is on entry presence, not text truthiness: empty copies empty.
    assert copied == [""]
    assert app.result == "UNSET"


async def test_y_with_empty_list_is_safe_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    _stub_clipboard_success(monkeypatch, copied)
    app = ModalHost([])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        await _drain_clipboard_tasks(pilot.app)

    assert copied == []
    assert app.result == "UNSET"


async def test_overlay_y_copies_highlighted_row_and_keeps_overlay_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    _stub_clipboard_success(monkeypatch, copied)
    app = PromptsHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("j")
        await pilot.pause()
        assert modal._stash_pane._highlighted_entry() is not None
        assert modal._stash_pane._highlighted_entry().id == "mid"

        await pilot.press("y")
        await wait_for(pilot, lambda: len(copied) == 1)
        await _drain_clipboard_tasks(pilot.app)

        assert copied == ["middle draft"]
        assert app.screen is modal
        assert app.result == "UNSET"
        assert modal._stash_pane._highlighted_entry().id == "mid"
        assert "y copy" in modal._footer_text()


async def test_overlay_history_filter_y_does_not_fire_stash_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _record_history_io(monkeypatch)
    copied: list[str] = []
    _stub_clipboard_success(monkeypatch, copied)
    app = PromptsHost(_entries())
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("]")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.HISTORY
        filter_input = modal.query_one("#prompt-history-filter-input", Input)
        assert filter_input.has_focus
        await pilot.press("y")
        await pilot.pause()
        assert filter_input.value == "y"
        assert copied == []
        assert app.result == "UNSET"
        # Returning to Stash re-enables ``y``.
        await pilot.press("[")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.STASH
        await pilot.press("y")
        await wait_for(pilot, lambda: len(copied) == 1)
        await _drain_clipboard_tasks(pilot.app)
        assert copied == ["newest draft"]
        assert app.result == "UNSET"


async def test_overlay_trash_focus_y_does_not_copy_stash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.ace.tui.modals.test_trash_pane import make_record

    copied: list[str] = []
    _stub_clipboard_success(monkeypatch, copied)
    app = PromptsHost(
        _entries(),
        trash=[make_record("t1", text="trashed draft")],
    )
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, PromptsModal)
        await pilot.press("t")
        await pilot.pause()
        assert modal._active_tab is PromptsTab.TRASH
        await pilot.press("y")
        await pilot.pause()
        await _drain_clipboard_tasks(pilot.app)
        assert copied == []
        assert app.result == "UNSET"


async def test_navigation_stays_responsive_while_delivery_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    entered = threading.Event()
    release = threading.Event()
    try:

        def _gated_copy(content: str) -> bool:
            entered.set()
            assert release.wait(timeout=10)
            copied.append(content)
            return True

        monkeypatch.setattr(
            "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
            _gated_copy,
        )
        app = ModalHost(_entries())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, StashedPromptsModal)
            await pilot.press("y")
            await wait_for(pilot, entered.is_set)
            # Navigate while delivery is held: the UI must keep up and the
            # clipboard must still receive the original selection's text.
            await pilot.press("j")
            await pilot.pause()
            option_list = modal.query_one("#stashed-prompts-list", OptionList)
            assert option_list.highlighted == 1
            release.set()
            await wait_for(pilot, lambda: len(copied) == 1)
            await _drain_clipboard_tasks(pilot.app)
            assert copied == ["newest draft"]
            assert app.result == "UNSET"
    finally:
        release.set()


async def test_transport_failure_shows_exact_fallback_and_returns_to_stash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "recover me\n---\nsecond body\n"
    entry = make_entry("row", text=body)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda _content: False,
    )
    app = ModalHost([entry])
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()

        def _fail_osc52(_value: str) -> None:
            raise RuntimeError("no OSC 52 transport")

        monkeypatch.setattr(app, "copy_to_clipboard", _fail_osc52)
        await pilot.press("y")
        await wait_for(pilot, lambda: isinstance(app.screen, CopyFallbackModal))
        fallback = app.screen
        assert isinstance(fallback, CopyFallbackModal)
        assert fallback.content == body
        await pilot.press("escape")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, StashedPromptsModal)
        assert [item.id for item in modal._entries] == ["row"]
        assert modal._pop == set()
        assert modal._pinned == set()
        assert modal._deleted == set()
        assert app.result == "UNSET"


def test_stash_hints_advertise_y_copy_in_both_modes() -> None:
    standalone = StashedPromptsModal(_entries())
    assert "y copy" in standalone._hint_text()
    from sase.ace.tui.modals.stash_pane_widget import StashPane

    overlay_pane = StashPane(_entries())
    assert overlay_pane._trash_mode()
    assert "y copy" in overlay_pane._hint_text()
