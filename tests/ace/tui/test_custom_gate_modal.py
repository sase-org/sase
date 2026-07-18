"""Interaction coverage for the shared branch-driven gate modal."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding
from textual.widgets import Button, Input

from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalData,
    CustomGateModalResult,
)
from sase.ace.tui.modals.gate_branch_controls import (
    GateBranchControls,
    GateBranchData,
)
from sase.notification_gates.models import GateGroup, GateOption


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False


def _option(
    option_id: str,
    *,
    label: str | None = None,
    icon: str | None = None,
    selected: bool = True,
    feedback: str = "disabled",
) -> GateOption:
    return GateOption.from_mapping(
        {
            "id": option_id,
            "label": label or option_id.title(),
            "icon": icon,
            "default_selected": selected,
            "feedback": feedback,
            "command": {"argv": [f"commands/{option_id}"]},
        },
        0,
    )


def _data(
    *,
    options: tuple[GateOption, ...],
    branches: tuple[tuple[str, ...], ...],
    groups: tuple[GateGroup, ...] = (),
) -> CustomGateModalData:
    return CustomGateModalData(
        request_id="custom-ace",
        sender="review-agent",
        icon="🛡️",
        notes=("Review guarded work.",),
        attachments=(),
        preview_name=None,
        preview_text=None,
        gate=GateBranchData(
            query="test query",
            options=options,
            groups=groups,
            branches=branches,
        ),
    )


async def test_singleton_button_resolves_its_option() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            options=(_option("proceed", icon="✅"), _option("cancel", icon="❌")),
            branches=(("proceed",), ("cancel",)),
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.click("#gate-singleton-0")
        await pilot.pause()

    assert results == [CustomGateModalResult(("proceed",), None)]


async def test_group_renders_defaults_toggles_and_configured_submit() -> None:
    results: list[CustomGateModalResult | None] = []
    group = GateGroup(
        options=("approve", "audit"),
        label="Approve guarded work",
        icon="✅",
    )
    modal = CustomGateModal(
        _data(
            options=(
                _option("approve", icon="✅"),
                _option("audit", icon="📝", selected=False),
                _option("reject", icon="❌"),
            ),
            branches=(("approve", "audit"), ("reject",)),
            groups=(group,),
        )
    )

    async with _TestApp().run_test(size=(100, 36)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        controls = modal.query_one(GateBranchControls)
        assert controls.selected_option_ids(0) == ("approve",)
        assert "⬜" in str(modal.query_one("#gate-option-0-1", Button).label)
        assert "Approve guarded work" in str(
            modal.query_one("#gate-group-submit-0", Button).label
        )

        modal.query_one("#gate-option-0-1", Button).press()
        await pilot.pause()
        modal.query_one("#gate-group-submit-0", Button).press()
        await pilot.pause()

    assert results == [CustomGateModalResult(("approve", "audit"), None)]


async def test_required_feedback_blocks_until_entered() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        _data(
            options=(_option("revise", feedback="required", icon="💬"),),
            branches=(("revise",),),
        )
    )

    async with _TestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        modal.query_one("#gate-singleton-0", Button).press()
        await pilot.pause()
        assert results == []
        feedback = modal.query_one("#gate-feedback-input", Input)
        feedback.value = "Please revise the rollout."
        modal.query_one("#gate-singleton-0", Button).press()
        await pilot.pause()

    assert results == [CustomGateModalResult(("revise",), "Please revise the rollout.")]


async def test_multiple_groups_start_collapsed_and_expand_one_at_a_time() -> None:
    options = tuple(_option(option_id) for option_id in ("a", "b", "c", "d"))
    modal = CustomGateModal(
        _data(
            options=options,
            branches=(("a", "b"), ("c", "d")),
            groups=(
                GateGroup(("a", "b"), "First", "1️⃣"),
                GateGroup(("c", "d"), "Second", "2️⃣"),
            ),
        )
    )

    async with _TestApp().run_test(size=(100, 36)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert modal.query_one("#gate-group-details-0").has_class("hidden")
        assert modal.query_one("#gate-group-details-1").has_class("hidden")

        await pilot.click("#gate-group-expand-1")
        await pilot.pause()
        assert modal.query_one("#gate-group-details-0").has_class("hidden")
        assert not modal.query_one("#gate-group-details-1").has_class("hidden")


def test_bindings_match_shared_branch_actions() -> None:
    actions = {
        binding.action if isinstance(binding, Binding) else binding[1]
        for binding in CustomGateModal.BINDINGS
    }
    assert {"next_control", "previous_control", "toggle_option"} <= actions
    assert {"activate_control", "submit_branch"} <= actions
    assert "next_choice" not in actions
