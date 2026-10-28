"""Responsive shell, footer, and preview-rail sizing for custom gates."""

from __future__ import annotations

from collections.abc import Callable

from textual.containers import VerticalScroll
from textual.pilot import Pilot
from textual.widget import Widget
from textual.widgets import Static

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.modals.custom_gate_modal import CustomGateModal
from sase.ace.tui.modals.gate_branch_controls import GateBranchControls
from sase.notification_gates.models import GateGroup

from ._custom_gate_modal_helpers import (
    StyledGateTestApp,
    data,
    option,
    wait_for_terminal,
)


_LONG_NOTES = tuple(
    f"Context {index}: "
    + "The signed deployment is ready for review and every release check passed. " * 15
    for index in range(1, 8)
) + ("Shell command: " + "./scripts/verify-release --check " * 18,)


async def _wait_for_mounted_modal(
    pilot: Pilot[None], modal: CustomGateModal, width: int, height: int
) -> None:
    await wait_for_terminal(pilot, width, height)

    def shell_mounted() -> bool:
        return bool(modal.query("#custom-gate-container"))

    await wait_for(pilot, shell_mounted)


async def _resize_and_wait(pilot: Pilot[None], width: int, height: int) -> None:
    await pilot.resize_terminal(width, height)
    await wait_for_terminal(pilot, width, height)


def _footer_fits_inside_shell(footer: Widget, shell: Widget) -> Callable[[], bool]:
    def footer_fits() -> bool:
        return footer.region.bottom <= (
            shell.region.bottom - shell.styles.gutter.bottom
        )

    return footer_fits


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
        await _wait_for_mounted_modal(pilot, modal, 264, 78)

        shell = modal.query_one("#custom-gate-container")
        await wait_for(pilot, lambda: shell.region.width == 120)
        assert shell.region.width == 120

        for width, height, expected in (
            (160, 50, 120),
            (120, 40, 90),
            (100, 30, 75),
            (80, 24, 60),
        ):
            await _resize_and_wait(pilot, width, height)

            def shell_width_matches(expected_width: int = expected) -> bool:
                return shell.region.width == expected_width

            await wait_for(pilot, shell_width_matches)
            assert shell.region.width == expected

        await _resize_and_wait(pilot, 60, 18)
        await wait_for(pilot, lambda: shell.region.width <= 57)
        assert shell.region.width <= 57


async def test_compact_scroll_fits_and_footer_stays_inside_shell() -> None:
    modal = _modal(notes=_LONG_NOTES)
    async with StyledGateTestApp().run_test(size=(160, 50)) as pilot:
        pilot.app.push_screen(modal)
        await _wait_for_mounted_modal(pilot, modal, 160, 50)

        shell = modal.query_one("#custom-gate-container")
        footer = modal.query_one("#custom-gate-footer", Static)
        scroll = modal.query_one("#custom-gate-review-scroll", VerticalScroll)
        footer_fits = _footer_fits_inside_shell(footer, shell)

        for width, height in ((80, 24), (100, 30), (120, 40), (160, 50)):
            await _resize_and_wait(pilot, width, height)
            await wait_for(pilot, footer_fits)
            assert footer_fits()

        await wait_for(pilot, lambda: scroll.size.height > 30)
        assert scroll.size.height > 30


async def test_short_gate_stays_compact_and_footer_fits_at_80x24() -> None:
    modal = _modal()
    async with StyledGateTestApp().run_test(size=(80, 24)) as pilot:
        pilot.app.push_screen(modal)
        await _wait_for_mounted_modal(pilot, modal, 80, 24)

        shell = modal.query_one("#custom-gate-container")
        footer = modal.query_one("#custom-gate-footer", Static)
        footer_fits = _footer_fits_inside_shell(footer, shell)
        await wait_for(pilot, footer_fits)
        assert footer_fits()

    wide_modal = _modal()
    async with StyledGateTestApp().run_test(size=(264, 78)) as pilot:
        pilot.app.push_screen(wide_modal)
        await _wait_for_mounted_modal(pilot, wide_modal, 264, 78)
        wide_shell = wide_modal.query_one("#custom-gate-container")
        await wait_for(pilot, lambda: wide_shell.size.height < 40)
        assert wide_shell.size.height < 40


async def test_compact_scroll_refits_after_resize() -> None:
    modal = _modal(notes=_LONG_NOTES)
    async with StyledGateTestApp().run_test(size=(160, 50)) as pilot:
        pilot.app.push_screen(modal)
        await _wait_for_mounted_modal(pilot, modal, 160, 50)

        shell = modal.query_one("#custom-gate-container")
        footer = modal.query_one("#custom-gate-footer", Static)
        scroll = modal.query_one("#custom-gate-review-scroll", VerticalScroll)
        footer_fits = _footer_fits_inside_shell(footer, shell)

        await _resize_and_wait(pilot, 80, 24)
        await wait_for(pilot, footer_fits)
        assert footer_fits()

        short_height = scroll.size.height
        await _resize_and_wait(pilot, 160, 50)
        await wait_for(pilot, lambda: scroll.size.height > short_height)
        assert scroll.size.height > short_height


async def test_preview_gate_does_not_get_compact_scroll_limit() -> None:
    modal = _modal(preview=True, notes=_LONG_NOTES)
    async with StyledGateTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await _wait_for_mounted_modal(pilot, modal, 120, 40)

        scroll = modal.query_one("#custom-gate-review-scroll", VerticalScroll)
        await wait_for(pilot, lambda: scroll.styles.max_height is None)
        assert scroll.styles.max_height is None


@pytest.mark.parametrize("preview", [False, True])
async def test_jk_navigation_keeps_lower_branches_visible(preview: bool) -> None:
    options = (
        option("attest"),
        option("approve"),
        option("rotation_only"),
        option("defer"),
        option("reject"),
    )
    modal = CustomGateModal(
        data(
            options=options,
            branches=(
                ("attest", "approve"),
                ("rotation_only",),
                ("defer",),
                ("reject",),
            ),
            groups=(
                GateGroup(options=("attest", "approve"), label="Attest and approve"),
            ),
            preview_name="review.md" if preview else None,
            preview_text="# Review\n" if preview else None,
            notes=_LONG_NOTES,
        )
    )
    async with StyledGateTestApp().run_test(size=(160, 50)) as pilot:
        pilot.app.push_screen(modal)
        await _wait_for_mounted_modal(pilot, modal, 160, 50)
        if preview:
            rail = modal.query_one(
                ".gate-review-body > .gate-review-actions", VerticalScroll
            )
        else:
            rail = modal.query_one("#custom-gate-review-scroll", VerticalScroll)

        await wait_for(pilot, lambda: rail.scroll_y == 0)
        assert rail.scroll_y == 0

        branch = modal.query_one(GateBranchControls)
        control_ids = branch.visible_control_ids()
        seen: set[str] = set()
        for _ in control_ids:
            await pilot.press("j")
            await pilot.pause()
            focused = pilot.app.screen.focused
            assert focused is not None and focused.id is not None
            seen.add(focused.id)
            assert rail.region.contains_region(focused.region), (
                f"{focused.id} outside rail {focused.region} vs {rail.region}"
            )
        assert "gate-singleton-1" in seen
        assert "gate-singleton-2" in seen
        assert "gate-singleton-3" in seen


async def test_custom_preview_rail_grows_and_stacks_at_narrow_breakpoint() -> None:
    modal = _modal(preview=True)
    async with StyledGateTestApp().run_test(size=(200, 56)) as pilot:
        pilot.app.push_screen(modal)
        await _wait_for_mounted_modal(pilot, modal, 200, 56)

        body = modal.query_one(".gate-review-body")
        rail = modal.query_one(".gate-review-body > .gate-review-actions")
        await wait_for(pilot, lambda: 42 < rail.region.width <= 72)
        assert 42 < rail.region.width <= 72

        await _resize_and_wait(pilot, 120, 40)
        await wait_for(pilot, lambda: rail.region.width == 42)
        assert rail.region.width == 42

        await _resize_and_wait(pilot, 90, 40)

        def rail_stacks_full_width() -> bool:
            return (
                rail.styles.dock == "bottom" and rail.region.width == body.region.width
            )

        await wait_for(pilot, rail_stacks_full_width)
        assert rail.styles.dock == "bottom"
        assert rail.region.width == body.region.width
