"""Frontend-neutral view of per-alias agent history.

This is the seam between :func:`sase.core.agent_scan_facade.query_agent_alias_history`
and any surface that renders it. Provenance classification lives here so a TUI,
CLI, or future web frontend cannot drift on the four pinned cases.

The adapter composes the core query with the configured per-alias limit, maps
each run's ProjectSpec key to a configured project name, classifies provenance
from ``alias_position`` and ``model_alias_origin``, and returns typed view
models that already carry truncation state, a done/failed/running rollup, and
an unformatted duration in seconds.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.core.agent_alias_history_wire import (
    DEFAULT_ALIAS_HISTORY_PROMPT_SNIPPET_BYTES,
    AgentAliasHistoryGroupWire,
    AgentAliasHistoryQueryWire,
    AgentAliasHistoryWire,
    AgentAliasRunWire,
)
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    query_agent_alias_history,
)
from sase.core.agent_scan_wire_markers import UsedXPromptWire
from sase.core.time import parse_local
from sase.project_display_names import ProjectDisplaySnapshot, project_display_name_for

from .config import get_model_alias_history_limit
from .launch_selection import ALIAS_ORIGIN_DEFAULT_MODEL, ALIAS_ORIGIN_DIRECTIVE

AliasHistoryProvenanceKind = Literal["direct", "default", "indirect", "unrecorded"]
AliasHistoryRollupStatus = Literal["done", "failed", "running"]
AliasHistoryFreshness = Literal["cached", "revalidate"]

_FAILED_STATUSES = frozenset({"failed"})
_RUNNING_STATUSES = frozenset({"running", "starting", "waiting"})


@dataclass(frozen=True, slots=True)
class _AliasHistoryProvenance:
    """How the queried alias entered one run.

    ``label`` is the four-way chip text (``direct`` / ``default`` /
    ``via @<prev>`` / ``unrecorded``). ``origin`` is the raw recorded origin
    when present — including on indirect rows, whose origin describes the
    *entry* alias rather than the queried hop.
    """

    kind: AliasHistoryProvenanceKind
    label: str
    origin: str | None = None
    via_alias: str | None = None


@dataclass(frozen=True, slots=True)
class _AliasHistoryStatusRollup:
    """Title-line counts over the returned window of runs."""

    done: int = 0
    failed: int = 0
    running: int = 0

    @property
    def total(self) -> int:
        """Return the sum of the three title-line buckets."""
        return self.done + self.failed + self.running


@dataclass(frozen=True, slots=True)
class AliasHistoryRun:
    """One display-ready run in an alias-history group."""

    artifact_dir: str
    project_key: str
    project_name: str
    workflow_dir_name: str
    timestamp: str
    alias_position: int
    status: str
    has_done_marker: bool
    hidden: bool
    provenance: _AliasHistoryProvenance
    rollup_status: AliasHistoryRollupStatus
    agent_name: str | None = None
    workflow_name: str | None = None
    model: str | None = None
    llm_provider: str | None = None
    reasoning_effort: str | None = None
    model_alias: str | None = None
    model_alias_origin: str | None = None
    model_alias_trail: tuple[str, ...] = ()
    workflow_status: str | None = None
    started_at: str | None = None
    finished_at: float | None = None
    duration_seconds: float | None = None
    retry_attempt: int | None = None
    bead_id: str | None = None
    cl_name: str | None = None
    workspace_num: int | None = None
    prompt_snippet: str | None = None
    used_xprompts: tuple[UsedXPromptWire, ...] = ()


@dataclass(frozen=True, slots=True)
class AliasHistoryGroup:
    """History for one requested alias, including truncation metadata."""

    alias: str
    limit: int
    total_count: int
    returned_count: int
    truncated: bool
    status_rollup: _AliasHistoryStatusRollup
    runs: tuple[AliasHistoryRun, ...] = ()


@dataclass(frozen=True, slots=True)
class AliasHistoryView:
    """Bounded, presentation-neutral alias-history snapshot."""

    index_path: str
    aliases: tuple[str, ...]
    limit_per_alias: int
    include_hidden: bool
    projects: tuple[str, ...]
    freshness: AliasHistoryFreshness
    groups: tuple[AliasHistoryGroup, ...]
    status_rollup: _AliasHistoryStatusRollup


def _classify_alias_history_provenance(
    alias_position: int,
    origin: str | None,
    trail: Sequence[str] = (),
) -> _AliasHistoryProvenance:
    """Classify one run into the four pinned provenance cases.

    ``alias_position > 0`` is always indirect — the recorded origin describes
    the entry alias, not this hop. A missing or unknown origin is unrecorded
    and never raises.
    """
    recorded_origin = _normalize_origin(origin)
    if alias_position > 0:
        via_alias = _previous_alias(alias_position, trail)
        label = f"via @{via_alias}" if via_alias else "via"
        return _AliasHistoryProvenance(
            kind="indirect",
            label=label,
            origin=recorded_origin,
            via_alias=via_alias,
        )
    if recorded_origin == ALIAS_ORIGIN_DIRECTIVE:
        return _AliasHistoryProvenance(
            kind="direct",
            label="direct",
            origin=recorded_origin,
        )
    if recorded_origin == ALIAS_ORIGIN_DEFAULT_MODEL:
        return _AliasHistoryProvenance(
            kind="default",
            label="default",
            origin=recorded_origin,
        )
    return _AliasHistoryProvenance(
        kind="unrecorded",
        label="unrecorded",
        origin=recorded_origin,
    )


def _classify_alias_history_status(
    status: str,
    *,
    workflow_status: str | None = None,
    has_done_marker: bool = False,
) -> AliasHistoryRollupStatus:
    """Map an indexed run onto the title-line done/failed/running rollup."""
    tokens = {_normalize_status(status), _normalize_status(workflow_status)}
    tokens.discard("")
    if tokens & _FAILED_STATUSES or any(token.startswith("failed") for token in tokens):
        return "failed"
    if tokens & _RUNNING_STATUSES and not has_done_marker:
        return "running"
    return "done"


def _alias_history_duration_seconds(
    started_at: str | None,
    finished_at: float | None,
) -> float | None:
    """Return elapsed seconds between start and finish, or ``None``.

    Formatting stays with the frontend. Unparseable or inverted bounds yield
    ``None`` rather than raising.
    """
    started = parse_local(started_at)
    finished = parse_local(finished_at)
    if started is None or finished is None:
        return None
    seconds = (finished - started).total_seconds()
    if seconds < 0:
        return None
    return seconds


def load_alias_history(
    aliases: str | Sequence[str],
    *,
    limit_per_alias: int | None = None,
    include_hidden: bool = False,
    projects: Sequence[str] | None = None,
    freshness: AliasHistoryFreshness = "cached",
    prompt_snippet_bytes: int = DEFAULT_ALIAS_HISTORY_PROMPT_SNIPPET_BYTES,
    index_path: Path | str | None = None,
    snapshot: ProjectDisplaySnapshot | None = None,
) -> AliasHistoryView:
    """Load typed alias-history view models for *aliases*.

    ``limit_per_alias`` defaults to :func:`get_model_alias_history_limit`.
    Project cells resolve through :func:`project_display_name_for`, falling
    back to the ProjectSpec key when no configured name is known.
    """
    requested = _requested_aliases(aliases)
    if not requested:
        raise ValueError("aliases must be a non-empty list")

    resolved_limit = (
        get_model_alias_history_limit()
        if limit_per_alias is None
        else int(limit_per_alias)
    )
    resolved_projects = tuple(str(project) for project in (projects or ()))
    resolved_index = (
        default_agent_artifact_index_path() if index_path is None else Path(index_path)
    )
    wire = query_agent_alias_history(
        resolved_index,
        AgentAliasHistoryQueryWire(
            aliases=list(requested),
            limit_per_alias=resolved_limit,
            include_hidden=include_hidden,
            projects=list(resolved_projects),
            prompt_snippet_bytes=int(prompt_snippet_bytes),
            freshness=freshness,
        ),
    )
    return _view_from_wire(
        wire,
        aliases=requested,
        limit_per_alias=resolved_limit,
        include_hidden=include_hidden,
        projects=resolved_projects,
        freshness=freshness,
        snapshot=snapshot,
    )


def _view_from_wire(
    wire: AgentAliasHistoryWire,
    *,
    aliases: tuple[str, ...],
    limit_per_alias: int,
    include_hidden: bool,
    projects: tuple[str, ...],
    freshness: AliasHistoryFreshness,
    snapshot: ProjectDisplaySnapshot | None,
) -> AliasHistoryView:
    groups = tuple(_group_from_wire(group, snapshot=snapshot) for group in wire.groups)
    return AliasHistoryView(
        index_path=wire.index_path,
        aliases=aliases,
        limit_per_alias=limit_per_alias,
        include_hidden=include_hidden,
        projects=projects,
        freshness=freshness,
        groups=groups,
        status_rollup=_combine_rollups(group.status_rollup for group in groups),
    )


def _group_from_wire(
    group: AgentAliasHistoryGroupWire,
    *,
    snapshot: ProjectDisplaySnapshot | None,
) -> AliasHistoryGroup:
    runs = tuple(_run_from_wire(run, snapshot=snapshot) for run in group.runs)
    return AliasHistoryGroup(
        alias=group.alias,
        limit=group.runs_limit.limit,
        total_count=group.runs_limit.total_count,
        returned_count=group.runs_limit.returned_count,
        truncated=group.runs_limit.truncated,
        status_rollup=_rollup_for_runs(runs),
        runs=runs,
    )


def _run_from_wire(
    run: AgentAliasRunWire,
    *,
    snapshot: ProjectDisplaySnapshot | None,
) -> AliasHistoryRun:
    trail = tuple(run.model_alias_trail)
    return AliasHistoryRun(
        artifact_dir=run.artifact_dir,
        project_key=run.project_name,
        project_name=project_display_name_for(run.project_name, snapshot=snapshot),
        workflow_dir_name=run.workflow_dir_name,
        timestamp=run.timestamp,
        alias_position=run.alias_position,
        status=run.status,
        has_done_marker=run.has_done_marker,
        hidden=run.hidden,
        provenance=_classify_alias_history_provenance(
            run.alias_position,
            run.model_alias_origin,
            trail,
        ),
        rollup_status=_classify_alias_history_status(
            run.status,
            workflow_status=run.workflow_status,
            has_done_marker=run.has_done_marker,
        ),
        agent_name=run.agent_name,
        workflow_name=run.workflow_name,
        model=run.model,
        llm_provider=run.llm_provider,
        reasoning_effort=run.reasoning_effort,
        model_alias=run.model_alias,
        model_alias_origin=run.model_alias_origin,
        model_alias_trail=trail,
        workflow_status=run.workflow_status,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_seconds=_alias_history_duration_seconds(
            run.started_at,
            run.finished_at,
        ),
        retry_attempt=run.retry_attempt,
        bead_id=run.bead_id,
        cl_name=run.cl_name,
        workspace_num=run.workspace_num,
        prompt_snippet=run.prompt_snippet,
        used_xprompts=tuple(run.used_xprompts),
    )


def _requested_aliases(aliases: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(aliases, str):
        return (aliases,)
    return tuple(str(alias) for alias in aliases)


def _normalize_origin(origin: str | None) -> str | None:
    if not isinstance(origin, str):
        return None
    stripped = origin.strip()
    return stripped or None


def _normalize_status(status: str | None) -> str:
    if not isinstance(status, str):
        return ""
    return status.strip().lower()


def _previous_alias(alias_position: int, trail: Sequence[str]) -> str | None:
    index = alias_position - 1
    if 0 <= index < len(trail):
        previous = trail[index].strip()
        return previous or None
    return None


def _rollup_for_runs(runs: Sequence[AliasHistoryRun]) -> _AliasHistoryStatusRollup:
    done = failed = running = 0
    for run in runs:
        if run.rollup_status == "failed":
            failed += 1
        elif run.rollup_status == "running":
            running += 1
        else:
            done += 1
    return _AliasHistoryStatusRollup(done=done, failed=failed, running=running)


def _combine_rollups(
    rollups: Iterable[_AliasHistoryStatusRollup],
) -> _AliasHistoryStatusRollup:
    done = failed = running = 0
    for rollup in rollups:
        done += rollup.done
        failed += rollup.failed
        running += rollup.running
    return _AliasHistoryStatusRollup(done=done, failed=failed, running=running)


__all__ = [
    "AliasHistoryFreshness",
    "AliasHistoryGroup",
    "AliasHistoryProvenanceKind",
    "AliasHistoryRollupStatus",
    "AliasHistoryRun",
    "AliasHistoryView",
    "load_alias_history",
]
