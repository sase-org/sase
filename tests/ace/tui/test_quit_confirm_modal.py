"""Tests for the rich quit confirmation modal."""

from __future__ import annotations

from datetime import datetime, timedelta

from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from sase.ace.tui.modals import QuitConfirmModal
from sase.ace.tui.task_queue import TaskInfo


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _task(
    task_id: str = "task-1",
    task_type: str = "sync",
    message: str = "Syncing visual-auth...",
    *,
    display_name: str | None = "Sync visual-auth",
) -> TaskInfo:
    return TaskInfo(
        task_id=task_id,
        task_type=task_type,
        cl_name="visual-auth",
        project_file="/tmp/project.sase",
        status="running",
        message=message,
        started_at=datetime.now() - timedelta(seconds=12),
        display_name=display_name,
    )


def test_format_summary_singular_and_plural() -> None:
    single = QuitConfirmModal([_task()])
    plural = QuitConfirmModal([_task("task-1"), _task("task-2", "mail")])

    assert "1 background task is still running." in single._summary_text().plain
    assert "kill it before it finishes" in single._summary_text().plain
    assert "2 background tasks are still running." in plural._summary_text().plain
    assert "kill them before they finish" in plural._summary_text().plain


def test_task_card_renders_label_type_message_and_elapsed(monkeypatch) -> None:
    import sase.ace.tui.modals.quit_confirm_modal as quit_confirm_modal

    monkeypatch.setattr(quit_confirm_modal, "_format_elapsed", lambda _dt: "12s")
    task = _task(
        task_type="accept",
        message="Accepting proposal visual-auth with a useful status line",
        display_name="Accept visual-auth",
    )
    card = QuitConfirmModal([task])._task_card_text(task)

    assert "Accept visual-auth" in card.plain
    assert "ACCEPT" in card.plain
    assert "12s" in card.plain
    assert "Accepting proposal visual-auth" in card.plain


async def test_modal_buttons_return_confirm_and_cancel(monkeypatch) -> None:
    async with _TestApp().run_test() as pilot:
        modal = QuitConfirmModal([_task()])
        dismissed: list[bool] = []
        monkeypatch.setattr(modal, "dismiss", dismissed.append)
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal.query_one("#cancel-btn", Button).has_focus

        await pilot.press("y")
        await pilot.press("n")
        await pilot.press("escape")
        await pilot.pause()

    assert dismissed == [True, False, False]


async def test_modal_composes_one_card_per_task() -> None:
    async with _TestApp().run_test() as pilot:
        modal = QuitConfirmModal(
            [
                _task("task-1", "sync"),
                _task("task-2", "mail"),
                _task("task-3", "accept"),
            ]
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        cards = modal.query(".quit-confirm-proc-card").nodes
        assert len(cards) == 3
        assert all(isinstance(card, Static) for card in cards)
