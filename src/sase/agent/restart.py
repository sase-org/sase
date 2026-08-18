"""Plan and apply ``sase agent restart`` without touching ACE/TUI code.

Planning is read-only: every refusal is discovered before anything is killed.
Execution then stops the old row, wipes the reserved name, and launches the
rewritten prompt from the home directory so an untagged prompt cannot inherit
the operator's current workspace.

This module is the seam callers import; the work lives in
``_restart_planning`` (read-only plan), ``_restart_preview`` (display facts and
warnings), ``_restart_execute`` (the mutating half), ``_restart_recovery`` (the
``~/.sase/restarts`` bundle), and ``_restart_types`` (shared dataclasses).
"""

from __future__ import annotations

from sase.agent import _restart_execute as _execute
from sase.agent import _restart_planning as _planning
from sase.agent import _restart_preview as _preview
from sase.agent import _restart_types as _types

AgentRestartError = _types.AgentRestartError
AgentRestartOutcome = _types.AgentRestartOutcome
AgentRestartPlan = _types.AgentRestartPlan
AgentRestartPreview = _types.AgentRestartPreview
NameReuseSource = _types.NameReuseSource
ProgressFn = _types.ProgressFn

plan_agent_restart = _planning.plan_agent_restart
execute_agent_restart = _execute.execute_agent_restart
deletion_note = _preview.deletion_note
related_wipe_warning = _preview.related_wipe_warning
restart_needs_confirmation = _preview.restart_needs_confirmation
wipe_deletes_label = _preview.wipe_deletes_label

__all__ = [
    "AgentRestartError",
    "AgentRestartOutcome",
    "AgentRestartPlan",
    "AgentRestartPreview",
    "NameReuseSource",
    "ProgressFn",
    "deletion_note",
    "execute_agent_restart",
    "plan_agent_restart",
    "related_wipe_warning",
    "restart_needs_confirmation",
    "wipe_deletes_label",
]
