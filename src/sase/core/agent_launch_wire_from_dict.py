"""``from_dict`` hydrators for the agent launch wire.

Split out of :mod:`sase.core.agent_launch_wire` to keep each module under the
500-line cap. Dataclasses live in :mod:`sase.core.agent_launch_wire_records`
and JSON projection in :mod:`sase.core.agent_launch_wire_conversion`.
"""

from __future__ import annotations

from typing import Any

from sase.core.agent_launch_wire_conversion import agent_launch_wire_to_json_dict
from sase.core.agent_launch_wire_records import (
    AgentLaunchPreparedWire,
    AgentUnitWire,
    BatchPredecessorContextWire,
    BatchPredecessorWaitBindingWire,
    LaunchAdmissionSummaryWire,
    LaunchConditionWire,
    LaunchFanoutPlanWire,
    LaunchFanoutSlotWire,
    LaunchPlanDiagnosticWire,
    LaunchPlanWire,
    LaunchUnitResultWire,
    LaunchUnitWire,
    ProcUnitWire,
    WaitTargetWire,
    WorkspaceClaimRequestWire,
)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _workspace_claim_request_from_dict(
    data: dict[str, Any],
) -> WorkspaceClaimRequestWire:
    return WorkspaceClaimRequestWire(
        project_file=str(data["project_file"]),
        workspace_num=int(data["workspace_num"]),
        workflow_name=str(data["workflow_name"]),
        pid=int(data["pid"]),
        cl_name=str(data.get("cl_name") or ""),
        artifacts_timestamp=str(data.get("artifacts_timestamp") or ""),
        transfer_from_pid=(
            None
            if data.get("transfer_from_pid") is None
            else int(data["transfer_from_pid"])
        ),
        pinned=bool(data.get("pinned", False)),
    )


def agent_launch_prepared_from_dict(
    data: dict[str, Any],
) -> AgentLaunchPreparedWire:
    claim_data = data.get("claim_request")
    return AgentLaunchPreparedWire(
        schema_version=int(data["schema_version"]),
        prompt_file=str(data["prompt_file"]),
        output_path=str(data["output_path"]),
        safe_name=str(data["safe_name"]),
        argv=[str(item) for item in data.get("argv", [])],
        cwd=str(data["cwd"]),
        env_delta={
            str(key): str(value)
            for key, value in dict(data.get("env_delta", {})).items()
        },
        claim_request=(
            None
            if claim_data is None
            else _workspace_claim_request_from_dict(dict(claim_data))
        ),
    )


def launch_fanout_plan_from_dict(data: dict[str, Any]) -> LaunchFanoutPlanWire:
    return LaunchFanoutPlanWire(
        schema_version=int(data["schema_version"]),
        launch_kind=str(data["launch_kind"]),
        slots=[
            LaunchFanoutSlotWire(
                prompt=str(slot["prompt"]),
                launch_kind=str(slot["launch_kind"]),
                slot_index=int(slot["slot_index"]),
                alt_id=None if slot.get("alt_id") is None else str(slot["alt_id"]),
                timestamp=(
                    None if slot.get("timestamp") is None else str(slot["timestamp"])
                ),
                workflow_name=(
                    None
                    if slot.get("workflow_name") is None
                    else str(slot["workflow_name"])
                ),
                model=None if slot.get("model") is None else str(slot["model"]),
                repeat_name=(
                    None
                    if slot.get("repeat_name") is None
                    else str(slot["repeat_name"])
                ),
                bead_id=(None if slot.get("bead_id") is None else str(slot["bead_id"])),
                wait_for_previous=bool(slot.get("wait_for_previous", False)),
                name_generated=bool(slot.get("name_generated", False)),
            )
            for slot in data.get("slots", [])
        ],
        requires_sequential_naming_wait=bool(
            data.get("requires_sequential_naming_wait", False)
        ),
        fanout_sleep_seconds=float(data.get("fanout_sleep_seconds", 0.0)),
    )


def batch_predecessor_context_from_dict(
    data: dict[str, Any],
) -> BatchPredecessorContextWire:
    return BatchPredecessorContextWire(
        schema_version=int(data["schema_version"]),
        project_name=str(data["project_name"]),
        timestamp=str(data["timestamp"]),
        artifact_dir=str(data["artifact_dir"]),
        name=None if data.get("name") is None else str(data["name"]),
    )


def batch_predecessor_wait_binding_from_dict(
    data: dict[str, Any],
) -> BatchPredecessorWaitBindingWire:
    return BatchPredecessorWaitBindingWire(
        schema_version=int(data["schema_version"]),
        prompt=str(data["prompt"]),
        wait_names=[str(item) for item in data.get("wait_names", [])],
        wait_for_artifacts=[
            agent_launch_wire_to_json_dict(dict(item))
            for item in data.get("wait_for_artifacts", [])
        ],
        bound_wait_count=int(data.get("bound_wait_count") or 0),
    )


def launch_plan_from_dict(data: dict[str, Any]) -> LaunchPlanWire:
    return LaunchPlanWire(
        schema_version=int(data["schema_version"]),
        launch_kind=str(data["launch_kind"]),
        selected_project=(
            None
            if data.get("selected_project") is None
            else str(data["selected_project"])
        ),
        units=[_launch_unit_from_dict(dict(unit)) for unit in data.get("units", [])],
        approval_preview=[str(line) for line in data.get("approval_preview", [])],
        content_digest=str(data["content_digest"]),
        diagnostics=[
            _launch_plan_diagnostic_from_dict(dict(row))
            for row in data.get("diagnostics", [])
        ],
    )


def _launch_unit_from_dict(data: dict[str, Any]) -> LaunchUnitWire:
    return LaunchUnitWire(
        logical_id=str(data["logical_id"]),
        source_order=int(data["source_order"]),
        waits=[_wait_target_from_dict(dict(wait)) for wait in data.get("waits", [])],
        condition=(
            None
            if data.get("condition") is None
            else _launch_condition_from_dict(dict(data["condition"]))
        ),
        payload=_launch_unit_payload_from_dict(dict(data["payload"])),
    )


def _launch_unit_payload_from_dict(
    data: dict[str, Any],
) -> AgentUnitWire | ProcUnitWire:
    kind = str(data.get("kind") or "")
    if kind == "agent":
        return AgentUnitWire(
            prompt=str(data["prompt"]),
            identity=_optional_str(data.get("identity")),
            identity_explicit=bool(data.get("identity_explicit", False)),
            identity_force_reuse=bool(data.get("identity_force_reuse", False)),
            clan=_optional_str(data.get("clan")),
            clan_declared=bool(data.get("clan_declared", False)),
            clan_tribe=_optional_str(data.get("clan_tribe")),
            clan_summary=_optional_str(data.get("clan_summary")),
            clan_summary_script=_optional_str(data.get("clan_summary_script")),
            family_attach_parent=_optional_str(data.get("family_attach_parent")),
            family_attach_suffix=_optional_str(data.get("family_attach_suffix")),
            tribe=_optional_str(data.get("tribe")),
            model=_optional_str(data.get("model")),
            reasoning_effort=_optional_str(data.get("reasoning_effort")),
            bead_id=_optional_str(data.get("bead_id")),
            hidden=bool(data.get("hidden", False)),
            auto_enabled=bool(data.get("auto_enabled", False)),
            auto_mode=_optional_str(data.get("auto_mode")),
            finalizers=[str(item) for item in data.get("finalizers", [])],
            wait_runners=(
                None if data.get("wait_runners") is None else int(data["wait_runners"])
            ),
            wait_priority=(
                None
                if data.get("wait_priority") is None
                else int(data["wait_priority"])
            ),
            queue_weight=(
                None
                if data.get("queue_weight") is None
                else float(data["queue_weight"])
            ),
            queue_weight_explicit=bool(data.get("queue_weight_explicit", False)),
            workspace_provider=_optional_str(data.get("workspace_provider")),
            workspace_reference=_optional_str(data.get("workspace_reference")),
            dispatch_target=_optional_str(data.get("dispatch_target")),
        )
    if kind == "proc":
        return ProcUnitWire(
            code=_code_value_from_dict(dict(data["code"])),
            shell_name=(
                None if data.get("shell_name") is None else str(data["shell_name"])
            ),
            label=None if data.get("label") is None else str(data["label"]),
            timeout=None if data.get("timeout") is None else str(data["timeout"]),
            idle_timeout=(
                None if data.get("idle_timeout") is None else str(data["idle_timeout"])
            ),
            cwd=None if data.get("cwd") is None else str(data["cwd"]),
            workspace=bool(data.get("workspace", False)),
            workspace_explicit=bool(data.get("workspace_explicit", False)),
            selected_project=(
                None
                if data.get("selected_project") is None
                else str(data["selected_project"])
            ),
        )
    raise ValueError(f"unknown launch unit payload kind: {kind!r}")


def _launch_condition_from_dict(data: dict[str, Any]) -> LaunchConditionWire:
    return LaunchConditionWire(
        code=_code_value_from_dict(dict(data["code"])),
        cwd=None if data.get("cwd") is None else str(data["cwd"]),
        context_fields=[str(item) for item in data.get("context_fields", [])],
    )


def _wait_target_from_dict(data: dict[str, Any]) -> WaitTargetWire:
    return WaitTargetWire(
        kind=str(data["kind"]),
        logical_id=None if data.get("logical_id") is None else str(data["logical_id"]),
        source=None if data.get("source") is None else str(data["source"]),
        name=None if data.get("name") is None else str(data["name"]),
        identifier=None if data.get("identifier") is None else str(data["identifier"]),
        bead_id=None if data.get("bead_id") is None else str(data["bead_id"]),
        value=None if data.get("value") is None else str(data["value"]),
    )


def _launch_plan_diagnostic_from_dict(
    data: dict[str, Any],
) -> LaunchPlanDiagnosticWire:
    span = data.get("source_span")
    return LaunchPlanDiagnosticWire(
        code=str(data["code"]),
        severity=str(data["severity"]),
        message=str(data["message"]),
        source_span=(
            (int(span[0]), int(span[1]))
            if isinstance(span, (list, tuple)) and len(span) == 2
            else None
        ),
        logical_id=None if data.get("logical_id") is None else str(data["logical_id"]),
    )


def _code_value_from_dict(data: dict[str, Any]) -> Any:
    from sase.xprompt.code_value import CodeValue

    info = data.get("info_string")
    return CodeValue(
        source=str(data.get("source") or ""),
        language=str(data.get("language") or "bash"),
        info_string=str(info) if isinstance(info, str) else None,
        digest=str(data.get("digest") or ""),
        preview=str(data.get("preview") or ""),
    )


def launch_unit_result_from_dict(data: dict[str, Any]) -> LaunchUnitResultWire:
    operation_key = data.get("operation_key")
    locator = data.get("locator")
    uncertain = data.get("uncertain")
    return LaunchUnitResultWire(
        logical_id=str(data["logical_id"]),
        outcome=str(data["outcome"]),
        message=None if data.get("message") is None else str(data["message"]),
        identity=_optional_str(data.get("identity")),
        dispatch_target=_optional_str(data.get("dispatch_target")),
        workspace_reference=_optional_str(data.get("workspace_reference")),
        operation_key=dict(operation_key) if isinstance(operation_key, dict) else None,
        locator=dict(locator) if isinstance(locator, dict) else None,
        receipt_state=_optional_str(data.get("receipt_state")),
        uncertain=None if uncertain is None else bool(uncertain),
    )


def launch_admission_summary_from_dict(
    data: dict[str, Any],
) -> LaunchAdmissionSummaryWire:
    return LaunchAdmissionSummaryWire(
        total=int(data.get("total") or 0),
        eligible=int(data.get("eligible") or 0),
        launched=int(data.get("launched") or 0),
        skipped=int(data.get("skipped") or 0),
        condition_errors=int(data.get("condition_errors") or 0),
        launch_errors=int(data.get("launch_errors") or 0),
    )


__all__ = [
    "agent_launch_prepared_from_dict",
    "batch_predecessor_context_from_dict",
    "batch_predecessor_wait_binding_from_dict",
    "launch_admission_summary_from_dict",
    "launch_fanout_plan_from_dict",
    "launch_plan_from_dict",
    "launch_unit_result_from_dict",
]
