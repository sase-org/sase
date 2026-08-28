"""Reusable substrate for SASE family shell mechanics."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_MODULE_BY_EXPORT = {
    "DEFAULT_STARTER_SETTLE_TIMEOUT_SECONDS": "followup",
    "FollowupLaunchResult": "followup",
    "FollowupPersistence": "followup",
    "fork_target_for_settled_starter": "followup",
    "record_followup_launched": "followup",
    "record_followup_not_launchable": "followup",
    "spawn_shell_family_successor": "followup",
    "starter_identity": "followup",
    "wait_for_starter": "followup",
    "ShellHandoffError": "handoff",
    "maybe_handoff_shell_from_agent": "handoff",
    "will_handoff_shell_to_agent_runner": "handoff",
    "write_shell_pending_marker": "handoff",
    "create_family_shell_member": "member",
    "SequenceSuffixSpec": "naming",
    "ShellIdSpec": "naming",
    "allocate_shell_suffix": "naming",
    "new_shell_id": "naming",
    "short_shell_id": "naming",
    "SHELL_MAX_OUTPUT_BYTES": "output",
    "OutputCapture": "output",
    "shell_routing_prefix": "prompt",
    "ShellSettlementConfig": "settlement",
    "finalize_shell_workflow_state": "settlement",
    "project_name_from_artifacts_dir": "settlement",
    "settle_shell_claim_and_followup": "settlement",
    "stamp_shell_finished_at": "settlement",
    "touch_shell_refresh_pulse": "settlement",
    "ShellStateConfig": "state",
    "is_real_shell_member": "state",
    "is_shell_member_role": "state",
    "shell_state_bucket": "state",
    "shell_state_is_terminal": "state",
    "ShellStatusPair": "status",
    "clamp_shell_status": "status",
    "clamp_shell_status_or_default": "status",
    "effective_shell_status": "status",
    "shell_status_accent": "status",
    "shell_status_glyph": "status",
    "shell_status_pair": "status",
    "shell_status_style": "status",
}

__all__ = sorted(_MODULE_BY_EXPORT)


def __getattr__(name: str) -> Any:
    """Load substrate exports lazily to keep light modules cheap to import."""
    module_name = _MODULE_BY_EXPORT.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


_PEP562_HOOKS = (__getattr__, __dir__)
