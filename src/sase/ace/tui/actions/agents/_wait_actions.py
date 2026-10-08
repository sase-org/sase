"""Wait editing and persistence actions for agents.

This module remains the compatibility entry point for
:class:`AgentWaitActionsMixin`. Implementation lives in focused mixins so
each file stays small.
"""

from __future__ import annotations

from ._wait_apply import AgentWaitApplyMixin
from ._wait_modal import AgentWaitModalMixin
from ._wait_relaunch import AgentWaitRelaunchMixin
from ._wait_runner import AgentWaitRunnerMixin
from ._wait_helpers import TabName as TabName


class AgentWaitActionsMixin(
    AgentWaitModalMixin,
    AgentWaitApplyMixin,
    AgentWaitRunnerMixin,
    AgentWaitRelaunchMixin,
):
    """Mixin providing agent wait editing and persistence actions."""

    current_tab: TabName


__all__ = ["AgentWaitActionsMixin", "TabName"]
