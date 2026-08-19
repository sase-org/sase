"""Input panel and feedback coverage for the shared gate modal."""

from __future__ import annotations

from textual.widgets import Button

from sase.ace.testing import wait_for
from sase.ace.tui.keymaps import GateModalKeymaps
from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalResult,
)
from sase.ace.tui.modals.gate_input_panel import GateInputPanel
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.notification_gates.models import GateOption

from ._custom_gate_modal_helpers import (
    GateTestApp,
    StyledGateTestApp,
    data,
    open_panel,
    option,
    task_triage_data,
)


async def test_declared_input_value_reaches_resolved_option_inputs() -> None:
    results: list[CustomGateModalResult | None] = []
    deploy = GateOption.from_mapping(
        {
            "id": "deploy",
            "label": "Deploy",
            "icon": "🚀",
            "default_selected": True,
            "feedback": "disabled",
            "command": {"argv": ["commands/deploy"]},
            "inputs": [
                {
                    "id": "target_env",
                    "label": "Target environment",
                    "type": "line",
                    "required": True,
                }
            ],
        },
        0,
    )
    modal = CustomGateModal(data(options=(deploy,), branches=(("deploy",),)))

    async with GateTestApp().run_test(size=(100, 40)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("1")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        panel = open_panel(pilot.app)
        field = panel.query_one("#gate-input-deploy-input-0", SingleLineVimTextArea)
        field.text = "staging"
        await pilot.pause()
        await pilot.press("ctrl+s")
        await wait_for(pilot, lambda: bool(results))

    assert results == [
        CustomGateModalResult(
            ("deploy",),
            None,
            option_inputs={"deploy": {"target_env": "staging"}},
        )
    ]


async def test_numbered_shortcut_focuses_required_enum_then_submits() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        data(
            options=(
                option("approve", icon="✅"),
                option("close", icon="✅"),
                option(
                    "snooze",
                    icon="💤",
                    inputs=[
                        {
                            "id": "wake_after",
                            "label": "Wake after",
                            "type": "enum",
                            "required": True,
                            "choices": [
                                {"value": "tomorrow", "label": "Tomorrow"},
                                {"value": "next_week", "label": "Next week"},
                            ],
                        },
                        {
                            "id": "note",
                            "label": "Note",
                            "type": "line",
                            "required": False,
                        },
                    ],
                ),
            ),
            branches=(("approve",), ("close",), ("snooze",)),
            preview_name="triage.md",
            preview_text="# Task triage\n",
            notes=tuple(f"Context line {index}" for index in range(16)),
        )
    )
    app = StyledGateTestApp()

    async with app.run_test(size=(120, 24)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("j")
        assert modal.query_one("#gate-singleton-1", Button).has_focus

        await pilot.press("3")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        panel = open_panel(app)
        wake_after = panel.query_one("#gate-input-snooze-input-0", Button)

        assert results == []
        assert wake_after.has_focus
        assert (
            "Fix the highlighted inputs before submitting",
            "warning",
        ) not in app.recorded_notifications

        wake_after.press()
        await pilot.pause()
        await pilot.press("ctrl+s")
        await wait_for(pilot, lambda: bool(results))

    assert results == [
        CustomGateModalResult(
            ("snooze",),
            None,
            option_inputs={"snooze": {"wake_after": "tomorrow"}},
        )
    ]


async def test_task_triage_shortcut_focuses_duration_line_then_submits() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(task_triage_data())
    app = StyledGateTestApp()

    async with app.run_test(size=(120, 24)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()

        await pilot.press("3")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        panel = open_panel(app)
        duration = panel.query_one("#gate-input-snooze-input-0", SingleLineVimTextArea)
        await wait_for(pilot, lambda: duration.has_focus)

        assert results == []
        assert (
            "Fix the highlighted inputs before submitting",
            "warning",
        ) not in app.recorded_notifications

        duration.text = "3d +2"
        await pilot.press("ctrl+s")
        await wait_for(pilot, lambda: bool(results))

    assert results == [
        CustomGateModalResult(
            ("snooze",),
            None,
            option_inputs={"snooze": {"duration": "3d +2"}},
        )
    ]


async def test_required_feedback_blocks_until_entered() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        data(
            options=(option("revise", feedback="required", icon="💬"),),
            branches=(("revise",),),
        )
    )

    async with GateTestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("1")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        panel = open_panel(pilot.app)
        assert results == []
        feedback = panel.query_one("#gate-input-note", VimTextArea)
        assert feedback.has_focus
        feedback.text = "123 Please revise the rollout."
        await pilot.press("ctrl+s")
        await wait_for(pilot, lambda: bool(results))

    assert results == [
        CustomGateModalResult(("revise",), "123 Please revise the rollout.")
    ]


def test_footer_omits_open_inputs_when_gate_has_no_inputs_or_note() -> None:
    modal = CustomGateModal(
        data(
            options=(option("proceed", icon="✅"),),
            branches=(("proceed",),),
        )
    )

    footer = modal._footer_text().plain
    assert "note/inputs" not in footer
    assert "^t complete path" not in footer


async def test_remapped_open_inputs_opens_panel_and_appears_in_footer() -> None:
    modal = CustomGateModal(
        data(
            options=(option("proceed", icon="✅", feedback="optional"),),
            branches=(("proceed",),),
        ),
        gate_keymaps=GateModalKeymaps(open_inputs="o"),
    )

    footer = modal._footer_text().plain
    assert "o note/inputs" in footer
    assert "i note/inputs" not in footer
    assert "^t complete path" not in footer

    async with GateTestApp().run_test(size=(100, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("o")
        await wait_for(pilot, lambda: isinstance(pilot.app.screen, GateInputPanel))
        assert open_panel(pilot.app).query("#gate-input-note")
