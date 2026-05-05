"""Wire records for the agent/artifact filesystem scan facade.

Companion to :mod:`sase.core.wire` and :mod:`sase.core.query_wire`. Defines
the **stable** boundary between Python and a future Rust implementation of
the agent-artifact snapshot scan (Phase 3 of
``sdd/research/202604/rust_backend_migration.md`` and
``../sase_100/plans/202604/rust_backend_phase3_agent_scan.md``).

The wire records intentionally do not subclass or share code with the
existing Python ``Agent`` / ``WorkflowEntry`` / ``RunningAgentInfo``
dataclasses. Those models keep evolving for the TUI/CLI; this contract
changes only with a schema bump.

Scope of the contract
---------------------

A snapshot scan visits ``projects/*/artifacts/<workflow>/<timestamp>/``
trees rooted under a Python-supplied ``projects_root`` (normally
``~/.sase/projects``) and parses a small, fixed set of marker JSON files:

- ``agent_meta.json``
- ``done.json``
- ``running.json``
- ``waiting.json``
- ``workflow_state.json``
- ``plan_path.json``
- ``prompt_step_*.json``

Each artifact directory becomes one :class:`AgentArtifactRecordWire`
carrying the markers actually present. Optional markers are ``None`` when
the file is missing or unreadable; the scan does **not** raise on
malformed JSON — it skips the bad file and increments a typed counter on
:class:`AgentArtifactScanStatsWire` so diagnostics are still possible.

Field selection rationale
-------------------------

Only fields currently consumed by Python call sites are exposed. Phase 3D
through 3F will plug the snapshot into:

- ``sase.agent.names._lookup`` (``find_named_agent`` / ``is_workflow_complete``)
- ``sase.agent.running`` (``list_running_agents`` / ``list_all_agents``)
- ``sase.ace.tui.models._loaders._artifact_loaders`` (``load_done_agents``,
  ``load_running_home_agents``, ``enrich_agent_from_meta``)
- ``sase.ace.tui.models._loaders._workflow_loaders`` (``load_workflow_states``)
- ``sase.ace.tui.models._loaders._workflow_step_loaders``
  (``load_workflow_agent_steps``)
- ``sase.ace.tui.models._loaders._workflow_snapshot_loaders`` (snapshot mirrors)

The wire is deliberately compact: arbitrary unknown fields from the marker
JSON files are NOT round-tripped. If a future call site needs an extra
field, add it here (and bump :data:`AGENT_SCAN_WIRE_SCHEMA_VERSION` if the
shape changes incompatibly).

JSON shape conventions
----------------------

- All keys are lowercase ``snake_case``.
- ``None`` is preserved (becomes JSON ``null``).
- Lists are preserved (never replaced with ``None`` for empty branches).
- Timestamps are passed through as the original string form (ISO 8601 for
  ``*_at`` fields; ``YYYYmmddHHMMSS`` for artifact directory names).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

AGENT_SCAN_WIRE_SCHEMA_VERSION = 1
AGENT_ARTIFACT_INDEX_SCHEMA_VERSION = 1

# Workflow directory categories the Phase 3A scanner walks.
#
# Fixed directory names that may carry done agents across non-ace-run
# workflows (these match ``_DONE_AGENT_WORKFLOW_DIRS`` in
# ``_artifact_loaders``).
DONE_WORKFLOW_DIR_NAMES: tuple[str, ...] = (
    "ace-run",
    "run",
    "fix-hook",
    "crs",
    "summarize-hook",
)

# Prefix-matched workflow directories (e.g. ``mentor-<profile>``). Mirrors
# ``_DONE_AGENT_WORKFLOW_PREFIXES`` in ``_artifact_loaders``.
DONE_WORKFLOW_DIR_PREFIXES: tuple[str, ...] = ("mentor-",)

# Workflow-state directory categories scanned by ``_iter_workflow_timestamp_dirs``.
WORKFLOW_STATE_DIR_NAMES: tuple[str, ...] = ("ace-run", "run")
WORKFLOW_STATE_DIR_PREFIXES: tuple[str, ...] = ("workflow-",)


@dataclass(frozen=True)
class AgentArtifactScanOptionsWire:
    """Caller-supplied knobs for one snapshot scan.

    Attributes:
        include_prompt_step_markers: When True (the default), parse
            ``prompt_step_*.json`` files inside each artifact directory.
            ``find_named_agent`` and the running-agent CLI list don't need
            them; the TUI workflow loader does. Callers that don't need
            them can flip this off to skip a glob + N reads per dir.
        include_raw_prompt_snippets: When True, read the first 200 bytes
            of ``raw_xprompt.md`` into
            :attr:`AgentArtifactRecordWire.raw_prompt_snippet`. The CLI
            ``sase agents`` listing uses this; lookup paths don't.
        max_prompt_snippet_bytes: Upper bound on snippet length. Defaults
            to 200 (matches the existing Python truncation).
        only_workflow_dirs: When non-empty, restrict the scan to artifact
            workflow directory names that exactly match an entry. Useful
            for callers that only need ``ace-run`` data. ``None`` /
            empty means "scan every supported workflow family".
        max_records: Bound the number of completed/history records returned.
            Active or otherwise incomplete records are still returned so old
            running/waiting agents do not disappear from fallback startup
            scans.
        newest_first: Return records ordered by newest timestamp first instead
            of the deterministic full-scan order.
        not_before_timestamp: Exclude completed/history records older than this
            ``YYYYmmddHHMMSS`` timestamp. Active or otherwise incomplete
            records are still returned.
        include_done_markers: When False, expose ``has_done_marker`` but skip
            parsing ``done.json`` payloads.
        include_workflow_state: When False, skip ``workflow_state.json``.
        include_waiting: When False, skip ``waiting.json``.
        only_projects: When non-empty, restrict the scan to project directory
            names that exactly match an entry.
    """

    include_prompt_step_markers: bool = True
    include_raw_prompt_snippets: bool = True
    max_prompt_snippet_bytes: int = 200
    only_workflow_dirs: tuple[str, ...] = ()
    max_records: int | None = None
    newest_first: bool = False
    not_before_timestamp: str | None = None
    include_done_markers: bool = True
    include_workflow_state: bool = True
    include_waiting: bool = True
    only_projects: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentArtifactIndexQueryWire:
    """Query knobs for the persistent agent artifact index.

    The default query matches the Tier 1 startup use case: active/incomplete
    rows plus a bounded window of recently completed visible rows.
    """

    include_active: bool = True
    include_recent_completed: bool = True
    include_full_history: bool = False
    recent_completed_limit: int | None = 200
    include_hidden: bool = False


@dataclass(frozen=True)
class AgentArtifactIndexUpdateWire:
    """Summary returned by artifact index rebuild/upsert/delete operations."""

    schema_version: int
    index_path: str
    projects_root: str
    rows_indexed: int = 0
    rows_deleted: int = 0
    rows_skipped: int = 0


@dataclass(frozen=True)
class AgentArtifactIndexVerifyWire:
    """Summary returned by artifact index verification."""

    ok: bool
    schema_version: int
    index_path: str
    projects_root: str
    indexed_rows: int = 0
    source_rows: int = 0
    stale_rows: int = 0
    missing_rows: int = 0
    extra_rows: int = 0
    corrupt_rows: int = 0


@dataclass(frozen=True)
class AgentArtifactScanStatsWire:
    """Diagnostic counters for one snapshot scan.

    Counters are best-effort; they are intended for diagnostics and a
    future Rust dual-run comparator, not for behavior gating. Soft errors
    (unreadable directories, malformed marker JSON) are reflected here
    rather than raised so a single bad artifact never breaks a scan.

    Attributes:
        projects_visited: Number of project directories iterated.
        artifact_dirs_visited: Number of timestamp-directories iterated
            across all workflow families.
        marker_files_parsed: Number of marker files successfully decoded
            into the wire.
        json_decode_errors: Marker files that existed but failed JSON
            decode (or were not a JSON object where one was expected).
        os_errors: Marker files that could not be opened/stat'd
            (permissions, vanished mid-scan, etc).
        prompt_step_markers_parsed: Subset of ``marker_files_parsed`` for
            ``prompt_step_*.json`` markers.
    """

    projects_visited: int = 0
    artifact_dirs_visited: int = 0
    marker_files_parsed: int = 0
    json_decode_errors: int = 0
    os_errors: int = 0
    prompt_step_markers_parsed: int = 0


@dataclass(frozen=True)
class DoneMarkerWire:
    """Compact projection of ``done.json`` (one per finished agent).

    Attributes:
        outcome: ``"completed"`` / ``"failed"`` / ``"plan_rejected"`` /
            ``"noop"``. ``None`` when the marker omits the field.
        finished_at: Unix epoch seconds. Float because some writers emit
            fractional seconds. ``None`` when the field is missing or
            non-numeric.
        cl_name: ChangeSpec name recorded at completion.
        project_file: Absolute path to the project ``.gp`` file.
        workspace_num: Workspace number released on completion.
        workspace_dir: Resolved directory the agent ran in, when recorded.
        pid: PID of the agent process at completion (informational).
        model: Last LLM model recorded.
        llm_provider: Last LLM provider recorded.
        vcs_provider: VCS provider recorded.
        name: Agent name set via ``%name`` or TUI rename.
        plan_path: Path to a plan written by the agent (if any).
        diff_path: Path to a diff produced by the agent (if any).
        markdown_pdf_paths: Generated PDFs for Markdown files added or modified
            by the agent.
        image_paths: Image files added or modified by the agent.
        response_path: Path to the agent response transcript.
        output_path: Path to a per-agent log/output file.
        step_output: Last step's output dict, when the agent was a
            workflow step. JSON-safe leaves only.
        error: Error message recorded for failed agents.
        traceback: Traceback recorded for failed agents.
        retried_as_timestamp: Forward pointer to the spawn-on-retry child.
        retry_chain_root_timestamp: Root of a retry chain.
        retry_error_category: Category that triggered the retry.
        approve: Auto-approve flag from launch options.
        hidden: Hidden-from-TUI flag from launch options.
    """

    outcome: str | None = None
    finished_at: float | None = None
    cl_name: str | None = None
    project_file: str | None = None
    workspace_num: int | None = None
    workspace_dir: str | None = None
    pid: int | None = None
    model: str | None = None
    llm_provider: str | None = None
    vcs_provider: str | None = None
    name: str | None = None
    plan_path: str | None = None
    diff_path: str | None = None
    markdown_pdf_paths: list[str] = field(default_factory=list)
    image_paths: list[str] = field(default_factory=list)
    response_path: str | None = None
    output_path: str | None = None
    step_output: dict[str, Any] | None = None
    error: str | None = None
    traceback: str | None = None
    retried_as_timestamp: str | None = None
    retry_chain_root_timestamp: str | None = None
    retry_error_category: str | None = None
    approve: bool = False
    hidden: bool = False


@dataclass(frozen=True)
class AgentMetaWire:
    """Compact projection of ``agent_meta.json``.

    Carries the identity, scheduling, and retry-lineage fields that
    ``enrich_agent_from_meta`` and ``find_named_agent`` consult. Field
    docstrings on the source dataclasses (``Agent`` / ``RunningAgentInfo``)
    are the canonical reference for semantics.
    """

    name: str | None = None
    artifact_agent_id: str | None = None
    artifact_source_dir: str | None = None
    changespec_name: str | None = None
    cl_name: str | None = None
    bead_id: str | None = None
    plan_path: str | None = None
    sdd_prompt_path: str | None = None
    sdd_plan_path: str | None = None
    question_request_path: str | None = None
    question_response_path: str | None = None
    epic_bead_id: str | None = None
    phase_bead_id: str | None = None
    legend_bead_id: str | None = None
    commit_changespec_name: str | None = None
    commit_entry_id: str | None = None
    commit_result: str | None = None
    commit_diff_path: str | None = None
    parent_agent_timestamp: str | None = None
    parent_agent_name: str | None = None
    workflow_name: str | None = None
    pid: int | None = None
    model: str | None = None
    llm_provider: str | None = None
    vcs_provider: str | None = None
    role_suffix: str | None = None
    parent_timestamp: str | None = None
    workspace_num: int | None = None
    workspace_dir: str | None = None
    approve: bool = False
    auto_approve_plan_action: str | None = None
    hidden: bool = False
    plan: bool = False
    plan_approved: bool = False
    plan_action: str | None = None
    wait_for: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None
    plan_submitted_at: list[str] = field(default_factory=list)
    epic_started_at: str | None = None
    feedback_submitted_at: list[str] = field(default_factory=list)
    questions_submitted_at: list[str] = field(default_factory=list)
    retry_started_at: list[str] = field(default_factory=list)
    run_started_at: str | None = None
    stopped_at: str | None = None
    retry_of_timestamp: str | None = None
    retry_attempt: int | None = None
    retry_chain_root_timestamp: str | None = None
    retried_as_timestamp: str | None = None
    retry_terminal: bool = False
    retry_error_category: str | None = None


@dataclass(frozen=True)
class RunningMarkerWire:
    """Compact projection of ``running.json`` (home-mode running marker).

    Home-mode agents (``projects/home/...``) record liveness here instead
    of via the project ``.gp`` RUNNING field. The wire keeps only the
    fields the TUI loader and CLI listing actually consume.
    """

    pid: int | None = None
    cl_name: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    vcs_provider: str | None = None
    workspace_dir: str | None = None


@dataclass(frozen=True)
class WaitingMarkerWire:
    """Compact projection of ``waiting.json``.

    Overrides ``agent_meta.json`` wait fields when present. The TUI
    loader uses this to flip status from ``RUNNING`` to ``WAITING`` and
    to display an updated wait list edited from the TUI ``w`` keymap.
    """

    waiting_for: list[str] = field(default_factory=list)
    wait_duration: float | None = None
    wait_until: str | None = None


@dataclass(frozen=True)
class WorkflowStepStateWire:
    """One step entry from ``workflow_state.json``'s ``steps`` array."""

    name: str = ""
    status: str = "pending"
    output: dict[str, Any] | None = None
    output_types: dict[str, str] | None = None
    error: str | None = None
    traceback: str | None = None


@dataclass(frozen=True)
class WorkflowStateWire:
    """Compact projection of ``workflow_state.json``."""

    workflow_name: str = "unknown"
    cl_name: str | None = None
    status: str = "running"
    pid: int | None = None
    appears_as_agent: bool = False
    is_anonymous: bool = False
    current_step_index: int = 0
    start_time: str | None = None
    error: str | None = None
    traceback: str | None = None
    steps: list[WorkflowStepStateWire] = field(default_factory=list)


@dataclass(frozen=True)
class PromptStepMarkerWire:
    """Compact projection of one ``prompt_step_*.json`` marker.

    Only the fields used by ``load_workflow_agent_steps`` and parent
    workflow enrichment are carried.
    """

    file_name: str
    workflow_name: str = "unknown"
    step_name: str = "unknown"
    step_type: str = "agent"
    step_source: str | None = None
    step_index: int | None = None
    total_steps: int | None = None
    parent_step_index: int | None = None
    parent_total_steps: int | None = None
    status: str = "completed"
    hidden: bool = False
    is_pre_prompt_step: bool = False
    embedded_workflow_name: str | None = None
    artifacts_dir: str | None = None
    diff_path: str | None = None
    response_path: str | None = None
    error: str | None = None
    traceback: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    output: dict[str, Any] | None = None
    output_types: dict[str, str] | None = None


@dataclass(frozen=True)
class PlanPathMarkerWire:
    """Compact projection of ``plan_path.json``.

    The TUI workflow loader reads the ``plan_path`` field to surface a
    plan link on the WORKFLOW-typed agent.
    """

    plan_path: str | None = None


@dataclass(frozen=True)
class AgentArtifactRecordWire:
    """One artifact directory's parsed markers.

    A record carries the path identity needed to rebuild current Python
    behavior plus optional projections of every supported marker. Optional
    markers are ``None`` when the file is missing or skipped due to soft
    errors.

    Path identity fields are absolute strings so callers don't need to
    keep the ``projects_root`` around to rebuild paths. The
    ``timestamp`` field is the artifact directory name verbatim
    (typically 14 digits ``YYYYmmddHHMMSS``).

    Attributes:
        project_name: Directory name under ``projects/``
            (e.g. ``"home"`` or ``"myproj"``).
        project_dir: Absolute path to ``projects/<project_name>``.
        project_file: Absolute path to the project ``.gp`` file
            (``projects/<project_name>/<project_name>.gp``). The file may
            not exist; the path is computed deterministically.
        workflow_dir_name: Workflow folder name
            (e.g. ``"ace-run"``, ``"workflow-foo"``, ``"mentor-bryan"``).
        artifact_dir: Absolute path to the timestamp directory.
        timestamp: Directory name of the timestamp directory.
        agent_meta: Parsed ``agent_meta.json``, or ``None``.
        done: Parsed ``done.json``, or ``None``.
        running: Parsed ``running.json``, or ``None``.
        waiting: Parsed ``waiting.json``, or ``None``.
        workflow_state: Parsed ``workflow_state.json``, or ``None``.
        plan_path: Parsed ``plan_path.json``, or ``None``.
        prompt_steps: Sorted (by file name) list of parsed
            ``prompt_step_*.json`` markers. Empty when no prompt-step
            markers exist or the option was disabled.
        raw_prompt_snippet: Up to ``max_prompt_snippet_bytes`` of
            ``raw_xprompt.md`` content (stripped). ``None`` when the file
            is missing or the option was disabled.
        has_done_marker: ``True`` iff ``done.json`` exists in the dir
            (set even when JSON decoding fails — mirrors current
            ``done_path.exists()`` checks that don't require parseable
            content).
    """

    project_name: str
    project_dir: str
    project_file: str
    workflow_dir_name: str
    artifact_dir: str
    timestamp: str
    agent_meta: AgentMetaWire | None = None
    done: DoneMarkerWire | None = None
    running: RunningMarkerWire | None = None
    waiting: WaitingMarkerWire | None = None
    workflow_state: WorkflowStateWire | None = None
    plan_path: PlanPathMarkerWire | None = None
    prompt_steps: list[PromptStepMarkerWire] = field(default_factory=list)
    raw_prompt_snippet: str | None = None
    has_done_marker: bool = False


@dataclass(frozen=True)
class AgentArtifactScanWire:
    """Top-level snapshot returned by :func:`scan_agent_artifacts`.

    Records are sorted deterministically by
    ``(project_name, workflow_dir_name, timestamp)`` so a Rust port can
    reproduce the order without extra agreement.

    Attributes:
        schema_version: Bumped on incompatible shape changes.
        projects_root: Absolute path that was scanned.
        options: The :class:`AgentArtifactScanOptionsWire` used.
        stats: Diagnostic counters from the scan.
        records: One :class:`AgentArtifactRecordWire` per artifact dir.
    """

    schema_version: int
    projects_root: str
    options: AgentArtifactScanOptionsWire
    stats: AgentArtifactScanStatsWire
    records: list[AgentArtifactRecordWire] = field(default_factory=list)


def agent_scan_wire_to_json_dict(record: Any) -> Any:
    """Project an agent-scan wire record (or list of them) to a JSON-safe shape.

    Mirrors :func:`sase.core.wire.to_json_dict` but is local to this module
    so the agent-scan wire stays independent of the changespec wire's
    schema bumps.
    """
    if isinstance(record, (list, tuple)):
        return [agent_scan_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: agent_scan_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


def _options_from_dict(data: dict[str, Any]) -> AgentArtifactScanOptionsWire:
    return AgentArtifactScanOptionsWire(
        include_prompt_step_markers=bool(data.get("include_prompt_step_markers", True)),
        include_raw_prompt_snippets=bool(data.get("include_raw_prompt_snippets", True)),
        max_prompt_snippet_bytes=int(data.get("max_prompt_snippet_bytes", 200)),
        only_workflow_dirs=tuple(data.get("only_workflow_dirs") or ()),
        max_records=(
            None
            if data.get("max_records") is None
            else int(data.get("max_records") or 0)
        ),
        newest_first=bool(data.get("newest_first", False)),
        not_before_timestamp=data.get("not_before_timestamp"),
        include_done_markers=bool(data.get("include_done_markers", True)),
        include_workflow_state=bool(data.get("include_workflow_state", True)),
        include_waiting=bool(data.get("include_waiting", True)),
        only_projects=tuple(data.get("only_projects") or ()),
    )


def agent_artifact_index_query_to_dict(
    query: AgentArtifactIndexQueryWire,
) -> dict[str, Any]:
    return {
        "include_active": query.include_active,
        "include_recent_completed": query.include_recent_completed,
        "include_full_history": query.include_full_history,
        "recent_completed_limit": query.recent_completed_limit,
        "include_hidden": query.include_hidden,
    }


def agent_artifact_index_update_from_dict(
    data: dict[str, Any],
) -> AgentArtifactIndexUpdateWire:
    return AgentArtifactIndexUpdateWire(
        schema_version=int(data["schema_version"]),
        index_path=str(data["index_path"]),
        projects_root=str(data.get("projects_root") or ""),
        rows_indexed=int(data.get("rows_indexed", 0)),
        rows_deleted=int(data.get("rows_deleted", 0)),
        rows_skipped=int(data.get("rows_skipped", 0)),
    )


def _stats_from_dict(data: dict[str, Any]) -> AgentArtifactScanStatsWire:
    return AgentArtifactScanStatsWire(
        projects_visited=int(data.get("projects_visited", 0)),
        artifact_dirs_visited=int(data.get("artifact_dirs_visited", 0)),
        marker_files_parsed=int(data.get("marker_files_parsed", 0)),
        json_decode_errors=int(data.get("json_decode_errors", 0)),
        os_errors=int(data.get("os_errors", 0)),
        prompt_step_markers_parsed=int(data.get("prompt_step_markers_parsed", 0)),
    )


def _record_from_dict(data: dict[str, Any]) -> AgentArtifactRecordWire:
    agent_meta = data.get("agent_meta")
    done = data.get("done")
    running = data.get("running")
    waiting = data.get("waiting")
    workflow_state = data.get("workflow_state")
    plan_path = data.get("plan_path")
    return AgentArtifactRecordWire(
        project_name=data["project_name"],
        project_dir=data["project_dir"],
        project_file=data["project_file"],
        workflow_dir_name=data["workflow_dir_name"],
        artifact_dir=data["artifact_dir"],
        timestamp=data["timestamp"],
        agent_meta=AgentMetaWire(**agent_meta)
        if isinstance(agent_meta, dict)
        else None,
        done=DoneMarkerWire(**done) if isinstance(done, dict) else None,
        running=RunningMarkerWire(**running) if isinstance(running, dict) else None,
        waiting=WaitingMarkerWire(**waiting) if isinstance(waiting, dict) else None,
        workflow_state=(
            _workflow_state_from_dict(workflow_state)
            if isinstance(workflow_state, dict)
            else None
        ),
        plan_path=PlanPathMarkerWire(**plan_path)
        if isinstance(plan_path, dict)
        else None,
        prompt_steps=[
            PromptStepMarkerWire(**step) for step in data.get("prompt_steps") or []
        ],
        raw_prompt_snippet=data.get("raw_prompt_snippet"),
        has_done_marker=bool(data.get("has_done_marker", False)),
    )


def _workflow_state_from_dict(data: dict[str, Any]) -> WorkflowStateWire:
    raw_steps = data.get("steps") or []
    steps = [WorkflowStepStateWire(**step) for step in raw_steps]
    payload = {k: v for k, v in data.items() if k != "steps"}
    return WorkflowStateWire(steps=steps, **payload)


def agent_scan_wire_from_dict(data: dict[str, Any]) -> AgentArtifactScanWire:
    """Rehydrate an :class:`AgentArtifactScanWire` from a JSON-safe dict.

    Inverse of :func:`agent_scan_wire_to_json_dict`. Used by the facade's
    Rust adapter (the PyO3 binding returns plain Python dicts/lists) and
    by tests that round-trip the snapshot through JSON.

    Missing optional fields fall back to dataclass defaults; unknown keys
    raise ``TypeError`` from the dataclass constructors so a wire-version
    drift surfaces immediately.
    """
    options = _options_from_dict(data.get("options") or {})
    stats = _stats_from_dict(data.get("stats") or {})
    records = [_record_from_dict(r) for r in data.get("records") or []]
    return AgentArtifactScanWire(
        schema_version=int(data["schema_version"]),
        projects_root=data["projects_root"],
        options=options,
        stats=stats,
        records=records,
    )


__all__ = [
    "AGENT_SCAN_WIRE_SCHEMA_VERSION",
    "DONE_WORKFLOW_DIR_NAMES",
    "DONE_WORKFLOW_DIR_PREFIXES",
    "WORKFLOW_STATE_DIR_NAMES",
    "WORKFLOW_STATE_DIR_PREFIXES",
    "AgentArtifactRecordWire",
    "AgentArtifactIndexVerifyWire",
    "AgentArtifactScanOptionsWire",
    "AgentArtifactScanStatsWire",
    "AgentArtifactScanWire",
    "AgentMetaWire",
    "DoneMarkerWire",
    "PlanPathMarkerWire",
    "PromptStepMarkerWire",
    "RunningMarkerWire",
    "WaitingMarkerWire",
    "WorkflowStateWire",
    "WorkflowStepStateWire",
    "agent_scan_wire_from_dict",
    "agent_scan_wire_to_json_dict",
]
