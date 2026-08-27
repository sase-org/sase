"""Top-level scan/record/options wire dataclasses for the agent scan facade.

Split out of :mod:`sase.core.agent_scan_wire` to keep each module under the
500-line cap. The records here are the snapshot scaffolding (scan options,
diagnostic stats, the per-artifact record, and the top-level scan wire). The
per-file marker projections live in
:mod:`sase.core.agent_scan_wire_markers` and the JSON conversion helpers in
:mod:`sase.core.agent_scan_wire_conversion`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sase.core.agent_scan_wire_markers import (
    AgentMetaWire,
    DoneMarkerWire,
    PendingQuestionMarkerWire,
    PlanPathMarkerWire,
    PromptStepMarkerWire,
    RunningMarkerWire,
    UsedXPromptWire,
    WaitingMarkerWire,
    WorkflowStateWire,
)

AGENT_SCAN_WIRE_SCHEMA_VERSION = 7
AGENT_ARTIFACT_INDEX_SCHEMA_VERSION = 24
AgentArtifactRecordShape = Literal["full", "list"]

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
            ``sase agent`` listing uses this; lookup paths don't.
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
        include_project_states: When non-empty, restrict the scan to projects
            whose ProjectSpec lifecycle state matches one of these values
            (``active``, ``inactive``, or ``sibling``; legacy ``archived`` /
            ``closed`` aliases normalize to ``inactive``). ``"all"`` or an
            empty tuple disables lifecycle filtering.
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
    include_project_states: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentArtifactIndexQueryWire:
    """Query knobs for the persistent agent artifact index.

    The default query matches the Tier 1 startup use case: all active or
    otherwise incomplete visible rows plus a bounded window of recently
    completed visible rows.

    Attributes:
        only_monitors: Restrict results to monitor family members
            (``agent_meta.agent_family_role == "monitor"``), so
            ``sase monitor list`` can ask the index directly instead of
            scanning and filtering every record in Python.
    """

    include_active: bool = True
    include_recent_completed: bool = True
    include_full_history: bool = False
    active_limit: int | None = None
    recent_completed_limit: int | None = 200
    include_hidden: bool = False
    freshness: Literal["revalidate", "cached"] = "revalidate"
    only_monitors: bool = False
    record_shape: AgentArtifactRecordShape = "full"


@dataclass(frozen=True)
class AgentArtifactIndexUpdateWire:
    """Summary returned by artifact index rebuild/upsert/delete operations."""

    schema_version: int
    index_path: str
    projects_root: str
    rows_indexed: int = 0
    rows_deleted: int = 0
    rows_skipped: int = 0
    hidden_terminal_rows_retained: int = 0
    hidden_terminal_rows_pruned: int = 0


@dataclass(frozen=True)
class AgentArtifactIndexStatusWire:
    """Lightweight row-count status for the persistent artifact index."""

    schema_version: int
    index_path: str
    agent_artifacts_rows: int = 0
    dismissed_agents_rows: int = 0
    agent_artifact_aliases_rows: int = 0
    agent_output_variables_rows: int = 0
    agent_artifact_model_aliases_rows: int = 0
    hidden_terminal_retention_limit: int = 0
    hidden_terminal_rows_retained: int = 0
    hidden_terminal_rows_prunable: int = 0
    freelist_pages: int = 0
    freelist_bytes: int = 0
    file_size_bytes: int = 0


@dataclass(frozen=True)
class AgentArtifactIndexVacuumWire:
    """Outcome of one VACUUM compaction pass over the artifact index."""

    index_path: str
    freelist_pages_before: int = 0
    freelist_pages_after: int = 0
    file_size_bytes_before: int = 0
    file_size_bytes_after: int = 0
    bytes_reclaimed: int = 0


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
        pending_question: Parsed ``pending_question.json``, or ``None``.
        workflow_state: Parsed ``workflow_state.json``, or ``None``.
        plan_path: Parsed ``plan_path.json``, or ``None``.
        prompt_steps: Sorted (by file name) list of parsed
            ``prompt_step_*.json`` markers. Empty when no prompt-step
            markers exist or the option was disabled.
        raw_prompt_snippet: Up to ``max_prompt_snippet_bytes`` of
            ``raw_xprompt.md`` content (stripped). ``None`` when the file
            is missing or the option was disabled.
        used_xprompts: Launch-boundary ``xprompts.json`` entries collapsed
            by name and sorted by name. Empty when the file is missing,
            unreadable, or carried no usable entry.
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
    pending_question: PendingQuestionMarkerWire | None = None
    workflow_state: WorkflowStateWire | None = None
    plan_path: PlanPathMarkerWire | None = None
    prompt_steps: list[PromptStepMarkerWire] = field(default_factory=list)
    raw_prompt_snippet: str | None = None
    used_xprompts: list[UsedXPromptWire] = field(default_factory=list)
    has_done_marker: bool = False
    record_shape: AgentArtifactRecordShape = "full"


@dataclass(frozen=True)
class AgentClanContextWire:
    """Resolved semantic attributes for one represented clan generation."""

    agent_clan: str
    agent_clan_generation: str | None = None
    clan_tribe: str | None = None
    clan_summary: str | None = None
    clan_tribe_source_launch_timestamp: str | None = None
    clan_tribe_source_identity: str | None = None
    clan_summary_source_launch_timestamp: str | None = None
    clan_summary_source_identity: str | None = None


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
    clan_context: list[AgentClanContextWire] = field(default_factory=list)


__all__ = [
    "AGENT_ARTIFACT_INDEX_SCHEMA_VERSION",
    "AGENT_SCAN_WIRE_SCHEMA_VERSION",
    "AgentArtifactIndexQueryWire",
    "AgentArtifactRecordShape",
    "AgentArtifactIndexStatusWire",
    "AgentArtifactIndexUpdateWire",
    "AgentArtifactIndexVerifyWire",
    "AgentArtifactRecordWire",
    "AgentArtifactScanOptionsWire",
    "AgentArtifactScanStatsWire",
    "AgentArtifactScanWire",
    "AgentClanContextWire",
    "DONE_WORKFLOW_DIR_NAMES",
    "DONE_WORKFLOW_DIR_PREFIXES",
    "WORKFLOW_STATE_DIR_NAMES",
    "WORKFLOW_STATE_DIR_PREFIXES",
]
