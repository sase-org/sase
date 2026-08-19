"""Branch selection and dispatch coverage for the shared gate modal."""

from __future__ import annotations

import pytest
from textual.binding import Binding
from textual.widgets import Button

from sase.ace.tui.keymaps import (
    GateModalKeymaps,
    build_gate_numbered_branch_bindings,
)
from sase.ace.tui.modals.custom_gate_modal import (
    CustomGateModal,
    CustomGateModalResult,
)
from sase.ace.tui.modals.gate_branch_controls import GateBranchControls
from sase.notification_gates.models import GateGroup

from ._custom_gate_modal_helpers import GateTestApp, data, option


async def test_singleton_button_resolves_its_option() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        data(
            options=(option("proceed", icon="✅"), option("cancel", icon="❌")),
            branches=(("proceed",), ("cancel",)),
        )
    )

    async with GateTestApp().run_test(size=(100, 34)) as pilot:
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
        data(
            options=(
                option("approve", icon="✅"),
                option("audit", icon="📝", selected=False),
                option("reject", icon="❌"),
            ),
            branches=(("approve", "audit"), ("reject",)),
            groups=(group,),
        )
    )

    async with GateTestApp().run_test(size=(100, 36)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        controls = modal.query_one(GateBranchControls)
        assert controls.selected_option_ids(0) == ("approve",)
        group_expand_label = str(modal.query_one("#gate-group-expand-0", Button).label)
        group_submit_label = str(modal.query_one("#gate-group-submit-0", Button).label)
        toggle_label = str(modal.query_one("#gate-option-0-1", Button).label)
        assert group_expand_label.startswith("1 ")
        assert group_submit_label.startswith("1 ")
        assert toggle_label.startswith("⬜")
        assert str(modal.query_one("#gate-singleton-1", Button).label).startswith("2 ")
        assert str(modal.query_one("#custom-gate-cancel", Button).label) == "Cancel"
        assert "Approve guarded work" in group_submit_label

        modal.query_one("#gate-option-0-1", Button).press()
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()

    assert results == [CustomGateModalResult(("approve", "audit"), None)]


@pytest.mark.parametrize(
    ("key", "expected_option_id"),
    [("1", "first"), ("2", "second"), ("3", "third")],
)
async def test_numbered_shortcuts_dispatch_canonical_branch_independent_of_focus(
    key: str,
    expected_option_id: str,
) -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        data(
            options=tuple(
                option(option_id) for option_id in ("first", "second", "third")
            ),
            branches=(("first",), ("second",), ("third",)),
        )
    )

    async with GateTestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("j")
        assert modal.query_one("#gate-singleton-1", Button).has_focus
        await pilot.press(key)
        await pilot.pause()

    assert results == [CustomGateModalResult((expected_option_id,), None)]


async def test_enter_submits_declared_primary_even_when_focus_is_elsewhere() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        data(
            options=(option("cancel", icon="❌"), option("proceed", icon="✅")),
            branches=(("cancel",), ("proceed",)),
            primary_branch=("proceed",),
        )
    )

    async with GateTestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        assert modal.query_one("#gate-singleton-0", Button).has_focus
        await pilot.press("enter")
        await pilot.pause()

    assert results == [CustomGateModalResult(("proceed",), None)]


async def test_remapped_primary_key_matches_footer_and_dispatch() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        data(
            options=(option("cancel", icon="❌"), option("proceed", icon="✅")),
            branches=(("cancel",), ("proceed",)),
            primary_branch=("proceed",),
        ),
        gate_keymaps=GateModalKeymaps(submit_primary="a"),
    )

    assert "a=Proceed" in modal._footer_text().plain

    async with GateTestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("a")
        await pilot.pause()

    assert results == [CustomGateModalResult(("proceed",), None)]


async def test_ctrl_s_still_submits_the_active_non_primary_branch() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        data(
            options=(option("proceed", icon="✅"), option("cancel", icon="❌")),
            branches=(("proceed",), ("cancel",)),
        )
    )

    async with GateTestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("j")
        await pilot.press("ctrl+s")
        await pilot.pause()

    assert results == [CustomGateModalResult(("cancel",), None)]


async def test_multiple_groups_expand_primary_and_switch_one_at_a_time() -> None:
    options = tuple(option(option_id) for option_id in ("a", "b", "c", "d"))
    modal = CustomGateModal(
        data(
            options=options,
            branches=(("a", "b"), ("c", "d")),
            groups=(
                GateGroup(("a", "b"), "First", "1️⃣"),
                GateGroup(("c", "d"), "Second", "2️⃣"),
            ),
        )
    )

    async with GateTestApp().run_test(size=(100, 36)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert not modal.query_one("#gate-group-details-0").has_class("hidden")
        assert modal.query_one("#gate-group-details-1").has_class("hidden")

        await pilot.click("#gate-group-expand-1")
        await pilot.pause()
        assert modal.query_one("#gate-group-details-0").has_class("hidden")
        assert not modal.query_one("#gate-group-details-1").has_class("hidden")


async def test_unassigned_digit_is_harmless_and_q_still_cancels() -> None:
    results: list[CustomGateModalResult | None] = []
    modal = CustomGateModal(
        data(options=(option("proceed"),), branches=(("proceed",),))
    )

    async with GateTestApp().run_test(size=(100, 34)) as pilot:
        pilot.app.push_screen(modal, results.append)
        await pilot.pause()
        await pilot.press("9")
        await pilot.pause()
        assert results == []
        await pilot.press("q")
        await pilot.pause()

    assert results == [None]


def test_bindings_match_shared_branch_actions() -> None:
    actions = {
        binding.action if isinstance(binding, Binding) else binding[1]
        for binding in CustomGateModal.BINDINGS
    }
    assert {"next_control", "previous_control", "toggle_option"} <= actions
    assert {"submit_primary", "submit_branch", "open_inputs"} <= actions
    assert {f"submit_numbered_branch({index})" for index in range(9)} <= actions
    assert "next_choice" not in actions

    numbered = build_gate_numbered_branch_bindings()
    assert [binding.key for binding in numbered] == [
        str(index) for index in range(1, 10)
    ]
    assert all(not binding.show and not binding.priority for binding in numbered)
