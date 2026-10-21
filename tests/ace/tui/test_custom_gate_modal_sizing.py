"""Responsive shell, footer, and preview-rail sizing for custom gates."""

from __future__ import annotations

from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.modals.custom_gate_modal import CustomGateModal

from ._custom_gate_modal_helpers import StyledGateTestApp, data, option


_LONG_NOTES = tuple(
    f"Context {index}: "
    + "The signed deployment is ready for review and every release check passed. " * 15
    for index in range(1, 8)
) + ("Shell command: " + "./scripts/verify-release --check " * 18,)


def _modal(
    *, preview: bool = False, notes: tuple[str, ...] | None = None
) -> CustomGateModal:
    return CustomGateModal(
        data(
            options=(option("approve"), option("cancel")),
            branches=(("approve",), ("cancel",)),
            preview_name="review.md" if preview else None,
            preview_text="# Review\n" if preview else None,
            notes=notes,
        )
    )


async def test_compact_width_scales_and_caps_at_120() -> None:
    modal = _modal()
    async with StyledGateTestApp().run_test(size=(264, 78)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        shell = modal.query_one("#custom-gate-container")
        assert shell.region.width == 120

        for width, height, expected in (
            (160, 50, 120),
            (120, 40, 90),
            (100, 30, 75),
            (80, 24, 60),
        ):
            await pilot.resize_terminal(width, height)
            await pilot.pause()
            assert shell.region.width == expected

        await pilot.resize_terminal(60, 18)
        await pilot.pause()
        assert shell.region.width <= 57


async def test_compact_scroll_fits_and_footer_stays_inside_shell() -> None:
    modal = _modal(notes=_LONG_NOTES)
    async with StyledGateTestApp().run_test(size=(160, 50)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        shell = modal.query_one("#custom-gate-container")
        footer = modal.query_one("#custom-gate-footer", Static)
        scroll = modal.query_one("#custom-gate-review-scroll", VerticalScroll)

        for width, height in ((80, 24), (100, 30), (120, 40), (160, 50)):
            await pilot.resize_terminal(width, height)
            await pilot.pause()
            assert footer.region.bottom <= (
                shell.region.bottom - shell.styles.gutter.bottom
            )

        assert scroll.size.height > 30


async def test_short_gate_stays_compact_and_footer_fits_at_80x24() -> None:
    modal = _modal()
    async with StyledGateTestApp().run_test(size=(80, 24)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        shell = modal.query_one("#custom-gate-container")
        footer = modal.query_one("#custom-gate-footer", Static)
        assert footer.region.bottom <= shell.region.bottom - shell.styles.gutter.bottom

    wide_modal = _modal()
    async with StyledGateTestApp().run_test(size=(264, 78)) as pilot:
        pilot.app.push_screen(wide_modal)
        await pilot.pause()
        wide_shell = wide_modal.query_one("#custom-gate-container")
        assert wide_shell.size.height < 40


async def test_compact_scroll_refits_after_resize() -> None:
    modal = _modal(notes=_LONG_NOTES)
    async with StyledGateTestApp().run_test(size=(160, 50)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        shell = modal.query_one("#custom-gate-container")
        footer = modal.query_one("#custom-gate-footer", Static)
        scroll = modal.query_one("#custom-gate-review-scroll", VerticalScroll)

        await pilot.resize_terminal(80, 24)
        await pilot.pause()
        assert footer.region.bottom <= shell.region.bottom - shell.styles.gutter.bottom

        short_height = scroll.size.height
        await pilot.resize_terminal(160, 50)
        await pilot.pause()
        assert scroll.size.height > short_height


async def test_preview_gate_does_not_get_compact_scroll_limit() -> None:
    modal = _modal(preview=True, notes=_LONG_NOTES)
    async with StyledGateTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        scroll = modal.query_one("#custom-gate-review-scroll", VerticalScroll)
        assert scroll.styles.max_height is None


async def test_custom_preview_rail_grows_and_stacks_at_narrow_breakpoint() -> None:
    modal = _modal(preview=True)
    async with StyledGateTestApp().run_test(size=(200, 56)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        body = modal.query_one(".gate-review-body")
        rail = modal.query_one(".gate-review-body > .gate-review-actions")
        assert 42 < rail.region.width <= 72

        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        assert rail.region.width == 42

        await pilot.resize_terminal(90, 40)
        await pilot.pause()
        assert rail.styles.dock == "bottom"
        assert rail.region.width == body.region.width
