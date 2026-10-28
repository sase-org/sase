"""Layout for the tall gate input panel (unclipped sections, fitted body)."""

from __future__ import annotations

from typing import Any

from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.gate_input_panel import GateInputPanel
from sase.ace.tui.modals.gate_input_panel_model import build_gate_input_request
from sase.ace.tui.modals.gate_input_panel_sections import GateInputSection
from sase.notification_gates.models import GateOption

from ._custom_gate_modal_helpers import StyledGateTestApp, wait_for_terminal


def _twelve_inputs() -> list[dict[str, Any]]:
    inputs: list[dict[str, Any]] = []
    for index in range(1, 10):
        inputs.append(
            {
                "id": f"f{index:02d}",
                "label": f"F-{index:02d}",
                "type": "enum",
                "choices": ["a", "b", "c", "d", "e"],
                "required": True,
                "help": f"Help for F-{index:02d}",
            }
        )
    inputs.append({"id": "flag", "label": "Flag", "type": "bool", "required": True})
    inputs.append({"id": "notes", "label": "Notes", "type": "text"})
    inputs.append(
        {"id": "secret_note", "label": "Secret", "type": "text", "secret": True}
    )
    return inputs


def _tall_options() -> tuple[GateOption, GateOption]:
    inputs = _twelve_inputs()
    attest = GateOption.from_mapping(
        {
            "id": "attest",
            "label": "Attest",
            "command": {"argv": ["commands/attest"]},
            "inputs": inputs,
        },
        0,
    )
    approve = GateOption.from_mapping(
        {
            "id": "approve",
            "label": "Approve",
            "command": {"argv": ["commands/approve"]},
            "inputs": inputs,
        },
        1,
    )
    return attest, approve


def _tall_request(branch_label: str = "Attest and approve"):
    attest, approve = _tall_options()
    return build_gate_input_request(
        (attest, approve),
        ("attest", "approve"),
        branch_index=0,
        branch_label=branch_label,
        feedback_mode="optional",  # type: ignore[arg-type]
    )


async def _wait_for_panel(
    pilot: Any, width: int, height: int, panel: GateInputPanel
) -> None:
    await wait_for_terminal(pilot, width, height)

    def panel_mounted() -> bool:
        return bool(panel.query("#gate-input-container"))

    await wait_for(pilot, panel_mounted)


async def test_tall_section_is_not_clipped_and_body_scrolls() -> None:
    for width, height in ((140, 80), (120, 40)):
        request = _tall_request()
        panel = GateInputPanel(request)
        app = StyledGateTestApp()
        async with app.run_test(size=(width, height)) as pilot:
            app.push_screen(panel)
            await _wait_for_panel(pilot, width, height, panel)

            body = panel.query_one("#gate-input-body", VerticalScroll)

            def layout_settled(
                _panel: GateInputPanel = panel,
                _body: VerticalScroll = body,
            ) -> bool:
                sections = list(_panel.query(".gate-input-section"))
                if not sections:
                    return False
                return (
                    all(
                        section.size.height == section.virtual_size.height
                        for section in sections
                    )
                    and _body.max_scroll_y > 0
                )

            await wait_for(pilot, layout_settled)
            for section in panel.query(".gate-input-section"):
                assert section.size.height == section.virtual_size.height
            assert body.max_scroll_y > 0


async def test_tab_reaches_every_field_and_scrolls_it_into_view() -> None:
    request = _tall_request()
    panel = GateInputPanel(request)
    app = StyledGateTestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        app.push_screen(panel)
        await _wait_for_panel(pilot, 120, 40, panel)
        body = panel.query_one("#gate-input-body", VerticalScroll)

        field_ids: list[str] = []
        for section in panel.query(GateInputSection):
            field_ids.extend(section.control_ids())
        assert len(field_ids) == 12
        body_ids = set(field_ids)
        if panel.query("#gate-input-note"):
            body_ids.add("gate-input-note")
        total_steps = len(field_ids) + (1 if "gate-input-note" in body_ids else 0) + 2

        await wait_for(pilot, lambda: panel.focused is not None)
        seen: set[str] = set()
        focused = panel.focused
        assert focused is not None and focused.id is not None
        seen.add(focused.id)
        if focused.id in body_ids:
            assert body.region.contains_region(focused.region)

        for _ in range(total_steps):
            await pilot.press("tab")
            await pilot.pause()
            focused = panel.focused
            assert focused is not None and focused.id is not None
            seen.add(focused.id)
            if focused.id in body_ids:
                assert body.region.contains_region(focused.region), (
                    f"{focused.id} outside body {focused.region} vs {body.region}"
                )

        for field_id in field_ids:
            assert field_id in seen


async def test_body_fits_shell_and_footer_stays_inside() -> None:
    request = _tall_request()
    panel = GateInputPanel(request)
    app = StyledGateTestApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app.push_screen(panel)
        await _wait_for_panel(pilot, 80, 24, panel)
        shell = panel.query_one("#gate-input-container")
        body = panel.query_one("#gate-input-body", VerticalScroll)
        footer = panel.query_one("#gate-input-footer", Static)

        def footer_fits() -> bool:
            return footer.region.bottom <= (
                shell.region.bottom - shell.styles.gutter.bottom
            )

        await wait_for(pilot, footer_fits)
        assert footer_fits()

        for width, height in ((120, 40), (140, 80)):
            await pilot.resize_terminal(width, height)
            await wait_for_terminal(pilot, width, height)
            await wait_for(pilot, footer_fits)
            assert footer_fits()

        await wait_for(pilot, lambda: body.size.height > 32)
        assert body.size.height > 32


async def test_short_panel_stays_compact() -> None:
    option = GateOption.from_mapping(
        {
            "id": "deploy",
            "label": "Deploy",
            "command": {"argv": ["commands/deploy"]},
            "inputs": [{"id": "env", "label": "Env", "type": "line", "required": True}],
        },
        0,
    )
    request = build_gate_input_request(
        (option,),
        ("deploy",),
        branch_index=0,
        branch_label="Deploy",
        feedback_mode="disabled",  # type: ignore[arg-type]
    )
    panel = GateInputPanel(request)
    app = StyledGateTestApp()
    async with app.run_test(size=(140, 80)) as pilot:
        app.push_screen(panel)
        await _wait_for_panel(pilot, 140, 80, panel)
        shell = panel.query_one("#gate-input-container")

        await wait_for(pilot, lambda: shell.size.height < 25)
        assert shell.size.height < 25
