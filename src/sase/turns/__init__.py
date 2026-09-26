"""Reusable substrate for SASE agent-session shell mechanics."""

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
    "spawn_turn_agent_session_successor": "followup",
    "starter_identity": "followup",
    "wait_for_followup_started": "followup",
    "wait_for_starter": "followup",
    "TurnHandoffError": "handoff",
    "maybe_handoff_turn_from_agent": "handoff",
    "will_handoff_turn_to_agent_runner": "handoff",
    "write_turn_pending_marker": "handoff",
    "create_agent_session_turn_member": "member",
    "SequenceSuffixSpec": "naming",
    "TurnIdSpec": "naming",
    "allocate_turn_suffix": "naming",
    "new_turn_id": "naming",
    "short_turn_id": "naming",
    "SHELL_MAX_OUTPUT_BYTES": "output",
    "OutputCapture": "output",
    "turn_routing_prefix": "prompt",
    "TurnSettlementConfig": "settlement",
    "finalize_turn_workflow_state": "settlement",
    "project_name_from_artifacts_dir": "settlement",
    "settle_turn_claim_and_followup": "settlement",
    "stamp_turn_finished_at": "settlement",
    "touch_agent_refresh_pulse": "settlement",
    "touch_turn_refresh_pulse": "settlement",
    "TurnStateConfig": "state",
    "is_real_turn_member": "state",
    "is_turn_member_role": "state",
    "turn_state_bucket": "state",
    "turn_state_is_terminal": "state",
    "TurnStatusPair": "status",
    "clamp_turn_status": "status",
    "clamp_turn_status_or_default": "status",
    "effective_turn_status": "status",
    "turn_status_accent": "status",
    "turn_status_glyph": "status",
    "turn_status_pair": "status",
    "turn_status_style": "status",
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
