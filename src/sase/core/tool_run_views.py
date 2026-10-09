"""Typed ToolRun view rows over the ``sase_core_rs`` wire.

Pure dataclasses built from result wires with ``from_wire`` constructors
that ignore unknown keys. No store paths, no Rust calls here: the ledger
facade in ``sase.core.tool_run`` owns every binding invocation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


def _optional_str(value: Any) -> str | None:
    """Return *value* as text, or None when it is absent."""

    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    """Return *value* as an int, or None when it is absent or blank."""

    if value is None or value is True or value is False:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count(value: Any) -> int:
    """Return *value* as a non-negative count, tolerating dirty wires."""

    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class ToolRunVerdictSummary:
    """One shared triage verdict with its §3.2 state-vocabulary bucket."""

    bucket: str
    verdict: str | None = None
    failure_kind: str | None = None
    reasons: tuple[str, ...] = ()
    new: int = 0
    known: int = 0
    flaky: int = 0
    unknown: int = 0
    unlabeled: int = 0

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunVerdictSummary:
        """Build a summary from a result wire, ignoring unknown keys."""

        raw = data.get("reasons") or ()
        reasons = (
            tuple(str(item) for item in raw)
            if isinstance(raw, (list, tuple))
            else (str(raw),)
        )
        return cls(
            bucket=str(data.get("bucket") or "undetermined"),
            verdict=_optional_str(data.get("verdict")),
            failure_kind=_optional_str(data.get("failure_kind")),
            reasons=reasons,
            new=_count(data.get("new")),
            known=_count(data.get("known")),
            flaky=_count(data.get("flaky")),
            unknown=_count(data.get("unknown")),
            unlabeled=_count(data.get("unlabeled")),
        )


@dataclass(frozen=True)
class ToolRunGlanceStage:
    """The in-flight stage of a live run; stamps are milliseconds."""

    description: str
    started_ms: int

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunGlanceStage:
        """Build a stage from a result wire, ignoring unknown keys."""

        return cls(
            description=str(data.get("description") or ""),
            started_ms=_count(data.get("started_ms")),
        )


@dataclass(frozen=True)
class ToolRunGlance:
    """One unsettled run: identity, attribution, timing, and progress."""

    run_id: str
    label: str
    state: str
    created_ts: int
    last_activity_ts: int
    stages_done: int = 0
    stop_requested: bool = False
    typical_samples: int = 0
    tool_name: str | None = None
    launch_mode: str | None = None
    project: str | None = None
    agent: str | None = None
    workspace: str | None = None
    bead: str | None = None
    owner_kind: str | None = None
    owner_id: str | None = None
    join_kind: str | None = None
    join_id: str | None = None
    parent_run_id: str | None = None
    running_ts: int | None = None
    current_stage: ToolRunGlanceStage | None = None
    stages_expected: int | None = None
    reference_run_id: str | None = None
    typical_ms: int | None = None

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunGlance:
        """Build a glance row from a result wire, ignoring unknown keys."""

        stage = data.get("current_stage")
        return cls(
            run_id=str(data.get("run_id") or ""),
            label=str(data.get("label") or ""),
            state=str(data.get("state") or ""),
            created_ts=_count(data.get("created_ts")),
            last_activity_ts=_count(data.get("last_activity_ts")),
            stages_done=_count(data.get("stages_done")),
            stop_requested=bool(data.get("stop_requested", False)),
            typical_samples=_count(data.get("typical_samples")),
            tool_name=_optional_str(data.get("tool_name")),
            launch_mode=_optional_str(data.get("launch_mode")),
            project=_optional_str(data.get("project")),
            agent=_optional_str(data.get("agent")),
            workspace=_optional_str(data.get("workspace")),
            bead=_optional_str(data.get("bead")),
            owner_kind=_optional_str(data.get("owner_kind")),
            owner_id=_optional_str(data.get("owner_id")),
            join_kind=_optional_str(data.get("join_kind")),
            join_id=_optional_str(data.get("join_id")),
            parent_run_id=_optional_str(data.get("parent_run_id")),
            running_ts=_optional_int(data.get("running_ts")),
            current_stage=(
                ToolRunGlanceStage.from_wire(stage)
                if isinstance(stage, Mapping)
                else None
            ),
            stages_expected=_optional_int(data.get("stages_expected")),
            reference_run_id=_optional_str(data.get("reference_run_id")),
            typical_ms=_optional_int(data.get("typical_ms")),
        )


def _undetermined_verdict() -> ToolRunVerdictSummary:
    """Return the fallback verdict when a wire carries none."""

    return ToolRunVerdictSummary(bucket="undetermined")


@dataclass(frozen=True)
class ToolRunBrief:
    """One lean run row: outcome, attribution, timing, verdict, pruning flags."""

    run_id: str
    label: str
    state: str
    created_ts: int
    verdict: ToolRunVerdictSummary = field(default_factory=_undetermined_verdict)
    detail_pruned: bool = False
    stop_requested: bool = False
    tool_name: str | None = None
    launch_mode: str | None = None
    exit_code: int | None = None
    signal: int | None = None
    terminal_cause: str | None = None
    project: str | None = None
    agent: str | None = None
    workspace: str | None = None
    bead: str | None = None
    owner_kind: str | None = None
    owner_id: str | None = None
    parent_run_id: str | None = None
    running_ts: int | None = None
    settled_ts: int | None = None
    duration_ms: int | None = None
    typical_ms: int | None = None

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunBrief:
        """Build a brief row from a result wire, ignoring unknown keys."""

        verdict = data.get("verdict")
        return cls(
            run_id=str(data.get("run_id") or ""),
            label=str(data.get("label") or ""),
            state=str(data.get("state") or ""),
            created_ts=_count(data.get("created_ts")),
            verdict=(
                ToolRunVerdictSummary.from_wire(verdict)
                if isinstance(verdict, Mapping)
                else ToolRunVerdictSummary(bucket="undetermined")
            ),
            detail_pruned=bool(data.get("detail_pruned", False)),
            stop_requested=bool(data.get("stop_requested", False)),
            tool_name=_optional_str(data.get("tool_name")),
            launch_mode=_optional_str(data.get("launch_mode")),
            exit_code=_optional_int(data.get("exit_code")),
            signal=_optional_int(data.get("signal")),
            terminal_cause=_optional_str(data.get("terminal_cause")),
            project=_optional_str(data.get("project")),
            agent=_optional_str(data.get("agent")),
            workspace=_optional_str(data.get("workspace")),
            bead=_optional_str(data.get("bead")),
            owner_kind=_optional_str(data.get("owner_kind")),
            owner_id=_optional_str(data.get("owner_id")),
            parent_run_id=_optional_str(data.get("parent_run_id")),
            running_ts=_optional_int(data.get("running_ts")),
            settled_ts=_optional_int(data.get("settled_ts")),
            duration_ms=_optional_int(data.get("duration_ms")),
            typical_ms=_optional_int(data.get("typical_ms")),
        )


@dataclass(frozen=True)
class ToolRunNodeSummary:
    """Per-node history for one TUI node selector."""

    key: str
    total_runs: int = 0
    truncated: bool = False
    live: tuple[ToolRunGlance, ...] = ()
    latest_by_tool: tuple[ToolRunBrief, ...] = ()
    runs: tuple[ToolRunBrief, ...] = ()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunNodeSummary:
        """Build a node summary from a result wire, ignoring unknown keys."""

        def _glances(value: Any) -> tuple[ToolRunGlance, ...]:
            if not isinstance(value, (list, tuple)):
                return ()
            return tuple(
                ToolRunGlance.from_wire(item)
                for item in value
                if isinstance(item, Mapping)
            )

        def _briefs(value: Any) -> tuple[ToolRunBrief, ...]:
            if not isinstance(value, (list, tuple)):
                return ()
            return tuple(
                ToolRunBrief.from_wire(item)
                for item in value
                if isinstance(item, Mapping)
            )

        return cls(
            key=str(data.get("key") or ""),
            total_runs=_count(data.get("total_runs")),
            truncated=bool(data.get("truncated", False)),
            live=_glances(data.get("live")),
            latest_by_tool=_briefs(data.get("latest_by_tool")),
            runs=_briefs(data.get("runs")),
        )


@dataclass(frozen=True)
class ToolRunLiveGlance:
    """Every unsettled run on the machine, newest first and capped."""

    store_exists: bool
    silent_after_s: int = 60
    truncated: bool = False
    runs: tuple[ToolRunGlance, ...] = ()
    last_write_ts: int | None = None
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunLiveGlance:
        """Build a glance result from a result wire, ignoring unknown keys."""

        runs = data.get("runs")
        diagnostics = data.get("diagnostics") or ()
        return cls(
            store_exists=bool(data.get("store_exists", False)),
            silent_after_s=_count(data.get("silent_after_s", 60)),
            truncated=bool(data.get("truncated", False)),
            runs=(
                tuple(
                    ToolRunGlance.from_wire(item)
                    for item in runs
                    if isinstance(item, Mapping)
                )
                if isinstance(runs, (list, tuple))
                else ()
            ),
            last_write_ts=_optional_int(data.get("last_write_ts")),
            diagnostics=(
                tuple(str(item) for item in diagnostics)
                if isinstance(diagnostics, (list, tuple))
                else ()
            ),
        )


@dataclass(frozen=True)
class ToolRunBriefs:
    """The lean filtered run list."""

    store_exists: bool
    runs: tuple[ToolRunBrief, ...] = ()
    next_cursor: str | None = None
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunBriefs:
        """Build a briefs result from a result wire, ignoring unknown keys."""

        runs = data.get("runs")
        diagnostics = data.get("diagnostics") or ()
        return cls(
            store_exists=bool(data.get("store_exists", False)),
            runs=(
                tuple(
                    ToolRunBrief.from_wire(item)
                    for item in runs
                    if isinstance(item, Mapping)
                )
                if isinstance(runs, (list, tuple))
                else ()
            ),
            next_cursor=_optional_str(data.get("next_cursor")),
            diagnostics=(
                tuple(str(item) for item in diagnostics)
                if isinstance(diagnostics, (list, tuple))
                else ()
            ),
        )


@dataclass(frozen=True)
class ToolRunNodeSummaries:
    """Per-node history for the requested TUI node selectors."""

    store_exists: bool
    silent_after_s: int = 60
    nodes: tuple[ToolRunNodeSummary, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunNodeSummaries:
        """Build a summaries result from a result wire, ignoring unknown keys."""

        nodes = data.get("nodes")
        diagnostics = data.get("diagnostics") or ()
        return cls(
            store_exists=bool(data.get("store_exists", False)),
            silent_after_s=_count(data.get("silent_after_s", 60)),
            nodes=(
                tuple(
                    ToolRunNodeSummary.from_wire(item)
                    for item in nodes
                    if isinstance(item, Mapping)
                )
                if isinstance(nodes, (list, tuple))
                else ()
            ),
            diagnostics=(
                tuple(str(item) for item in diagnostics)
                if isinstance(diagnostics, (list, tuple))
                else ()
            ),
        )


@dataclass(frozen=True)
class ToolRunDetailStageCounts:
    """Per-stage triage counts for one detail stage row."""

    new: int = 0
    known: int = 0
    flaky: int = 0
    unknown: int = 0

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunDetailStageCounts:
        """Build stage counts from a result wire, ignoring unknown keys."""

        if not isinstance(data, Mapping):
            return cls()
        return cls(
            new=_count(data.get("new")),
            known=_count(data.get("known")),
            flaky=_count(data.get("flaky")),
            unknown=_count(data.get("unknown")),
        )


@dataclass(frozen=True)
class ToolRunDetailStage:
    """One stage of a run; every stamp is milliseconds and says so."""

    description: str
    incomplete: bool = False
    started_ms: int | None = None
    finished_ms: int | None = None
    elapsed_ms: int | None = None
    exit_code: int | None = None
    output_bytes: int | None = None
    counts: ToolRunDetailStageCounts = field(default_factory=ToolRunDetailStageCounts)

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunDetailStage:
        """Build a stage row from a result wire, ignoring unknown keys."""

        return cls(
            description=str(data.get("description") or ""),
            incomplete=bool(data.get("incomplete", False)),
            started_ms=_optional_int(data.get("started_ms")),
            finished_ms=_optional_int(data.get("finished_ms")),
            elapsed_ms=_optional_int(data.get("elapsed_ms")),
            exit_code=_optional_int(data.get("exit_code")),
            output_bytes=_optional_int(data.get("output_bytes")),
            counts=ToolRunDetailStageCounts.from_wire(data.get("counts") or {}),
        )


@dataclass(frozen=True)
class ToolRunExpectedStage:
    """One stage of the reference run behind pending/not-reached rows."""

    description: str
    elapsed_ms: int | None = None

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunExpectedStage:
        """Build an expected stage from a result wire, ignoring unknown keys."""

        return cls(
            description=str(data.get("description") or ""),
            elapsed_ms=_optional_int(data.get("elapsed_ms")),
        )


@dataclass(frozen=True)
class ToolRunDetailTriageItem:
    """One witnessed triage item; ``class`` is absent for unlabeled items."""

    stage_key: str
    display: str
    occurrences: int = 0
    witness_runs: int = 0
    witness_agents: int = 0
    item_class: str | None = None
    locator_paths: tuple[str, ...] = ()
    first_seen_ts: int | None = None
    last_seen_ts: int | None = None

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunDetailTriageItem:
        """Build a triage item from a result wire, ignoring unknown keys."""

        raw_paths = data.get("locator_paths") or ()
        paths = (
            tuple(str(item) for item in raw_paths)
            if isinstance(raw_paths, (list, tuple))
            else ()
        )
        return cls(
            stage_key=str(data.get("stage_key") or ""),
            display=str(data.get("display") or ""),
            occurrences=_count(data.get("occurrences")),
            witness_runs=_count(data.get("witness_runs")),
            witness_agents=_count(data.get("witness_agents")),
            item_class=_optional_str(data.get("class")),
            locator_paths=paths,
            first_seen_ts=_optional_int(data.get("first_seen_ts")),
            last_seen_ts=_optional_int(data.get("last_seen_ts")),
        )


@dataclass(frozen=True)
class ToolRunLogMetadata:
    """Log retention metadata for one run; never a log body."""

    has_private_argv: bool = False
    stdout_path: str | None = None
    stderr_path: str | None = None
    events_path: str | None = None
    owner_log_path: str | None = None

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunLogMetadata:
        """Build log metadata from a result wire, ignoring unknown keys."""

        if not isinstance(data, Mapping):
            return cls()
        return cls(
            has_private_argv=bool(data.get("has_private_argv", False)),
            stdout_path=_optional_str(data.get("stdout_path")),
            stderr_path=_optional_str(data.get("stderr_path")),
            events_path=_optional_str(data.get("events_path")),
            owner_log_path=_optional_str(data.get("owner_log_path")),
        )

    def to_tail_metadata(self) -> dict[str, Any]:
        """Return the ``tool_run_log_tail`` metadata map for this run."""

        return {
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "events_path": self.events_path,
            "owner_log_path": self.owner_log_path,
        }


@dataclass(frozen=True)
class ToolRunDetail:
    """One run for one card block: brief, argv, stages, items, children."""

    store_exists: bool
    found: bool
    display_argv: tuple[str, ...] = ()
    stages: tuple[ToolRunDetailStage, ...] = ()
    expected_stages: tuple[ToolRunExpectedStage, ...] = ()
    triage_items: tuple[ToolRunDetailTriageItem, ...] = ()
    child_runs: tuple[ToolRunBrief, ...] = ()
    logs: ToolRunLogMetadata = field(default_factory=ToolRunLogMetadata)
    brief: ToolRunBrief | None = None
    items_truncated: bool = False
    detail_pruned: bool = False
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def from_wire(cls, data: Mapping[str, Any]) -> ToolRunDetail:
        """Build a detail result from a result wire, ignoring unknown keys."""

        def _stages(value: Any) -> tuple[ToolRunDetailStage, ...]:
            if not isinstance(value, (list, tuple)):
                return ()
            return tuple(
                ToolRunDetailStage.from_wire(item)
                for item in value
                if isinstance(item, Mapping)
            )

        def _expected(value: Any) -> tuple[ToolRunExpectedStage, ...]:
            if not isinstance(value, (list, tuple)):
                return ()
            return tuple(
                ToolRunExpectedStage.from_wire(item)
                for item in value
                if isinstance(item, Mapping)
            )

        def _items(value: Any) -> tuple[ToolRunDetailTriageItem, ...]:
            if not isinstance(value, (list, tuple)):
                return ()
            return tuple(
                ToolRunDetailTriageItem.from_wire(item)
                for item in value
                if isinstance(item, Mapping)
            )

        def _briefs(value: Any) -> tuple[ToolRunBrief, ...]:
            if not isinstance(value, (list, tuple)):
                return ()
            return tuple(
                ToolRunBrief.from_wire(item)
                for item in value
                if isinstance(item, Mapping)
            )

        brief = data.get("brief")
        logs = data.get("logs")
        diagnostics = data.get("diagnostics") or ()
        argv = data.get("display_argv") or ()
        return cls(
            store_exists=bool(data.get("store_exists", False)),
            found=bool(data.get("found", False)),
            display_argv=(
                tuple(str(item) for item in argv)
                if isinstance(argv, (list, tuple))
                else ()
            ),
            stages=_stages(data.get("stages")),
            expected_stages=_expected(data.get("expected_stages")),
            triage_items=_items(data.get("triage_items")),
            child_runs=_briefs(data.get("child_runs")),
            logs=(
                ToolRunLogMetadata.from_wire(logs)
                if isinstance(logs, Mapping)
                else ToolRunLogMetadata()
            ),
            brief=(
                ToolRunBrief.from_wire(brief) if isinstance(brief, Mapping) else None
            ),
            items_truncated=bool(data.get("items_truncated", False)),
            detail_pruned=bool(data.get("detail_pruned", False)),
            diagnostics=(
                tuple(str(item) for item in diagnostics)
                if isinstance(diagnostics, (list, tuple))
                else ()
            ),
        )


__all__ = [
    "ToolRunBrief",
    "ToolRunBriefs",
    "ToolRunDetail",
    "ToolRunDetailStage",
    "ToolRunDetailStageCounts",
    "ToolRunDetailTriageItem",
    "ToolRunExpectedStage",
    "ToolRunGlance",
    "ToolRunGlanceStage",
    "ToolRunLiveGlance",
    "ToolRunLogMetadata",
    "ToolRunNodeSummaries",
    "ToolRunNodeSummary",
    "ToolRunVerdictSummary",
]
