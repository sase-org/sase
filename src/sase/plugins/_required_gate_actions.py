"""Host effects a human's PluginsRequired decision authorizes.

Install already ran inside the option command so a failure could leave the
gate pending. The host effect only restarts the scheduler after a successful
install that changed installed code, matching ``sase plugin install``.
"""

from __future__ import annotations

from sase.plugins._required_gate_response import PluginsRequiredResponse
from sase.plugins._required_gate_spec import PLUGINS_REQUIRED_INSTALL_OPTION_ID


def apply_plugins_required_decision(decision: PluginsRequiredResponse) -> None:
    """Restart the scheduler after a successful install that changed code."""
    if decision.action != PLUGINS_REQUIRED_INSTALL_OPTION_ID or not decision.changed:
        return
    from sase.axe.process import is_axe_running
    from sase.main.update_restart import restart_after_update

    restart_after_update(
        changed=True,
        scheduler_running_fn=is_axe_running,
        source="sase plugin install",
    )
