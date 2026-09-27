"""Behavioral coverage for the update failure-report modal."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Static

from sase.ace._update_attempts_model import UpdateFailure
from sase.ace.tui.modals import UpdateFailureModal

_ROOT = Path(__file__).resolve().parents[3]


class _ModalHost(App[None]):
    CSS_PATH = _ROOT / "src/sase/ace/tui/styles.tcss"

    def compose(self) -> ComposeResult:
        yield from ()


def _failure(**kwargs: object) -> UpdateFailure:
    values: dict[str, object] = {
        "attempt_id": "a1",
        "label": "sase update",
        "proc_type": "comprehensive-update",
        "stage": "apply",
        "started_at": 1700000000.0,
        "finished_at": 1700000010.0,
        "error": "boom",
        "output_tail": "line one\nline two",
        "interrupted": False,
    }
    values.update(kwargs)
    return UpdateFailure(**values)  # type: ignore[arg-type]


def _plain(static: Static) -> str:
    rendered = static.render()
    if isinstance(rendered, Text):
        return rendered.plain
    return str(rendered)


async def test_renders_meta_error_output_and_red_frame() -> None:
    async with _ModalHost().run_test(size=(100, 40)) as pilot:
        modal = UpdateFailureModal(_failure())
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert "sase update · apply · failed" in _plain(
            modal.query_one("#update-failure-meta", Static)
        )
        assert "boom" in _plain(modal.query_one("#update-failure-error", Static))
        body = _plain(modal.query_one("#update-failure-body", Static))
        assert "line one" in body and "line two" in body
        assert "last output" in _plain(
            modal.query_one("#update-failure-output-label", Static)
        )
        assert "u open Update · d dismiss · y copy · q close" in _plain(
            modal.query_one("#update-failure-footer", Static)
        )
        container = modal.query_one("#update-failure-container", Container)
        assert "✗ Update failed" in str(container.border_title)
        style, color = container.styles.border_top
        assert style == "double"
        assert (color.r, color.g, color.b) == (255, 95, 95)


async def test_interrupted_attempt_shows_explanation() -> None:
    async with _ModalHost().run_test(size=(100, 40)) as pilot:
        modal = UpdateFailureModal(_failure(interrupted=True, output_tail=""))
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert "interrupted" in _plain(modal.query_one("#update-failure-meta", Static))
        assert 'ACE exited before "sase update" finished' in _plain(
            modal.query_one("#update-failure-error", Static)
        )
        container = modal.query_one("#update-failure-container", Container)
        assert "✗ Update interrupted" in str(container.border_title)


async def test_empty_output_shows_placeholder() -> None:
    async with _ModalHost().run_test(size=(100, 40)) as pilot:
        modal = UpdateFailureModal(_failure(output_tail=""))
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert "No output was captured." in _plain(
            modal.query_one("#update-failure-body", Static)
        )


async def test_markup_like_output_renders_literally() -> None:
    async with _ModalHost().run_test(size=(100, 40)) as pilot:
        modal = UpdateFailureModal(_failure(output_tail="[bold]hi[/bold]"))
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert "[bold]hi[/bold]" in _plain(
            modal.query_one("#update-failure-body", Static)
        )


async def test_dismiss_open_and_close_keys_return_results() -> None:
    for key, expected in [("d", "dismiss"), ("u", "open_update"), ("q", None)]:
        dismissed: list[object] = []
        async with _ModalHost().run_test(size=(100, 40)) as pilot:
            pilot.app.push_screen(
                UpdateFailureModal(_failure()), callback=dismissed.append
            )
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()

        assert dismissed == [expected]


def test_copy_text_combines_error_and_output() -> None:
    modal = UpdateFailureModal(_failure())

    assert modal._copy_text() == "boom\n\nline one\nline two"
    assert UpdateFailureModal(_failure(output_tail=""))._copy_text() == "boom"
