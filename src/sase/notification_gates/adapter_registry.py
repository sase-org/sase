"""Registered gate-kind table and its lookup projections."""

from sase.autonomy.gates import capabilities_for_kind
from sase.notification_gates.adapter import GateAdapter
from sase.notification_gates.models import GateError

_ADAPTERS = (
    GateAdapter(
        kind="plan",
        display_title="Plan Approval",
        action="PlanApproval",
        pending_action_kind="plan_approval",
        sender="plan",
        request_filename="plan_request.json",
        response_filename="plan_response.json",
        legacy_directory_key="response_dir",
        auto_capabilities=capabilities_for_kind("plan"),
    ),
    GateAdapter(
        kind="epic_plan",
        display_title="Epic Approval",
        action="EpicApproval",
        pending_action_kind="epic_approval",
        sender="epic",
        request_filename="plan_request.json",
        response_filename="plan_response.json",
        legacy_directory_key="response_dir",
        auto_capabilities=capabilities_for_kind("epic_plan"),
    ),
    GateAdapter(
        kind="question",
        display_title="Question",
        action="UserQuestion",
        pending_action_kind="user_question",
        sender="question",
        request_filename="question_request.json",
        response_filename="question_response.json",
        legacy_directory_key="response_dir",
        auto_capabilities=capabilities_for_kind("question"),
        branch_actionable=False,
    ),
    GateAdapter(
        kind="sudo",
        display_title="Sudo Request",
        action="SudoRequest",
        pending_action_kind="sudo",
        sender="sudo",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bundle_path",
        neutral_only=True,
        default_feedback="optional",
        generic_form=True,
    ),
    GateAdapter(
        kind="launch",
        display_title="Launch Approval",
        action="LaunchApproval",
        pending_action_kind="launch_approval",
        sender="launch",
        request_filename="launch_request.json",
        response_filename="launch_response.json",
        legacy_directory_key="response_dir",
    ),
    GateAdapter(
        kind="hitl",
        display_title="HITL",
        action="HITL",
        pending_action_kind="hitl",
        sender="hitl",
        request_filename="hitl_request.json",
        response_filename="hitl_response.json",
        legacy_directory_key="artifacts_dir",
    ),
    GateAdapter(
        kind="task_triage",
        display_title="Task Triage",
        action="TaskTriage",
        pending_action_kind="task_triage",
        sender="bead",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bundle_path",
        neutral_only=True,
        generic_form=True,
    ),
    GateAdapter(
        kind="bead_snooze",
        display_title="Snoozed Task",
        action="BeadSnooze",
        pending_action_kind="bead_snooze",
        sender="bead",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bead_snooze_dir",
        neutral_only=True,
        generic_form=True,
    ),
    GateAdapter(
        kind="flag_triage",
        display_title="Flag Triage",
        action="FlagTriage",
        pending_action_kind="flag_triage",
        sender="bead",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bundle_path",
        neutral_only=True,
        generic_form=True,
    ),
    GateAdapter(
        kind="bead_stale_cleanup",
        display_title="Stale Task Cleanup",
        action="BeadStaleCleanup",
        pending_action_kind="bead_stale_cleanup",
        sender="bead",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bundle_path",
        neutral_only=True,
        default_feedback="optional",
        generic_form=True,
    ),
    GateAdapter(
        kind="plugins_required",
        display_title="Required Plugins",
        action="PluginsRequired",
        pending_action_kind="plugins_required",
        sender="plugin",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bundle_path",
        neutral_only=True,
        generic_form=True,
    ),
    GateAdapter(
        kind="custom",
        display_title="Custom Gate",
        action="CustomGate",
        pending_action_kind="custom_gate",
        sender="custom",
        request_filename="request.json",
        response_filename="response.json",
        legacy_directory_key="bundle_path",
        neutral_only=True,
        default_feedback="optional",
        generic_form=True,
    ),
)

_BY_KIND = {adapter.kind: adapter for adapter in _ADAPTERS}
_BY_ACTION = {adapter.action: adapter for adapter in _ADAPTERS}
_KIND_ALIASES = {
    "plan_approval": "plan",
    "epic": "epic_plan",
    "epic_approval": "epic_plan",
    "user_question": "question",
    "launch_approval": "launch",
}

PRIVILEGED_GATE_ACTIONS = frozenset(_BY_ACTION)


def adapter_for_kind(kind: str) -> GateAdapter:
    """Return the registered adapter for *kind*."""
    canonical = _KIND_ALIASES.get(kind, kind)
    try:
        return _BY_KIND[canonical]
    except KeyError as exc:
        raise GateError(
            "unknown_gate_kind", "kind", f"unregistered gate kind: {kind}"
        ) from exc


def adapter_for_action(action: str | None) -> GateAdapter | None:
    """Return the registered adapter projected by a notification action."""
    if action is None:
        return None
    return _BY_ACTION.get(action)


def registered_gate_kinds() -> tuple[str, ...]:
    """Return canonical registered kind identifiers."""
    return tuple(adapter.kind for adapter in _ADAPTERS)
