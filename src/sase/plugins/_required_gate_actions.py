"""Host effects a human's PluginsRequired decision authorizes.

Install already ran inside the option command so a failure could leave the
gate pending. The host effect only restarts axe after a successful install
that changed installed code, matching ``sase plugin install``.
"""

from __future__ import annotations

from sase.plugins._required_gate_response import PluginsRequiredResponse
from sase.plugins._required_gate_spec import PLUGINS_REQUIRED_INSTALL_OPTION_ID


def apply_plugins_required_decision(decision: PluginsRequiredResponse) -> None:
    """Restart axe after a successful install that changed installed code."""
    if decision.action != PLUGINS_REQUIRED_INSTALL_OPTION_ID or not decision.changed:
        return
    from sase.axe.process import is_axe_running, restart_axe_daemon_result
    from sase.main.update_restart import restart_after_update

    restart_after_update(
        changed=True,
        axe_running_fn=is_axe_running,
        restart_axe_fn=restart_axe_daemon_result,
        source="sase plugin install",
    )
