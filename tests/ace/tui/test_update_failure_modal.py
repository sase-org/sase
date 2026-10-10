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
        assert "u open Update · d dismiss · y copy · q/Esc close" in _plain(
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


async def test_single_scroll_region_contains_report() -> None:
    from textual.containers import VerticalScroll

    async with _ModalHost().run_test(size=(100, 40)) as pilot:
        modal = UpdateFailureModal(_failure())
        pilot.app.push_screen(modal)
        await pilot.pause()

        scroll = modal.query_one("#update-failure-scroll", VerticalScroll)
        assert scroll.query_one("#update-failure-meta", Static) is not None
        assert scroll.query_one("#update-failure-error", Static) is not None
        assert scroll.query_one("#update-failure-output-label", Static) is not None
        assert scroll.query_one("#update-failure-body", Static) is not None
        # Footer stays outside the scroll region with the title visible.
        assert modal.query_one("#update-failure-footer", Static) is not None
        assert modal.query_one("#update-failure-footer", Static).parent is not scroll


async def test_compact_report_has_no_scroll_hint() -> None:
    async with _ModalHost().run_test(size=(240, 70)) as pilot:
        modal = UpdateFailureModal(_failure())
        pilot.app.push_screen(modal)
        await pilot.pause()

        from textual.containers import Container

        container = modal.query_one("#update-failure-container", Container)
        assert int(container.styles.width.value) <= 90 + 2
        hint = modal.query_one("#update-failure-scroll-hint", Static)
        assert hint.display is False


async def test_long_command_widens_report() -> None:
    command = "git " + "x" * 160
    output = "\n".join(f"row {i}" for i in range(30))
    async with _ModalHost().run_test(size=(240, 70)) as pilot:
        modal = UpdateFailureModal(_failure(error=command, output_tail=output))
        pilot.app.push_screen(modal)
        await pilot.pause()

        from textual.containers import Container

        container = modal.query_one("#update-failure-container", Container)
        assert int(container.styles.width.value) > 90


async def test_overflow_shows_scroll_hint_and_pins_footer() -> None:
    output = "\n".join(f"output line {i} with some detail" for i in range(200))
    async with _ModalHost().run_test(size=(80, 24)) as pilot:
        modal = UpdateFailureModal(_failure(output_tail=output))
        pilot.app.push_screen(modal)
        await pilot.pause()

        hint = modal.query_one("#update-failure-scroll-hint", Static)
        assert hint.display is True
        assert "g/G" in _plain(hint)
        footer = _plain(modal.query_one("#update-failure-footer", Static))
        assert "u" in footer and "d" in footer and "y" in footer and "q" in footer


async def test_narrow_width_shortens_footer_labels() -> None:
    output = "\n".join(f"line {i}" for i in range(5))
    async with _ModalHost().run_test(size=(40, 12)) as pilot:
        modal = UpdateFailureModal(_failure(output_tail=output))
        pilot.app.push_screen(modal)
        await pilot.pause()

        footer = _plain(modal.query_one("#update-failure-footer", Static))
        assert "u" in footer and "d" in footer and "y" in footer and "q" in footer


async def test_half_page_step_is_at_least_one_row() -> None:
    async with _ModalHost().run_test(size=(40, 12)) as pilot:
        modal = UpdateFailureModal(_failure(output_tail="a\nb\nc"))
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal._half_page_step() >= 1  # noqa: SLF001


async def test_copy_text_ignores_wrapping_and_tabs() -> None:
    failure = _failure(error="boom", output_tail="a\tb\nline")
    modal = UpdateFailureModal(failure)

    assert modal._copy_text() == "boom\n\na\tb\nline"  # noqa: SLF001


async def test_scroll_keys_reach_top_and_bottom() -> None:
    from textual.containers import VerticalScroll

    output = "\n".join(f"line {i:03d}" for i in range(100))
    async with _ModalHost().run_test(size=(80, 24)) as pilot:
        modal = UpdateFailureModal(_failure(output_tail=output))
        pilot.app.push_screen(modal)
        await pilot.pause()

        scroll = modal.query_one("#update-failure-scroll", VerticalScroll)
        modal.action_scroll_to_bottom()
        await pilot.pause()
        assert scroll.is_vertical_scroll_end
        modal.action_scroll_to_top()
        await pilot.pause()
        assert int(scroll.scroll_y) == 0
