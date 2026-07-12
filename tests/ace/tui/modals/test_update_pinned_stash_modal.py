"""Tests for the update-pinned-prompt picker."""

from __future__ import annotations

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.update_pinned_stash_modal import UpdatePinnedStashModal
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
        pinned=True,
    )


class _ModalHost(App[None]):
    """Pushes the update picker and captures its dismiss result."""

    def __init__(self, entries: list[PromptStashEntryWire]) -> None:
        super().__init__()
        self._entries = entries
        self.result: object = "UNSET"

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(
            UpdatePinnedStashModal(self._entries),
            lambda res: setattr(self, "result", res),
        )


async def test_digit_picks_expected_entry_id() -> None:
    app = _ModalHost(
        [
            _entry("first", created_at="2026-06-16T12:00:00"),
            _entry("target", created_at="2026-06-16T11:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()

    assert app.result == "target"


async def test_zero_picks_tenth_entry_id() -> None:
    entries = [
        _entry(
            f"row-{idx + 1}",
            created_at=f"2026-06-16T{23 - idx:02d}:00:00",
        )
        for idx in range(10)
    ]
    app = _ModalHost(entries)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("0")
        await pilot.pause()

    assert app.result == "row-10"


async def test_enter_confirms_highlighted_after_navigation() -> None:
    app = _ModalHost(
        [
            _entry("first", created_at="2026-06-16T12:00:00"),
            _entry("target", created_at="2026-06-16T11:00:00"),
        ]
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("enter")
        await pilot.pause()

    assert app.result == "target"


async def test_preview_follows_highlight() -> None:
    app = _ModalHost(
        [
            _entry("first", "First", created_at="2026-06-16T12:00:00"),
            _entry(
                "target",
                "#review\n\nTarget full prompt",
                created_at="2026-06-16T11:00:00",
            ),
        ]
    )
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, UpdatePinnedStashModal)
        body = modal.query_one(".prompt-stash-preview-body", Static)
        assert body.render().plain == "First"

        await pilot.press("j")
        await pilot.pause(0.2)
        assert body.render().plain == "#review\n\nTarget full prompt"


async def test_escape_and_q_cancel() -> None:
    app_escape = _ModalHost([_entry("a")])
    async with app_escape.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert app_escape.result is None

    app_q = _ModalHost([_entry("a")])
    async with app_q.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
    assert app_q.result is None


def test_rows_render_pin_glyph_preview_and_digit_gutter() -> None:
    modal = UpdatePinnedStashModal([_entry("a", "\n\npreview line\nsecond")])
    option = modal._build_options()[0]
    assert isinstance(option.prompt, Text)
    plain = option.prompt.plain
    assert plain.startswith(" 1  ")
    assert "📌" in plain
    assert "preview line" in plain


def test_newest_first_ordering() -> None:
    modal = UpdatePinnedStashModal(
        [
            _entry("old", created_at="2026-06-16T09:00:00"),
            _entry("new", created_at="2026-06-16T11:00:00"),
            _entry("mid", created_at="2026-06-16T10:00:00"),
        ]
    )
    assert [entry.id for entry in modal._entries] == ["new", "mid", "old"]
