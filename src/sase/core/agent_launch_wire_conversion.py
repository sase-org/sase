"""JSON-shape conversion helpers for the agent launch wire.

Split out of :mod:`sase.core.agent_launch_wire` to keep each module under the
500-line cap. Dataclasses live in :mod:`sase.core.agent_launch_wire_records`
and ``from_dict`` hydrators in :mod:`sase.core.agent_launch_wire_from_dict`.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sase.core.agent_launch_wire_records import (
    AgentUnitWire,
    BatchPredecessorContextWire,
    BatchPredecessorWaitBindingWire,
    LaunchConditionWire,
    LaunchPlanWire,
    LaunchUnitResultWire,
    LaunchUnitWire,
    ProcUnitWire,
    WaitTargetWire,
)


def agent_launch_wire_to_json_dict(record: Any) -> Any:
    """Project launch wire dataclasses to JSON-safe dict/list/scalar values."""

    if isinstance(record, (list, tuple)):
        return [agent_launch_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {str(k): agent_launch_wire_to_json_dict(v) for k, v in record.items()}
    from sase.xprompt.code_value import CodeValue

    if isinstance(record, CodeValue):
        data: dict[str, Any] = {
            "schema_version": 1,
            "source": record.source,
            "language": record.language,
            "digest": record.digest,
            "preview": record.preview,
        }
        if record.info_string is not None:
            data["info_string"] = record.info_string
        return data
    if isinstance(record, AgentUnitWire):
        agent_payload = asdict(record)
        agent_payload["kind"] = "agent"
        for key in (
            "identity",
            "clan",
            "clan_tribe",
            "clan_summary",
            "clan_summary_script",
            "family_attach_parent",
            "family_attach_suffix",
            "tribe",
            "model",
            "reasoning_effort",
            "bead_id",
            "auto_mode",
            "wait_runners",
            "wait_priority",
            "queue_weight",
            "workspace_provider",
            "workspace_reference",
            "dispatch_target",
        ):
            if agent_payload.get(key) is None:
                agent_payload.pop(key, None)
        for key in ("identity_force_reuse", "clan_declared", "queue_weight_explicit"):
            if not agent_payload.get(key):
                agent_payload.pop(key, None)
        return agent_launch_wire_to_json_dict(agent_payload)
    if isinstance(record, ProcUnitWire):
        proc_payload: dict[str, Any] = {
            "kind": "proc",
            "code": agent_launch_wire_to_json_dict(record.code),
            "workspace": record.workspace,
            "workspace_explicit": record.workspace_explicit,
        }
        if record.shell_name is not None:
            proc_payload["shell_name"] = record.shell_name
        if record.label is not None:
            proc_payload["label"] = record.label
        if record.timeout is not None:
            proc_payload["timeout"] = record.timeout
        if record.idle_timeout is not None:
            proc_payload["idle_timeout"] = record.idle_timeout
        if record.cwd is not None:
            proc_payload["cwd"] = record.cwd
        if record.selected_project is not None:
            proc_payload["selected_project"] = record.selected_project
        return proc_payload
    if isinstance(record, LaunchConditionWire):
        condition = {
            "code": agent_launch_wire_to_json_dict(record.code),
            "context_fields": list(record.context_fields),
        }
        if record.cwd is not None:
            condition["cwd"] = record.cwd
        return condition
    if isinstance(record, WaitTargetWire):
        return _wait_target_to_json_dict(record)
    if isinstance(record, BatchPredecessorContextWire):
        context = {
            "schema_version": record.schema_version,
            "project_name": record.project_name,
            "timestamp": record.timestamp,
            "artifact_dir": record.artifact_dir,
        }
        if record.name is not None:
            context["name"] = record.name
        return context
    if isinstance(record, BatchPredecessorWaitBindingWire):
        return {
            "schema_version": record.schema_version,
            "prompt": record.prompt,
            "wait_names": list(record.wait_names),
            "wait_for_artifacts": [
                agent_launch_wire_to_json_dict(item)
                for item in record.wait_for_artifacts
            ],
            "bound_wait_count": record.bound_wait_count,
        }
    if isinstance(record, LaunchPlanWire):
        return {
            "schema_version": record.schema_version,
            "launch_kind": record.launch_kind,
            "selected_project": record.selected_project,
            "units": [agent_launch_wire_to_json_dict(unit) for unit in record.units],
            "approval_preview": list(record.approval_preview),
            "content_digest": record.content_digest,
            "diagnostics": [
                agent_launch_wire_to_json_dict(item) for item in record.diagnostics
            ],
        }
    if isinstance(record, LaunchUnitWire):
        unit: dict[str, Any] = {
            "logical_id": record.logical_id,
            "source_order": record.source_order,
            "waits": [agent_launch_wire_to_json_dict(wait) for wait in record.waits],
            "payload": agent_launch_wire_to_json_dict(record.payload),
        }
        if record.condition is not None:
            unit["condition"] = agent_launch_wire_to_json_dict(record.condition)
        return unit
    if isinstance(record, LaunchUnitResultWire):
        result: dict[str, Any] = {
            "logical_id": record.logical_id,
            "outcome": record.outcome,
        }
        if record.message is not None:
            result["message"] = record.message
        if record.identity is not None:
            result["identity"] = record.identity
        if record.dispatch_target is not None:
            result["dispatch_target"] = record.dispatch_target
        if record.workspace_reference is not None:
            result["workspace_reference"] = record.workspace_reference
        if record.operation_key is not None:
            result["operation_key"] = dict(record.operation_key)
        if record.locator is not None:
            result["locator"] = dict(record.locator)
        if record.receipt_state is not None:
            result["receipt_state"] = record.receipt_state
        if record.uncertain is not None:
            result["uncertain"] = record.uncertain
        return result
    if hasattr(record, "__dataclass_fields__"):
        return agent_launch_wire_to_json_dict(asdict(record))
    return record


def _wait_target_to_json_dict(wait: WaitTargetWire) -> dict[str, Any]:
    data: dict[str, Any] = {"kind": wait.kind}
    if wait.logical_id is not None:
        data["logical_id"] = wait.logical_id
    if wait.source is not None:
        data["source"] = wait.source
    if wait.name is not None:
        data["name"] = wait.name
    if wait.identifier is not None:
        data["identifier"] = wait.identifier
    if wait.bead_id is not None:
        data["bead_id"] = wait.bead_id
    if wait.value is not None:
        data["value"] = wait.value
    return data


__all__ = [
    "agent_launch_wire_to_json_dict",
]
