"""Wire records for agent-list composition.

The records in this module pin the boundary for the future Rust
``compose_agent_list`` operation. They intentionally mirror the raw data the
Agents tab needs rather than display-only computed properties from
``sase.ace.tui.models.agent.Agent``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_scan_wire import AgentArtifactScanWire, agent_scan_wire_from_dict
from sase.core.wire import ChangeSpecWire
from sase.core.wire_conversion import changespec_wire_from_dict

AGENT_COMPOSE_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunningClaimWire:
    """RUNNING-field claim parsed by Python and consumed by composition."""

    project_file: str
    project_name: str
    cl_name: str
    workspace_num: int | None = None
    workspace_dir: str | None = None
    workflow: str | None = None
    raw_suffix: str | None = None
    pid: int | None = None
    model: str | None = None
    llm_provider: str | None = None
    vcs_provider: str | None = None
    agent_name: str | None = None
    approve: bool = False
    hidden: bool = False
    bug: str | None = None
    cl_num: str | None = None


@dataclass(frozen=True)
class AgentComposeOptionsWire:
    """Caller-supplied knobs for one compose operation."""

    include_diagnostics: bool = True
    include_workflow_steps: bool = True
    tui_mode: bool = True


@dataclass(frozen=True)
class AgentComposeInputWire:
    """All host-owned inputs needed by deterministic agent composition."""

    schema_version: int = AGENT_COMPOSE_WIRE_SCHEMA_VERSION
    artifact_scan: AgentArtifactScanWire | None = None
    changespecs: list[ChangeSpecWire] = field(default_factory=list)
    running_claims: list[RunningClaimWire] = field(default_factory=list)
    alive_pids: list[int] = field(default_factory=list)
    dead_pids: list[int] = field(default_factory=list)
    dismissed_identities: list[tuple[str, str, str | None]] = field(
        default_factory=list
    )
    dismissed_suffixes: list[str] = field(default_factory=list)
    options: AgentComposeOptionsWire = field(default_factory=AgentComposeOptionsWire)


# pyvision: tests/test_core_agent_compose.py
@dataclass(frozen=True)
class DropReasonWire:
    """Diagnostic describing a candidate dropped during composition."""

    stage: str
    identity: tuple[str, str, str | None]
    reason: str
    detail: str | None = None


# pyvision: tests/test_core_agent_compose.py
@dataclass(frozen=True)
class MergeReasonWire:
    """Diagnostic describing data merged from one candidate into another."""

    stage: str
    source_identity: tuple[str, str, str | None]
    target_identity: tuple[str, str, str | None]
    reason: str
    fields: list[str] = field(default_factory=list)


# pyvision: tests/test_core_agent_compose.py
@dataclass(frozen=True)
class AgentWire:
    """Stable wire projection of one ``Agent`` row."""

    agent_type: str
    cl_name: str
    project_file: str
    status: str
    start_time: str | None = None
    run_start_time: str | None = None
    stop_time: str | None = None
    workspace_num: int | None = None
    workflow: str | None = None
    hook_command: str | None = None
    commit_entry_id: str | None = None
    mentor_profile: str | None = None
    mentor_name: str | None = None
    reviewer: str | None = None
    pid: int | None = None
    raw_suffix: str | None = None
    response_path: str | None = None
    diff_path: str | None = None
    extra_files: list[str] = field(default_factory=list)
    bug: str | None = None
    cl_num: str | None = None
    parent_workflow: str | None = None
    parent_timestamp: str | None = None
    step_name: str | None = None
    step_type: str | None = None
    step_source: str | None = None
    step_output: dict[str, Any] | None = None
    step_index: int | None = None
    total_steps: int | None = None
    parent_step_index: int | None = None
    parent_total_steps: int | None = None
    is_hidden_step: bool = False
    appears_as_agent: bool = False
    is_anonymous: bool = False
    error_message: str | None = None
    error_traceback: str | None = None
    output_path: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    vcs_provider: str | None = None
    workspace_dir: str | None = None
    agent_name: str | None = None
    waiting_for: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None
    artifacts_dir: str | None = None
    embedded_workflow_name: str | None = None
    is_pre_prompt_step: bool = False
    hidden: bool = False
    retry_count: int = 0
    max_retries: int = 0
    retry_next_at_epoch: float | None = None
    retry_wait_seconds: int = 0
    using_fallback: bool = False
    fallback_model: str | None = None
    retry_status: str | None = None
    from_changespec: bool = False
    approve: bool = False
    role_suffix: str | None = None
    tag: str | None = None
    retry_of_timestamp: str | None = None
    retry_attempt: int = 0
    retry_chain_root_timestamp: str | None = None
    retried_as_timestamp: str | None = None
    retry_terminal: bool = False
    retry_error_category: str | None = None
    plan_times: list[str] = field(default_factory=list)
    code_time: str | None = None
    feedback_times: list[str] = field(default_factory=list)
    questions_times: list[str] = field(default_factory=list)
    retry_times: list[str] = field(default_factory=list)
    followup_identities: list[tuple[str, str, str | None]] = field(default_factory=list)
    retry_chain_sibling_identities: list[tuple[str, str, str | None]] = field(
        default_factory=list
    )

    @property
    def identity(self) -> tuple[str, str, str | None]:
        return (self.agent_type, self.cl_name, self.raw_suffix)


@dataclass(frozen=True)
class ComposedAgentListWire:
    """Result of composing an Agents-tab list."""

    schema_version: int = AGENT_COMPOSE_WIRE_SCHEMA_VERSION
    agents: list[AgentWire] = field(default_factory=list)
    workflow_agent_steps: list[AgentWire] = field(default_factory=list)
    dismissed_from_loader: list[AgentWire] = field(default_factory=list)
    dropped: list[DropReasonWire] = field(default_factory=list)
    merge_log: list[MergeReasonWire] = field(default_factory=list)


def _datetime_to_wire(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_list_to_wire(values: list[datetime]) -> list[str]:
    return [value.isoformat() for value in values]


def _datetime_from_wire(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _datetime_list_from_wire(values: list[str]) -> list[datetime]:
    return [datetime.fromisoformat(value) for value in values]


def _agent_identity_to_wire(agent: Agent) -> tuple[str, str, str | None]:
    agent_type, cl_name, raw_suffix = agent.identity
    return (agent_type.value, cl_name, raw_suffix)


def agent_to_wire(agent: Agent) -> AgentWire:
    """Convert an ``Agent`` model to the stable composition wire shape."""

    return AgentWire(
        agent_type=agent.agent_type.value,
        cl_name=agent.cl_name,
        project_file=agent.project_file,
        status=agent.status,
        start_time=_datetime_to_wire(agent.start_time),
        run_start_time=_datetime_to_wire(agent.run_start_time),
        stop_time=_datetime_to_wire(agent.stop_time),
        workspace_num=agent.workspace_num,
        workflow=agent.workflow,
        hook_command=agent.hook_command,
        commit_entry_id=agent.commit_entry_id,
        mentor_profile=agent.mentor_profile,
        mentor_name=agent.mentor_name,
        reviewer=agent.reviewer,
        pid=agent.pid,
        raw_suffix=agent.raw_suffix,
        response_path=agent.response_path,
        diff_path=agent.diff_path,
        extra_files=list(agent.extra_files),
        bug=agent.bug,
        cl_num=agent.cl_num,
        parent_workflow=agent.parent_workflow,
        parent_timestamp=agent.parent_timestamp,
        step_name=agent.step_name,
        step_type=agent.step_type,
        step_source=agent.step_source,
        step_output=agent.step_output,
        step_index=agent.step_index,
        total_steps=agent.total_steps,
        parent_step_index=agent.parent_step_index,
        parent_total_steps=agent.parent_total_steps,
        is_hidden_step=agent.is_hidden_step,
        appears_as_agent=agent.appears_as_agent,
        is_anonymous=agent.is_anonymous,
        error_message=agent.error_message,
        error_traceback=agent.error_traceback,
        output_path=agent.output_path,
        model=agent.model,
        llm_provider=agent.llm_provider,
        vcs_provider=agent.vcs_provider,
        workspace_dir=agent.workspace_dir,
        agent_name=agent.agent_name,
        waiting_for=list(agent.waiting_for),
        wait_duration=agent.wait_duration,
        wait_until=agent.wait_until,
        artifacts_dir=agent.artifacts_dir,
        embedded_workflow_name=agent.embedded_workflow_name,
        is_pre_prompt_step=agent.is_pre_prompt_step,
        hidden=agent.hidden,
        retry_count=agent.retry_count,
        max_retries=agent.max_retries,
        retry_next_at_epoch=agent.retry_next_at_epoch,
        retry_wait_seconds=agent.retry_wait_seconds,
        using_fallback=agent.using_fallback,
        fallback_model=agent.fallback_model,
        retry_status=agent.retry_status,
        from_changespec=agent._from_changespec,
        approve=agent.approve,
        role_suffix=agent.role_suffix,
        tag=agent.tag,
        retry_of_timestamp=agent.retry_of_timestamp,
        retry_attempt=agent.retry_attempt,
        retry_chain_root_timestamp=agent.retry_chain_root_timestamp,
        retried_as_timestamp=agent.retried_as_timestamp,
        retry_terminal=agent.retry_terminal,
        retry_error_category=agent.retry_error_category,
        plan_times=_datetime_list_to_wire(agent.plan_times),
        code_time=_datetime_to_wire(agent.code_time),
        feedback_times=_datetime_list_to_wire(agent.feedback_times),
        questions_times=_datetime_list_to_wire(agent.questions_times),
        retry_times=_datetime_list_to_wire(agent.retry_times),
        followup_identities=[
            _agent_identity_to_wire(followup) for followup in agent.followup_agents
        ],
        retry_chain_sibling_identities=[
            _agent_identity_to_wire(sibling) for sibling in agent.retry_chain_siblings
        ],
    )


# pyvision: tests/test_core_agent_compose.py
def agent_from_wire(record: AgentWire) -> Agent:
    """Reconstruct an ``Agent`` model from :class:`AgentWire`."""

    agent = Agent(
        agent_type=AgentType(record.agent_type),
        cl_name=record.cl_name,
        project_file=record.project_file,
        status=record.status,
        start_time=_datetime_from_wire(record.start_time),
        run_start_time=_datetime_from_wire(record.run_start_time),
        stop_time=_datetime_from_wire(record.stop_time),
        workspace_num=record.workspace_num,
        workflow=record.workflow,
        hook_command=record.hook_command,
        commit_entry_id=record.commit_entry_id,
        mentor_profile=record.mentor_profile,
        mentor_name=record.mentor_name,
        reviewer=record.reviewer,
        pid=record.pid,
        raw_suffix=record.raw_suffix,
        response_path=record.response_path,
        diff_path=record.diff_path,
        extra_files=list(record.extra_files),
        bug=record.bug,
        cl_num=record.cl_num,
        parent_workflow=record.parent_workflow,
        parent_timestamp=record.parent_timestamp,
        step_name=record.step_name,
        step_type=record.step_type,
        step_source=record.step_source,
        step_output=record.step_output,
        step_index=record.step_index,
        total_steps=record.total_steps,
        parent_step_index=record.parent_step_index,
        parent_total_steps=record.parent_total_steps,
        is_hidden_step=record.is_hidden_step,
        appears_as_agent=record.appears_as_agent,
        is_anonymous=record.is_anonymous,
        error_message=record.error_message,
        error_traceback=record.error_traceback,
        output_path=record.output_path,
        model=record.model,
        llm_provider=record.llm_provider,
        vcs_provider=record.vcs_provider,
        workspace_dir=record.workspace_dir,
        agent_name=record.agent_name,
        waiting_for=list(record.waiting_for),
        wait_duration=record.wait_duration,
        wait_until=record.wait_until,
        artifacts_dir=record.artifacts_dir,
        embedded_workflow_name=record.embedded_workflow_name,
        is_pre_prompt_step=record.is_pre_prompt_step,
        hidden=record.hidden,
        retry_count=record.retry_count,
        max_retries=record.max_retries,
        retry_next_at_epoch=record.retry_next_at_epoch,
        retry_wait_seconds=record.retry_wait_seconds,
        using_fallback=record.using_fallback,
        fallback_model=record.fallback_model,
        retry_status=record.retry_status,
        approve=record.approve,
        role_suffix=record.role_suffix,
        tag=record.tag,
        retry_of_timestamp=record.retry_of_timestamp,
        retry_attempt=record.retry_attempt,
        retry_chain_root_timestamp=record.retry_chain_root_timestamp,
        retried_as_timestamp=record.retried_as_timestamp,
        retry_terminal=record.retry_terminal,
        retry_error_category=record.retry_error_category,
        plan_times=_datetime_list_from_wire(record.plan_times),
        code_time=_datetime_from_wire(record.code_time),
        feedback_times=_datetime_list_from_wire(record.feedback_times),
        questions_times=_datetime_list_from_wire(record.questions_times),
        retry_times=_datetime_list_from_wire(record.retry_times),
    )
    agent._from_changespec = record.from_changespec
    return agent


# pyvision: tests/test_core_agent_compose.py
def composed_agent_list_to_json_dict(record: ComposedAgentListWire) -> dict[str, Any]:
    return asdict(record)


def agent_compose_wire_to_json_dict(record: Any) -> Any:
    """Project compose wire records to the JSON-safe shape Rust expects."""
    if isinstance(record, list):
        return [agent_compose_wire_to_json_dict(item) for item in record]
    if isinstance(record, tuple):
        return [agent_compose_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: agent_compose_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


def _running_claim_from_dict(data: dict[str, Any]) -> RunningClaimWire:
    return RunningClaimWire(
        project_file=data["project_file"],
        project_name=data["project_name"],
        cl_name=data["cl_name"],
        workspace_num=data.get("workspace_num"),
        workspace_dir=data.get("workspace_dir"),
        workflow=data.get("workflow"),
        raw_suffix=data.get("raw_suffix"),
        pid=data.get("pid"),
        model=data.get("model"),
        llm_provider=data.get("llm_provider"),
        vcs_provider=data.get("vcs_provider"),
        agent_name=data.get("agent_name"),
        approve=bool(data.get("approve", False)),
        hidden=bool(data.get("hidden", False)),
        bug=data.get("bug"),
        cl_num=data.get("cl_num"),
    )


def _options_from_dict(data: dict[str, Any]) -> AgentComposeOptionsWire:
    return AgentComposeOptionsWire(
        include_diagnostics=bool(data.get("include_diagnostics", True)),
        include_workflow_steps=bool(data.get("include_workflow_steps", True)),
        tui_mode=bool(data.get("tui_mode", True)),
    )


def _agent_wire_from_dict(data: dict[str, Any]) -> AgentWire:
    return AgentWire(
        agent_type=data["agent_type"],
        cl_name=data["cl_name"],
        project_file=data["project_file"],
        status=data["status"],
        start_time=data.get("start_time"),
        run_start_time=data.get("run_start_time"),
        stop_time=data.get("stop_time"),
        workspace_num=data.get("workspace_num"),
        workflow=data.get("workflow"),
        hook_command=data.get("hook_command"),
        commit_entry_id=data.get("commit_entry_id"),
        mentor_profile=data.get("mentor_profile"),
        mentor_name=data.get("mentor_name"),
        reviewer=data.get("reviewer"),
        pid=data.get("pid"),
        raw_suffix=data.get("raw_suffix"),
        response_path=data.get("response_path"),
        diff_path=data.get("diff_path"),
        extra_files=list(data.get("extra_files") or []),
        bug=data.get("bug"),
        cl_num=data.get("cl_num"),
        parent_workflow=data.get("parent_workflow"),
        parent_timestamp=data.get("parent_timestamp"),
        step_name=data.get("step_name"),
        step_type=data.get("step_type"),
        step_source=data.get("step_source"),
        step_output=data.get("step_output"),
        step_index=data.get("step_index"),
        total_steps=data.get("total_steps"),
        parent_step_index=data.get("parent_step_index"),
        parent_total_steps=data.get("parent_total_steps"),
        is_hidden_step=bool(data.get("is_hidden_step", False)),
        appears_as_agent=bool(data.get("appears_as_agent", False)),
        is_anonymous=bool(data.get("is_anonymous", False)),
        error_message=data.get("error_message"),
        error_traceback=data.get("error_traceback"),
        output_path=data.get("output_path"),
        model=data.get("model"),
        llm_provider=data.get("llm_provider"),
        vcs_provider=data.get("vcs_provider"),
        workspace_dir=data.get("workspace_dir"),
        agent_name=data.get("agent_name"),
        waiting_for=list(data.get("waiting_for") or []),
        wait_duration=data.get("wait_duration"),
        wait_until=data.get("wait_until"),
        artifacts_dir=data.get("artifacts_dir"),
        embedded_workflow_name=data.get("embedded_workflow_name"),
        is_pre_prompt_step=bool(data.get("is_pre_prompt_step", False)),
        hidden=bool(data.get("hidden", False)),
        retry_count=int(data.get("retry_count", 0)),
        max_retries=int(data.get("max_retries", 0)),
        retry_next_at_epoch=data.get("retry_next_at_epoch"),
        retry_wait_seconds=int(data.get("retry_wait_seconds", 0)),
        using_fallback=bool(data.get("using_fallback", False)),
        fallback_model=data.get("fallback_model"),
        retry_status=data.get("retry_status"),
        from_changespec=bool(data.get("from_changespec", False)),
        approve=bool(data.get("approve", False)),
        role_suffix=data.get("role_suffix"),
        tag=data.get("tag"),
        retry_of_timestamp=data.get("retry_of_timestamp"),
        retry_attempt=int(data.get("retry_attempt", 0)),
        retry_chain_root_timestamp=data.get("retry_chain_root_timestamp"),
        retried_as_timestamp=data.get("retried_as_timestamp"),
        retry_terminal=bool(data.get("retry_terminal", False)),
        retry_error_category=data.get("retry_error_category"),
        plan_times=list(data.get("plan_times") or []),
        code_time=data.get("code_time"),
        feedback_times=list(data.get("feedback_times") or []),
        questions_times=list(data.get("questions_times") or []),
        retry_times=list(data.get("retry_times") or []),
        followup_identities=[
            (item[0], item[1], item[2])
            for item in data.get("followup_identities") or []
        ],
        retry_chain_sibling_identities=[
            (item[0], item[1], item[2])
            for item in data.get("retry_chain_sibling_identities") or []
        ],
    )


def _drop_reason_from_dict(data: dict[str, Any]) -> DropReasonWire:
    identity = data["identity"]
    return DropReasonWire(
        stage=data["stage"],
        identity=(identity[0], identity[1], identity[2]),
        reason=data["reason"],
        detail=data.get("detail"),
    )


def _merge_reason_from_dict(data: dict[str, Any]) -> MergeReasonWire:
    source_identity = data["source_identity"]
    target_identity = data["target_identity"]
    return MergeReasonWire(
        stage=data["stage"],
        source_identity=(source_identity[0], source_identity[1], source_identity[2]),
        target_identity=(target_identity[0], target_identity[1], target_identity[2]),
        reason=data["reason"],
        fields=list(data.get("fields") or []),
    )


# pyvision: tests/test_core_agent_compose.py
def agent_compose_input_from_dict(data: dict[str, Any]) -> AgentComposeInputWire:
    schema_version = data.get("schema_version")
    if schema_version != AGENT_COMPOSE_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported AgentComposeInputWire schema_version={schema_version!r}; "
            f"this build understands {AGENT_COMPOSE_WIRE_SCHEMA_VERSION}."
        )
    artifact_scan = data.get("artifact_scan")
    return AgentComposeInputWire(
        schema_version=schema_version,
        artifact_scan=(
            agent_scan_wire_from_dict(artifact_scan) if artifact_scan else None
        ),
        changespecs=[
            changespec_wire_from_dict(item) for item in data.get("changespecs") or []
        ],
        running_claims=[
            _running_claim_from_dict(item) for item in data.get("running_claims") or []
        ],
        alive_pids=list(data.get("alive_pids") or []),
        dead_pids=list(data.get("dead_pids") or []),
        dismissed_identities=[
            (item[0], item[1], item[2])
            for item in data.get("dismissed_identities") or []
        ],
        dismissed_suffixes=list(data.get("dismissed_suffixes") or []),
        options=_options_from_dict(data.get("options") or {}),
    )


def composed_agent_list_from_dict(data: dict[str, Any]) -> ComposedAgentListWire:
    schema_version = data.get("schema_version")
    if schema_version != AGENT_COMPOSE_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported ComposedAgentListWire schema_version={schema_version!r}; "
            f"this build understands {AGENT_COMPOSE_WIRE_SCHEMA_VERSION}."
        )
    return ComposedAgentListWire(
        schema_version=schema_version,
        agents=[_agent_wire_from_dict(item) for item in data.get("agents") or []],
        workflow_agent_steps=[
            _agent_wire_from_dict(item)
            for item in data.get("workflow_agent_steps") or []
        ],
        dismissed_from_loader=[
            _agent_wire_from_dict(item)
            for item in data.get("dismissed_from_loader") or []
        ],
        dropped=[_drop_reason_from_dict(item) for item in data.get("dropped") or []],
        merge_log=[
            _merge_reason_from_dict(item) for item in data.get("merge_log") or []
        ],
    )


__all__ = [
    "AGENT_COMPOSE_WIRE_SCHEMA_VERSION",
    "AgentComposeInputWire",
    "AgentComposeOptionsWire",
    "AgentWire",
    "ComposedAgentListWire",
    "DropReasonWire",
    "MergeReasonWire",
    "RunningClaimWire",
    "agent_compose_input_from_dict",
    "agent_compose_wire_to_json_dict",
    "agent_from_wire",
    "agent_to_wire",
    "composed_agent_list_from_dict",
    "composed_agent_list_to_json_dict",
]
