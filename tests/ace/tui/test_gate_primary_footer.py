"""Focused coverage for branch-driven gate footer presentation."""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from sase.ace.tui.keymaps import GateModalKeymaps
from sase.ace.tui.modals.custom_gate_modal import CustomGateModal, CustomGateModalData
from sase.ace.tui.modals.gate_branch_controls import GateBranchData
from sase.ace.tui.modals.gate_primary_footer import (
    _primary_branch_label,
    primary_action_badge,
)
from sase.ace.tui.modals.plan_approval_modal import PlanApprovalModal
from sase.notification_gates.models import GateGroup, GateOption
from sase.plan_approval_choices import PlanApprovalModalChoice


def _option(option_id: str, label: str) -> GateOption:
    return GateOption.from_mapping(
        {
            "id": option_id,
            "label": label,
            "command": {"argv": [f"commands/{option_id}"]},
        },
        0,
    )


def _gate(
    *,
    options: tuple[GateOption, ...],
    primary_branch: tuple[str, ...],
    groups: tuple[GateGroup, ...] = (),
) -> GateBranchData:
    return GateBranchData(
        query="footer test",
        options=options,
        groups=groups,
        branches=(primary_branch,),
        primary_branch=primary_branch,
    )


def _custom_modal(
    gate: GateBranchData,
    *,
    gate_keymaps: GateModalKeymaps | None = None,
) -> CustomGateModal:
    return CustomGateModal(
        CustomGateModalData(
            request_id="footer-test",
            title="Custom Gate",
            sender="review-agent",
            icon="",
            notes=(),
            attachments=(),
            preview_name=None,
            preview_text=None,
            gate=gate,
        ),
        gate_keymaps=gate_keymaps,
    )


@pytest.mark.parametrize(("choice", "label"), [("tale", "Tale"), ("epic", "Epic")])
def test_plan_footer_names_declared_primary_action(
    choice: PlanApprovalModalChoice, label: str
) -> None:
    modal = PlanApprovalModal(
        "approved-plan.md",
        default_choice=choice,
        plan_content="",
    )

    footer = modal._footer_text()

    assert f"Enter={label}" in footer.plain
    assert "Submit primary" not in footer.plain


def test_primary_branch_label_uses_singleton_group_and_defensive_fallback() -> None:
    approve = _option("approve", "Approve deployment")
    audit = _option("audit", "Record audit")
    singleton = _gate(options=(approve,), primary_branch=("approve",))
    grouped = _gate(
        options=(approve, audit),
        primary_branch=("approve", "audit"),
        groups=(GateGroup(("approve", "audit"), "Deploy signed build"),),
    )
    unlabeled_group = _gate(
        options=(approve, audit),
        primary_branch=("approve", "audit"),
        groups=(GateGroup(("approve", "audit")),),
    )

    assert _primary_branch_label(singleton) == "Approve deployment"
    assert _primary_branch_label(grouped) == "Deploy signed build"
    assert _primary_branch_label(unlabeled_group) == "Approve deployment"


def test_primary_badge_renders_markup_like_wide_label_literally_by_cells() -> None:
    full_label = "[deploy] " + "界" * 40
    gate = _gate(
        options=(_option("deploy", full_label),),
        primary_branch=("deploy",),
    )

    badge = primary_action_badge(gate, "enter")

    assert badge.plain.startswith(" Enter=[deploy] ")
    assert badge.plain.endswith("… ")
    assert badge.cell_len == cell_len(" Enter= ") + 32
    assert badge.cell_len < cell_len(f" Enter={full_label} ")


def test_primary_badge_styles_the_whole_key_action_and_leaves_hints_secondary() -> None:
    gate = _gate(
        options=(_option("approve", "Approve deployment"),),
        primary_branch=("approve",),
    )
    footer = _custom_modal(gate)._footer_text()
    primary_text = " Enter=Approve deployment "
    primary_start = footer.plain.index(primary_text)
    primary_end = primary_start + len(primary_text)

    primary_spans = [
        span
        for span in footer.spans
        if span.start <= primary_start and span.end >= primary_end
    ]

    assert len(primary_spans) == 1
    assert "bold" in str(primary_spans[0].style)
    assert "on #00d7af" in str(primary_spans[0].style).lower()
    navigate_index = footer.plain.index("navigate")
    assert not any(span.start <= navigate_index < span.end for span in footer.spans)


def test_custom_footer_uses_effective_primary_submit_key() -> None:
    gate = _gate(
        options=(_option("approve", "Approve deployment"),),
        primary_branch=("approve",),
    )
    modal = _custom_modal(
        gate,
        gate_keymaps=GateModalKeymaps(submit_primary="a"),
    )

    assert "a=Approve deployment" in modal._footer_text().plain
    assert "Enter=Approve deployment" not in modal._footer_text().plain
