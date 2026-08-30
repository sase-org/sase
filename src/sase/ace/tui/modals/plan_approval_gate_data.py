"""Static bindings, keymap defaults, and the fallback gate model for plan review.

A plan gate normally arrives fully described by the notification layer, but
direct and legacy callers open
:class:`~sase.ace.tui.modals.plan_approval_modal.PlanApprovalModal` with little
more than a plan file. The branch model those callers get is built here, beside
the constants that decide which keys the modal owns and which properties its
host already collects.
"""

from __future__ import annotations

from sase.notification_gates.models import GateGroup, GateOption
from sase.plan_approval_choices import PlanApprovalModalChoice as PlanApprovalChoice
from sase.plan_gate import (
    TALE_PLAN_SUBMIT_GROUP,
    PlanGateTier,
    plan_gate_option_icon,
    plan_gate_option_label,
)

from ..keymaps import GateModalKeymaps, load_builtin_gate_defaults
from .gate_branch_controls import GateBranchData

PLAN_GATE_STATIC_BINDINGS = [
    ("escape", "cancel", "Cancel"),
    ("q", "cancel", "Cancel"),
    ("d", "debug_view", "Debug"),
    ("c", "custom", "Custom"),
    ("y", "copy_plan_path", "Copy path"),
    ("Y", "copy_plan", "Copy all contents"),
    ("ctrl+d", "scroll_down", "Scroll down"),
    ("ctrl+u", "scroll_up", "Scroll up"),
    ("g", "scroll_to_top", "Top"),
    ("G", "scroll_to_bottom", "Bottom"),
]
DEFAULT_GATE_KEYMAPS = GateModalKeymaps(**load_builtin_gate_defaults())
#: Approval fields are already collected by the "c" ApproveOptionsModal
#: (`coder_prompt`/`coder_model`/`wait`) and by the host's own epic launch
#: choice (`epic_launch_mode`), so the raw-schema escape hatch must not
#: duplicate them with a YAML box on every plan and epic gate.
HOST_COLLECTED_PROPERTIES = frozenset(
    {"feedback", "coder_prompt", "coder_model", "epic_launch_mode", "wait"}
)


def default_plan_gate_data(default_choice: PlanApprovalChoice) -> GateBranchData:
    """Build a display-only branch model for direct/legacy modal callers."""
    tier: PlanGateTier = "epic" if default_choice == "epic" else "tale"
    definitions: tuple[tuple[str, str, str, str], ...] = (
        (
            "approve",
            plan_gate_option_label("approve", tier=tier),
            plan_gate_option_icon("approve", tier=tier),
            "disabled",
        ),
        (
            "commit",
            plan_gate_option_label("commit", tier=tier),
            plan_gate_option_icon("commit", tier=tier),
            "disabled",
        ),
        (
            "reject",
            plan_gate_option_label("reject", tier=tier),
            plan_gate_option_icon("reject", tier=tier),
            "disabled",
        ),
        (
            "feedback",
            plan_gate_option_label("feedback", tier=tier),
            plan_gate_option_icon("feedback", tier=tier),
            "required",
        ),
    )
    if default_choice == "epic":
        definitions = tuple(item for item in definitions if item[0] != "commit")
        query = "approve OR reject OR feedback"
        branches: tuple[tuple[str, ...], ...] = (
            ("approve",),
            ("reject",),
            ("feedback",),
        )
        groups: tuple[GateGroup, ...] = ()
    else:
        query = "(approve AND commit) OR reject OR feedback"
        branches = (("approve", "commit"), ("reject",), ("feedback",))
        groups = (TALE_PLAN_SUBMIT_GROUP,)
    options = tuple(
        GateOption.from_mapping(
            {
                "id": option_id,
                "label": label,
                "icon": icon,
                "command": {"argv": [f"commands/{option_id}"]},
                "feedback": feedback,
            },
            index,
        )
        for index, (option_id, label, icon, feedback) in enumerate(definitions)
    )
    return GateBranchData(
        query=query,
        options=options,
        groups=groups,
        branches=branches,
        primary_branch=branches[0],
    )


__all__ = [
    "DEFAULT_GATE_KEYMAPS",
    "HOST_COLLECTED_PROPERTIES",
    "PLAN_GATE_STATIC_BINDINGS",
    "default_plan_gate_data",
]
