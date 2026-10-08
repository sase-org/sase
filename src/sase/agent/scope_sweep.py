"""Sweep leaked processes out of an agent runner's own systemd scope.

Contract: an agent runner's ``sase-agent-*`` scope bounds the lifetime of
every process the agent starts. Work that must outlive the runner must escape
through :func:`sase.detach_scope.detach_scope` into its own scope. Anything
still in the scope that is not the runner, not one of the runner's live
descendants, and not a spared shared daemon is a leak and gets terminated.

This module is the seam callers import; the work lives in
``_scope_sweep_types`` (shared constants and types), ``_scope_sweep_core``
(member reads, selection rule, and signal execution),
``_scope_sweep_own`` (runner own-scope teardown), and ``_scope_sweep_reap``
(orphaned-scope reaper backstop).
"""

from __future__ import annotations

from sase.agent._scope_sweep_own import (
    sweep_own_agent_scope as sweep_own_agent_scope,
)
from sase.agent._scope_sweep_reap import (
    reap_orphaned_agent_scopes as reap_orphaned_agent_scopes,
)
from sase.agent._scope_sweep_types import (
    AGENT_SCOPE_UNIT_PREFIX as AGENT_SCOPE_UNIT_PREFIX,
)
from sase.agent._scope_sweep_types import (
    DEFAULT_SPARE_PROCESS_PATTERNS as DEFAULT_SPARE_PROCESS_PATTERNS,
)
from sase.agent._scope_sweep_types import (
    RUNNER_SCRIPT_NAME as RUNNER_SCRIPT_NAME,
)

__all__ = [
    "AGENT_SCOPE_UNIT_PREFIX",
    "DEFAULT_SPARE_PROCESS_PATTERNS",
    "RUNNER_SCRIPT_NAME",
    "reap_orphaned_agent_scopes",
    "sweep_own_agent_scope",
]
