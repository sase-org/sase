"""Footer hints for the plan approval modal.

The hint line is a projection of three things a reviewer cannot otherwise see
at a glance: the configured gate keymap, which branch is primary, and whether
the gate offers an input panel for a note or declared fields.
"""

from __future__ import annotations

from rich.text import Text

from ..keymaps import GateModalKeymaps, key_display_name, split_key_alternatives
from .gate_branch_controls import GateBranchData, gate_declares_inputs
from .gate_primary_footer import primary_action_badge
from .plan_approval_gate_data import HOST_COLLECTED_PROPERTIES


def _first_key_display(binding: str) -> str:
    """Return the display name of the first alternative in *binding*."""
    alternatives = split_key_alternatives(binding)
    if not alternatives:
        return ""
    return key_display_name(alternatives[0])


def plan_approval_footer_text(
    gate: GateBranchData,
    keys: GateModalKeymaps,
    action_hints: Text,
    *,
    has_decisions: bool = False,
    decision_focused: bool = False,
    sheet_open: bool = False,
    enter_badge: Text | None = None,
) -> Text:
    """Return footer hints with the declared primary action emphasized."""
    hints = Text()
    hints.append(
        f"{_first_key_display(keys.next_control)}/"
        f"{_first_key_display(keys.previous_control)}",
        style="green",
    )
    hints.append("=Navigate  ")
    if has_decisions and decision_focused:
        hints.append(
            f"{_first_key_display(keys.decision_prev)}/"
            f"{_first_key_display(keys.decision_next)}",
            style="green",
        )
        hints.append("=Choice  ")
        hints.append(key_display_name(keys.toggle_option), style="green")
        hints.append("=Cycle  ")
        hints.append(
            f"{_first_key_display(keys.decision_reset)}/"
            f"{_first_key_display(keys.decision_reset_all)}",
            style="green",
        )
        hints.append("=Reset  ")
    else:
        hints.append(key_display_name(keys.toggle_option), style="green")
        hints.append("=Toggle  ")
    if enter_badge is not None:
        hints.append_text(enter_badge)
    else:
        hints.append_text(primary_action_badge(gate, keys.submit_primary))
    hints.append("  ")
    hints.append(key_display_name(keys.submit_branch), style="green")
    hints.append("=Submit  ")
    if has_decisions:
        hints.append(_first_key_display(keys.decision_zoom), style="green")
        hints.append("=Back to plan  " if sheet_open else "=Sheet  ")
    has_inputs, _ = gate_declares_inputs(gate.options, HOST_COLLECTED_PROPERTIES)
    if has_inputs or any(option.feedback != "disabled" for option in gate.options):
        hints.append(key_display_name(keys.open_inputs), style="green")
        hints.append("=note/inputs  ")
    hints.append("c", style="green")
    hints.append("=Coder options  ")
    hints.append_text(action_hints)
    hints.append("y", style="cyan")
    hints.append("=Copy path  ")
    hints.append("Y", style="cyan")
    hints.append("=Copy all contents  ")
    hints.append("d", style="cyan")
    hints.append("=Debug  ")
    hints.append("q", style="dim")
    hints.append("=Cancel  |  Ctrl+D/U / g / G to scroll")
    return hints


__all__ = ["plan_approval_footer_text"]
