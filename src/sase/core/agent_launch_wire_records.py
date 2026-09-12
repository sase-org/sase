"""Dataclass records for the agent-launch migration boundary.

Split out of :mod:`sase.core.agent_launch_wire` to keep each module under the
500-line cap. JSON ``to_dict``/``from_dict`` helpers live in
:mod:`sase.core.agent_launch_wire_conversion` and
:mod:`sase.core.agent_launch_wire_from_dict`. The public import path remains
:mod:`sase.core.agent_launch_wire`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AGENT_LAUNCH_WIRE_SCHEMA_VERSION = 1
LAUNCH_PLAN_WIRE_SCHEMA_VERSION = 1
LAUNCH_ADMISSION_JOURNAL_SCHEMA_VERSION = 1
BATCH_PREDECESSOR_CONTEXT_SCHEMA_VERSION = 1


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
class BatchPredecessorContextWire:
    """Identity for the previous segment in one prompt-stack launch batch."""

    schema_version: int
    project_name: str
    timestamp: str
    artifact_dir: str
    name: str | None = None


@dataclass(frozen=True)
class BatchPredecessorWaitBindingWire:
    """Result of binding bare waits to a prompt-stack predecessor."""

    schema_version: int
    prompt: str
    wait_names: list[str] = field(default_factory=list)
    wait_for_artifacts: list[dict[str, Any]] = field(default_factory=list)
    bound_wait_count: int = 0


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
    """Agent payload inside a typed launch unit.

    ``identity`` is the positional ``%id`` member id or a declarer's full name.
    Clan joiners keep that member id here and put the clan on ``clan`` so
    dispatch can rebuild ``%id(<member>, clan=<clan>)`` without treating the
    member as the complete agent name. Missing optional grouping fields
    deserialize to today's plain-identity behavior.
    """

    prompt: str
    identity: str | None = None
    identity_explicit: bool = False
    identity_force_reuse: bool = False
    clan: str | None = None
    clan_declared: bool = False
    clan_tribe: str | None = None
    clan_summary: str | None = None
    clan_summary_script: str | None = None
    family_attach_parent: str | None = None
    family_attach_suffix: str | None = None
    tribe: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    bead_id: str | None = None
    hidden: bool = False
    auto_enabled: bool = False
    auto_mode: str | None = None
    finalizers: list[str] = field(default_factory=list)
    wait_runners: int | None = None
    wait_priority: int | None = None
    queue_weight: float | None = None
    queue_weight_explicit: bool = False
    workspace_provider: str | None = None
    workspace_reference: str | None = None
    dispatch_target: str | None = None


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
    identity: str | None = None
    dispatch_target: str | None = None
    workspace_reference: str | None = None
    operation_key: dict[str, Any] | None = None
    locator: dict[str, Any] | None = None
    receipt_state: str | None = None
    uncertain: bool | None = None


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


__all__ = [
    "AGENT_LAUNCH_WIRE_SCHEMA_VERSION",
    "AgentLaunchPreparedWire",
    "AgentLaunchRequestWire",
    "AgentUnitWire",
    "BATCH_PREDECESSOR_CONTEXT_SCHEMA_VERSION",
    "BatchPredecessorContextWire",
    "BatchPredecessorWaitBindingWire",
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
]
