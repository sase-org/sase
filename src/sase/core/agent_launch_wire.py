"""Wire records for the agent-launch migration boundary.

These dataclasses pin the Python-side JSON contract that later Rust-backed
launch phases will implement. Phase 1 only defines and tests the shapes; no
production launch path consumes these records yet.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

AGENT_LAUNCH_WIRE_SCHEMA_VERSION = 1
LAUNCH_PLAN_WIRE_SCHEMA_VERSION = 1
LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class WorkspaceClaimRequestWire:
    """Request to claim or transfer a launch workspace after process spawn."""

    project_file: str
    workspace_num: int
    workflow_name: str
    pid: int
    cl_name: str = ""
    artifacts_timestamp: str = ""
    transfer_from_pid: int | None = None
    pinned: bool = False


@dataclass(frozen=True)
class AgentLaunchRequestWire:
    """Resolved host request for one low-level agent launch."""

    schema_version: int
    cl_name: str
    project_file: str
    workspace_dir: str
    workspace_num: int
    workflow_name: str
    prompt: str
    timestamp: str
    update_target: str = ""
    project_name: str = ""
    history_sort_key: str = ""
    is_home_mode: bool = False
    vcs_workflow_type: str | None = None
    vcs_ref: str | None = None
    deferred_workspace: bool = False
    local_xprompts_file: str | None = None
    extra_env: dict[str, str] = field(default_factory=dict)
    retry_transfer_from_pid: int | None = None


@dataclass(frozen=True)
class AgentLaunchPreparedWire:
    """Prepared process-spawn data derived from an agent launch request."""

    schema_version: int
    prompt_file: str
    output_path: str
    safe_name: str
    argv: list[str]
    cwd: str
    env_delta: dict[str, str] = field(default_factory=dict)
    claim_request: WorkspaceClaimRequestWire | None = None


@dataclass(frozen=True)
class LaunchFanoutSlotWire:
    """One child slot in a planned launch fan-out."""

    prompt: str
    launch_kind: str
    slot_index: int
    alt_id: str | None = None
    timestamp: str | None = None
    workflow_name: str | None = None
    model: str | None = None
    repeat_name: str | None = None
    bead_id: str | None = None
    wait_for_previous: bool = False
    name_generated: bool = False


@dataclass(frozen=True)
class LaunchFanoutPlanWire:
    """Normalized launch fan-out plan shared by future TUI and CLI callers."""

    schema_version: int
    launch_kind: str
    slots: list[LaunchFanoutSlotWire] = field(default_factory=list)
    requires_sequential_naming_wait: bool = False
    fanout_sleep_seconds: float = 0.0


@dataclass(frozen=True)
class WaitTargetWire:
    """One typed wait edge in an approved launch plan."""

    kind: str
    logical_id: str | None = None
    source: str | None = None
    name: str | None = None
    identifier: str | None = None
    bead_id: str | None = None
    value: str | None = None


@dataclass(frozen=True)
class LaunchConditionWire:
    """Admission predicate attached to one logical launch unit."""

    code: Any
    cwd: str | None = None
    context_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentUnitWire:
    """Agent payload inside a typed launch unit."""

    prompt: str
    identity: str | None = None
    identity_explicit: bool = False
    model: str | None = None
    reasoning_effort: str | None = None
    bead_id: str | None = None
    hidden: bool = False
    auto_enabled: bool = False
    auto_mode: str | None = None
    finalizers: list[str] = field(default_factory=list)
    wait_runners: int | None = None
    wait_priority: int | None = None


@dataclass(frozen=True)
class ProcUnitWire:
    """Stand-alone proc payload inside a typed launch unit."""

    code: Any
    shell_name: str | None = None
    label: str | None = None
    timeout: str | None = None
    idle_timeout: str | None = None
    cwd: str | None = None
    workspace: bool = False
    workspace_explicit: bool = False
    selected_project: str | None = None


@dataclass(frozen=True)
class LaunchUnitWire:
    """One stable logical Agent-or-Proc unit in a typed launch plan."""

    logical_id: str
    source_order: int
    payload: AgentUnitWire | ProcUnitWire
    waits: list[WaitTargetWire] = field(default_factory=list)
    condition: LaunchConditionWire | None = None


@dataclass(frozen=True)
class LaunchUnitResultWire:
    """Terminal result for one logical launch unit."""

    logical_id: str
    outcome: str
    message: str | None = None


@dataclass(frozen=True)
class LaunchAdmissionSummaryWire:
    """Batch admission counts reported after coordinator progress."""

    total: int
    eligible: int
    launched: int
    skipped: int
    condition_errors: int
    launch_errors: int


@dataclass(frozen=True)
class LaunchPlanDiagnosticWire:
    """Stable typed launch-plan diagnostic."""

    code: str
    severity: str
    message: str
    source_span: tuple[int, int] | None = None
    logical_id: str | None = None


@dataclass(frozen=True)
class LaunchPlanWire:
    """Pure typed launch graph prepared before approval."""

    schema_version: int
    launch_kind: str
    selected_project: str | None
    content_digest: str
    units: list[LaunchUnitWire] = field(default_factory=list)
    approval_preview: list[str] = field(default_factory=list)
    diagnostics: list[LaunchPlanDiagnosticWire] = field(default_factory=list)


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
            identity=None if data.get("identity") is None else str(data["identity"]),
            identity_explicit=bool(data.get("identity_explicit", False)),
            model=None if data.get("model") is None else str(data["model"]),
            reasoning_effort=(
                None
                if data.get("reasoning_effort") is None
                else str(data["reasoning_effort"])
            ),
            bead_id=None if data.get("bead_id") is None else str(data["bead_id"]),
            hidden=bool(data.get("hidden", False)),
            auto_enabled=bool(data.get("auto_enabled", False)),
            auto_mode=None if data.get("auto_mode") is None else str(data["auto_mode"]),
            finalizers=[str(item) for item in data.get("finalizers", [])],
            wait_runners=(
                None if data.get("wait_runners") is None else int(data["wait_runners"])
            ),
            wait_priority=(
                None
                if data.get("wait_priority") is None
                else int(data["wait_priority"])
            ),
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


def _launch_plan_diagnostic_from_dict(data: dict[str, Any]) -> LaunchPlanDiagnosticWire:
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
    return LaunchUnitResultWire(
        logical_id=str(data["logical_id"]),
        outcome=str(data["outcome"]),
        message=None if data.get("message") is None else str(data["message"]),
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
    "AGENT_LAUNCH_WIRE_SCHEMA_VERSION",
    "AgentLaunchPreparedWire",
    "AgentLaunchRequestWire",
    "AgentUnitWire",
    "LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION",
    "LaunchAdmissionSummaryWire",
    "LaunchConditionWire",
    "LaunchFanoutPlanWire",
    "LaunchFanoutSlotWire",
    "LaunchPlanDiagnosticWire",
    "LaunchPlanWire",
    "LaunchUnitResultWire",
    "LaunchUnitWire",
    "LAUNCH_PLAN_WIRE_SCHEMA_VERSION",
    "ProcUnitWire",
    "WaitTargetWire",
    "WorkspaceClaimRequestWire",
    "agent_launch_prepared_from_dict",
    "agent_launch_wire_to_json_dict",
    "launch_admission_summary_from_dict",
    "launch_fanout_plan_from_dict",
    "launch_plan_from_dict",
    "launch_unit_result_from_dict",
]
