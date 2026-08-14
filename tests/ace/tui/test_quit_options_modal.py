"""Tests for the quit / restart options modal."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.modals import QuitOption, QuitOptionsModal


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def test_warning_text_singular_and_plural() -> None:
    single = QuitOptionsModal(running_task_count=1)
    plural = QuitOptionsModal(running_task_count=2)

    assert single._warning_text() == "  1 proc will be stopped."
    assert plural._warning_text() == "  2 procs will be stopped."


async def test_modal_keys_return_choices(monkeypatch) -> None:
    async with _TestApp().run_test() as pilot:
        modal = QuitOptionsModal(running_task_count=2)
        dismissed: list[QuitOption | None] = []
        monkeypatch.setattr(modal, "dismiss", dismissed.append)
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("1")
        await pilot.press("s")
        await pilot.press("2")
        await pilot.press("r")
        await pilot.press("3")
        await pilot.press("a")
        await pilot.press("escape")
        await pilot.press("q")
        await pilot.pause()

    assert dismissed == [
        "quit_stop_axe",
        "quit_stop_axe",
        "restart_tui",
        "restart_tui",
        "restart_tui_and_axe",
        "restart_tui_and_axe",
        None,
        None,
    ]
