"""Footer hints for the plan approval modal.

The hint line is a projection of three things a reviewer cannot otherwise see
at a glance: the configured gate keymap, which branch is primary, and whether
the gate declares path inputs worth a completion key.
"""

from __future__ import annotations

from rich.text import Text

from ..keymaps import GateModalKeymaps, key_display_name
from .gate_branch_controls import GateBranchData, gate_declares_inputs
from .gate_primary_footer import primary_action_badge
from .plan_approval_gate_data import HOST_COLLECTED_PROPERTIES


def plan_approval_footer_text(
    gate: GateBranchData,
    keys: GateModalKeymaps,
    action_hints: Text,
) -> Text:
    """Return footer hints with the declared primary action emphasized."""
    hints = Text()
    hints.append(
        f"{key_display_name(keys.next_control)}/"
        f"{key_display_name(keys.previous_control)}",
        style="green",
    )
    hints.append("=Navigate  ")
    hints.append(key_display_name(keys.toggle_option), style="green")
    hints.append("=Toggle  ")
    hints.append_text(primary_action_badge(gate, keys.submit_primary))
    hints.append("  ")
    hints.append(key_display_name(keys.submit_branch), style="green")
    hints.append("=Submit  ")
    _has_inputs, has_path = gate_declares_inputs(
        gate.options, HOST_COLLECTED_PROPERTIES
    )
    if has_path:
        hints.append("^t", style="green")
        hints.append("=Complete path  ")
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
