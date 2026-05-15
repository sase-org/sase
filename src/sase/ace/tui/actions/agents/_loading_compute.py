"""Pure-data compute helpers for :class:`AgentLoadingMixin`.

These helpers are safe to call from a worker thread — they do not touch
widgets, do not read app state, and (apart from the self-healing
artifact cleanup) do not write to disk. The mixin in :mod:`._loading`
folds their output back into ``self`` on the UI thread.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_content_search import AgentContentSearchIndex
    from ...models.agent_group_fold import GroupKey
    from ...models.agent_groups import GroupingMode
    from ...models.agent_loader import AgentLoadState
    from ...models.fold_state import FoldLevel

from ._loading_helpers import (
    DISMISSABLE_STATUSES,
    is_always_visible,
    is_axe_spawned_agent,
)

log = logging.getLogger(__name__)

# Per-process cache of artifact dirs already reconciled by the loader's
# self-healing pass.  First call inspects the dir (and may call
# ``delete_agent_artifacts``); subsequent full reloads skip it, saving the
# stat/glob syscalls when many dismissed agents accumulate.
_CLEANED_ARTIFACT_DIRS: set[str] = set()


def compute_loader_cleanup(
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    dismissed_from_loader: list[Agent],
) -> tuple[
    set[tuple[AgentType, str, str | None]],
    set[str],
]:
    """Compute orphaned-dismissed entries and clean loader-sourced artifacts."""
    from ._killing import delete_agent_artifacts

    del dismissed_snapshot
    orphaned: set[tuple[AgentType, str, str | None]] = set()

    # Self-healing: clean stale artifacts only for loader-sourced dismissed agents.
    cleaned_dirs: set[str] = set()
    for a in dismissed_from_loader:
        if a._loaded_from_dismissed_bundle:
            continue
        artifacts_dir = a.artifacts_dir or a.get_artifacts_dir()
        if artifacts_dir is None or artifacts_dir in _CLEANED_ARTIFACT_DIRS:
            continue
        if not Path(artifacts_dir).is_dir():
            cleaned_dirs.add(artifacts_dir)
            continue
        delete_agent_artifacts(artifacts_dir)
        cleaned_dirs.add(artifacts_dir)

    return orphaned, cleaned_dirs


@dataclass
class PreparedApplyData:
    """Output of :func:`compute_apply_loaded_agents` (worker thread).

    All fields are plain Python values — no widget access, no ``self``
    state mutation — so the compute is safe to run via
    ``asyncio.to_thread`` while the Textual event loop continues
    dispatching ``j``/``k`` keystrokes.
    """

    filtered_agents: list[Agent]
    has_always_visible: bool
    hidden_count: int
    hideable_agents: list[Agent]
    dismissed_agent_objects: list[Agent]
    recovered_bundle_identities: set[tuple[AgentType, str, str | None]] = field(
        default_factory=set
    )
    auto_dismissed_identities: set[tuple[AgentType, str, str | None]] = field(
        default_factory=set
    )


@dataclass(frozen=True)
class PreparedApplySelectionInputs:
    """Selection state captured before the prepared apply boundary runs."""

    on_agents_tab: bool
    selected_identity: tuple[AgentType, str, str | None] | None
    prior_visual_row: int | None


@dataclass(frozen=True)
class PreparedApplySnapshot:
    """Pure snapshot of app-owned state needed to prepare loaded agents."""

    cached_agents_with_children: list[Agent]
    dismissed_agents: set[tuple[AgentType, str, str | None]]
    agents_seen_complete_history: bool
    hide_non_run_agents: bool
    load_state: AgentLoadState | None
    fold_levels: dict[str, FoldLevel] | None
    selection: PreparedApplySelectionInputs
    agent_search_query: str = ""
    agent_query_cache: tuple[str, QueryExpr | None] | None = None
    agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = field(
        default_factory=dict
    )
    grouping_mode: GroupingMode | None = None


@dataclass(frozen=True)
class _PreparedFoldFiltering:
    """Fold-filter output plus the unfiltered payload the UI must preserve."""

    unfiltered_agents: list[Agent]
    visible_agents: list[Agent]
    fold_counts: dict[str, tuple[int, int]]


@dataclass(frozen=True)
class _PreparedQueryFilter:
    """Result of running the structured query filter off-thread."""

    raw_query: str
    parsed_ast: QueryExpr | None
    parse_error: str | None
    filtered_agents: list[Agent]


@dataclass(frozen=True)
class _PreparedStatusOverridePlan:
    """Pure plan describing how the UI should reconcile status overrides."""

    overrides_to_apply: list[tuple[tuple[AgentType, str, str | None], str]]
    cleared_identities: list[tuple[AgentType, str, str | None]]


@dataclass(frozen=True)
class _PreparedSelectionPlan:
    """Pure selection-restoration math for the post-finalize cursor."""

    restored_idx: int
    identity_restored: bool


@dataclass(frozen=True)
class _PreparedFinalizeStaleToken:
    """Captured mutable UI inputs the worker used to compute the plan.

    The UI re-captures these at apply time. If anything diverged from
    what the worker saw, the precomputed plan is discarded and the
    finalize pipeline recomputes synchronously instead.
    """

    on_agents_tab: bool
    selected_identity: tuple[AgentType, str, str | None] | None
    prior_visual_row: int | None
    fold_levels: tuple[tuple[str, FoldLevel], ...] | None
    agent_search_query: str
    agent_query_cache_identity: int | None
    agent_status_override_keys: frozenset[tuple[AgentType, str, str | None]]
    grouping_mode: GroupingMode | None
    hide_non_run_agents: bool


@dataclass(frozen=True)
class PreparedFinalizePlan:
    """Pure-data finalize plan computable off the UI thread."""

    query: _PreparedQueryFilter
    overrides: _PreparedStatusOverridePlan
    selection: _PreparedSelectionPlan
    group_keys: list[GroupKey]
    stale_token: _PreparedFinalizeStaleToken


@dataclass(frozen=True)
class PreparedApplyBoundary:
    """Prepared post-load data the UI thread can apply without recomputing."""

    prep: PreparedApplyData
    fold: _PreparedFoldFiltering
    selection: PreparedApplySelectionInputs
    finalize: PreparedFinalizePlan | None = None


class _FoldStateSnapshot:
    """Read-only fold-state adapter for pure fold filtering."""

    def __init__(self, levels: dict[str, FoldLevel]) -> None:
        self._levels = levels

    def get(self, key: str) -> FoldLevel:
        from ...models.fold_state import FoldLevel

        return self._levels.get(key, FoldLevel.COLLAPSED)


def _filter_agents_by_fold_snapshot(
    agents: list[Agent],
    fold_levels: dict[str, FoldLevel],
) -> tuple[list[Agent], dict[str, tuple[int, int]]]:
    """Fold-filter agents from an explicit fold-state snapshot."""
    from ...models._fold_filter import filter_agents_by_fold_state

    return filter_agents_by_fold_state(
        agents, cast(Any, _FoldStateSnapshot(fold_levels))
    )


def _reattach_children_after_parent_dedup(
    agents_before_dedup: list[Agent],
    agents_after_dedup: list[Agent],
) -> list[Agent]:
    """Move children from removed same-PID parents to surviving parents."""
    after_ids = {id(agent) for agent in agents_after_dedup}
    surviving_parent_by_pid: dict[int, Agent] = {}
    for agent in agents_after_dedup:
        if agent.pid is None or agent.raw_suffix is None or agent.is_workflow_child:
            continue
        surviving_parent_by_pid.setdefault(agent.pid, agent)

    replacement_suffix_by_removed_suffix: dict[str, str] = {}
    for agent in agents_before_dedup:
        if (
            id(agent) in after_ids
            or agent.pid is None
            or agent.raw_suffix is None
            or agent.is_workflow_child
        ):
            continue
        survivor = surviving_parent_by_pid.get(agent.pid)
        if (
            survivor is None
            or survivor.raw_suffix is None
            or survivor.raw_suffix == agent.raw_suffix
        ):
            continue
        replacement_suffix_by_removed_suffix[agent.raw_suffix] = survivor.raw_suffix

    if not replacement_suffix_by_removed_suffix:
        return agents_after_dedup

    reattached_ids: set[int] = set()
    for agent in agents_after_dedup:
        if not agent.is_workflow_child or agent.parent_timestamp is None:
            continue
        replacement_suffix = replacement_suffix_by_removed_suffix.get(
            agent.parent_timestamp
        )
        if replacement_suffix is None:
            continue
        agent.parent_timestamp = replacement_suffix
        reattached_ids.add(id(agent))

    if not reattached_ids:
        return agents_after_dedup

    children_by_parent: dict[str, list[Agent]] = {}
    roots_and_unchanged_children: list[Agent] = []
    for agent in agents_after_dedup:
        if id(agent) in reattached_ids and agent.parent_timestamp is not None:
            children_by_parent.setdefault(agent.parent_timestamp, []).append(agent)
        else:
            roots_and_unchanged_children.append(agent)

    regrouped: list[Agent] = []
    for agent in roots_and_unchanged_children:
        regrouped.append(agent)
        if agent.raw_suffix is None:
            continue
        regrouped.extend(children_by_parent.pop(agent.raw_suffix, []))

    for remaining_children in children_by_parent.values():
        regrouped.extend(remaining_children)
    return regrouped


def merge_incomplete_load_after_complete_history(
    prep: PreparedApplyData,
    snapshot: PreparedApplySnapshot,
) -> PreparedApplyData:
    """Treat post-reconcile Tier 1 loads as patches over full history."""
    load_state = snapshot.load_state
    if (
        load_state is None
        or load_state.complete_history
        or not snapshot.agents_seen_complete_history
    ):
        return prep

    cached_agents = list(snapshot.cached_agents_with_children)
    if not cached_agents:
        return prep

    from ...models._dedup import dedup_by_pid, dedup_running_vs_workflow
    from ...models.agent import AgentType

    incoming_by_identity = {agent.identity: agent for agent in prep.filtered_agents}
    dismissed = set(snapshot.dismissed_agents)
    dismissed_suffixes = {
        raw_suffix for _, _, raw_suffix in dismissed if raw_suffix is not None
    }
    dismissed_cl_suffixes = {
        (cl_name, raw_suffix)
        for _, cl_name, raw_suffix in dismissed
        if raw_suffix is not None
    }

    def is_dismissed(agent: Agent) -> bool:
        if agent.identity in dismissed:
            return True
        if agent.raw_suffix is None:
            return False
        if agent.status == "RUNNING":
            return (agent.cl_name, agent.raw_suffix) in dismissed_cl_suffixes or (
                agent.cl_name == "unknown" and agent.raw_suffix in dismissed_suffixes
            )
        return agent.raw_suffix in dismissed_suffixes

    merged: list[Agent] = []
    seen: set[tuple[AgentType, str, str | None]] = set()
    cached_identities = {agent.identity for agent in cached_agents}
    cached_parent_by_suffix = {
        agent.raw_suffix: agent
        for agent in cached_agents
        if agent.raw_suffix is not None and not agent.is_workflow_child
    }
    cached_parent_suffixes = set(cached_parent_by_suffix)
    incoming_parent_suffixes = {
        agent.raw_suffix
        for agent in prep.filtered_agents
        if agent.raw_suffix is not None and not agent.is_workflow_child
    }
    known_parent_suffixes = cached_parent_suffixes | incoming_parent_suffixes
    new_roots: list[Agent] = []
    new_children_by_parent: dict[str, list[Agent]] = {}

    def can_canonical_dedup_running_shadow(agent: Agent) -> bool:
        """Whether loader-level RUNNING-WORKFLOW dedup can handle this row."""
        cached_parent = (
            cached_parent_by_suffix.get(agent.raw_suffix)
            if agent.raw_suffix is not None
            else None
        )
        return (
            agent.agent_type == AgentType.RUNNING
            and cached_parent is not None
            and cached_parent.agent_type == AgentType.WORKFLOW
            and agent.workflow is not None
            and (
                agent.workflow.startswith("ace(run)")
                or agent.workflow == "ace-run"
                or agent.workflow == "run"
            )
        )

    # Newly discovered Tier 1 rows are usually the newest rows. Keep their
    # relative Tier 1 order while preserving cached parent/child groups.
    for agent in prep.filtered_agents:
        if agent.identity in cached_identities or is_dismissed(agent):
            continue
        if agent.parent_timestamp and agent.parent_timestamp in known_parent_suffixes:
            new_children_by_parent.setdefault(agent.parent_timestamp, []).append(agent)
            continue
        if (
            agent.raw_suffix is not None
            and not agent.is_workflow_child
            and agent.raw_suffix in cached_parent_suffixes
            and not can_canonical_dedup_running_shadow(agent)
        ):
            continue
        new_roots.append(agent)

    for agent in new_roots:
        if agent.identity in seen:
            continue
        merged.append(agent)
        seen.add(agent.identity)
        if agent.raw_suffix:
            for child in new_children_by_parent.pop(agent.raw_suffix, []):
                if child.identity in seen:
                    continue
                merged.append(child)
                seen.add(child.identity)

    for cached in cached_agents:
        replacement = incoming_by_identity.get(cached.identity, cached)
        if replacement.identity in seen or is_dismissed(replacement):
            continue
        merged.append(replacement)
        seen.add(replacement.identity)
        if replacement.raw_suffix:
            for child in new_children_by_parent.pop(replacement.raw_suffix, []):
                if child.identity in seen:
                    continue
                merged.append(child)
                seen.add(child.identity)

    before_dedup = list(merged)
    merged = dedup_running_vs_workflow(merged)
    merged = dedup_by_pid(merged)
    merged = _reattach_children_after_parent_dedup(before_dedup, merged)

    always_visible = [agent for agent in merged if is_always_visible(agent)]
    hideable = [agent for agent in merged if not is_always_visible(agent)]
    if always_visible and snapshot.hide_non_run_agents and hideable:
        filtered_agents = always_visible
        hidden_count = len(hideable)
    else:
        filtered_agents = merged
        hidden_count = 0

    prep.filtered_agents = filtered_agents
    prep.hidden_count = hidden_count
    prep.has_always_visible = bool(always_visible)
    prep.hideable_agents = hideable
    return prep


def prepare_loaded_agents_apply_boundary(
    prep: PreparedApplyData,
    snapshot: PreparedApplySnapshot,
    *,
    merge_incomplete: bool = True,
) -> PreparedApplyBoundary:
    """Prepare pure post-load apply data from an explicit app-state snapshot."""
    from ...util.trace import tui_trace

    if merge_incomplete:
        with tui_trace(
            "agents.incomplete_load_merge",
            incoming=len(prep.filtered_agents),
            cached=len(snapshot.cached_agents_with_children),
            complete=getattr(snapshot.load_state, "complete_history", None),
        ):
            prep = merge_incomplete_load_after_complete_history(prep, snapshot)

    unfiltered_agents = list(prep.filtered_agents)
    if snapshot.fold_levels is None:
        visible_agents = list(unfiltered_agents)
        fold_counts: dict[str, tuple[int, int]] = {}
    else:
        with tui_trace("agents.fold_filtering", count=len(unfiltered_agents)):
            visible_agents, fold_counts = _filter_agents_by_fold_snapshot(
                unfiltered_agents, snapshot.fold_levels
            )

    return PreparedApplyBoundary(
        prep=prep,
        fold=_PreparedFoldFiltering(
            unfiltered_agents=unfiltered_agents,
            visible_agents=visible_agents,
            fold_counts=fold_counts,
        ),
        selection=snapshot.selection,
    )


def compute_apply_loaded_agents(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
) -> PreparedApplyData:
    """Pure-data filter pipeline for ``_apply_loaded_agents``.

    Computes the recovered-bundle / auto-dismiss deltas, applies the
    dismissed-set filter, marks axe-spawned agents hidden, and partitions
    the result into always-visible vs hideable. Returns a
    :class:`_PreparedApplyData` snapshot for the UI thread to fold into
    ``self``. Safe to call from a worker thread — does not access widgets,
    does not write to disk, does not mutate ``self`` state.
    """
    recovered = {
        a.identity
        for a in dismissed_from_loader
        if a._loaded_from_dismissed_bundle and a.identity not in dismissed_snapshot
    }

    # The filter must treat freshly-recovered identities as dismissed so a
    # re-recovered agent doesn't briefly leak into the visible list before
    # the UI thread persists the recovery delta.
    effective_dismissed = dismissed_snapshot | recovered
    dismissed_suffixes: set[str] = {
        raw_suffix for _, _, raw_suffix in effective_dismissed if raw_suffix is not None
    }
    dismissed_cl_suffixes: set[tuple[str, str]] = {
        (cl_name, raw_suffix)
        for _, cl_name, raw_suffix in effective_dismissed
        if raw_suffix is not None
    }

    # Filter out dismissed agents.  Non-RUNNING agents use the broad
    # dismissed_suffixes index (suffix-only).  RUNNING agents use the
    # narrower dismissed_cl_suffixes index (cl_name, raw_suffix) to
    # avoid cross-CL contamination while still catching agents that
    # reappear with a different AgentType after dedup (e.g. a killed
    # WORKFLOW agent whose artifacts are deleted but whose RUNNING
    # field entry persists, producing an AgentType.RUNNING agent).
    # RUNNING agents with cl_name="unknown" fall back to suffix-only
    # matching since "unknown" is a transient placeholder from the
    # RUNNING field that gets resolved during dedup.
    filtered = [
        a
        for a in all_agents
        if a.identity not in effective_dismissed
        and (
            a.status == "RUNNING"
            or (a.raw_suffix is None or a.raw_suffix not in dismissed_suffixes)
        )
        and not (
            a.status == "RUNNING"
            and a.raw_suffix is not None
            and (
                (a.cl_name, a.raw_suffix) in dismissed_cl_suffixes
                or (a.cl_name == "unknown" and a.raw_suffix in dismissed_suffixes)
            )
        )
    ]

    # Auto-dismiss hidden agents that have completed successfully.
    # Failed agents are kept visible so the user can investigate.
    auto_dismissed_ids = {
        a.identity
        for a in filtered
        if a.hidden and a.status in DISMISSABLE_STATUSES and a.status != "FAILED"
    }
    if auto_dismissed_ids:
        filtered = [a for a in filtered if a.identity not in auto_dismissed_ids]

    # Mark axe-spawned agents as hidden so the icon renders correctly.
    for agent in filtered:
        if not agent.hidden and is_axe_spawned_agent(agent):
            agent.hidden = True

    # Categorize agents: always-visible (dismissable OR running) vs hideable
    always_visible: list[Agent] = []
    hideable: list[Agent] = []
    for a in filtered:
        if is_always_visible(a):
            always_visible.append(a)
        else:
            hideable.append(a)

    has_always_visible = len(always_visible) > 0
    if has_always_visible and hide_non_run_agents and hideable:
        result_agents = always_visible
        hidden_count = len(hideable)
    else:
        result_agents = filtered
        hidden_count = 0

    return PreparedApplyData(
        filtered_agents=result_agents,
        has_always_visible=has_always_visible,
        hidden_count=hidden_count,
        hideable_agents=hideable,
        dismissed_agent_objects=dismissed_from_loader,
        recovered_bundle_identities=recovered,
        auto_dismissed_identities=auto_dismissed_ids,
    )


def _prepare_loaded_agents_worker_prep(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
    snapshot: PreparedApplySnapshot,
) -> PreparedApplyData:
    """Prepare async-loaded agents, including post-history Tier 1 patch merge."""
    from ...util.trace import tui_trace

    prep = compute_apply_loaded_agents(
        all_agents,
        dismissed_from_loader,
        dismissed_snapshot,
        hide_non_run_agents,
    )
    snapshot_for_merge = PreparedApplySnapshot(
        cached_agents_with_children=snapshot.cached_agents_with_children,
        dismissed_agents=(
            set(snapshot.dismissed_agents)
            | prep.recovered_bundle_identities
            | prep.auto_dismissed_identities
        ),
        agents_seen_complete_history=snapshot.agents_seen_complete_history,
        hide_non_run_agents=snapshot.hide_non_run_agents,
        load_state=snapshot.load_state,
        fold_levels=snapshot.fold_levels,
        selection=snapshot.selection,
    )
    with tui_trace(
        "agents.incomplete_load_merge",
        incoming=len(prep.filtered_agents),
        cached=len(snapshot.cached_agents_with_children),
        complete=getattr(snapshot.load_state, "complete_history", None),
    ):
        return merge_incomplete_load_after_complete_history(prep, snapshot_for_merge)


def prepare_loaded_agents_worker_boundary(
    all_agents: list[Agent],
    dismissed_from_loader: list[Agent],
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    hide_non_run_agents: bool,
    snapshot: PreparedApplySnapshot,
) -> PreparedApplyBoundary:
    """Prepare async-loaded agents through the fold-filter boundary."""
    prep = _prepare_loaded_agents_worker_prep(
        all_agents,
        dismissed_from_loader,
        dismissed_snapshot,
        hide_non_run_agents,
        snapshot,
    )
    return prepare_loaded_agents_apply_boundary(
        prep,
        snapshot,
        merge_incomplete=False,
    )


def attach_finalize_plan_to_boundary(
    boundary: PreparedApplyBoundary,
    snapshot: PreparedApplySnapshot,
    *,
    content_index: AgentContentSearchIndex | None,
) -> PreparedApplyBoundary:
    """Compute the finalize plan and return a new boundary that includes it."""
    finalize_plan = _compute_finalize_plan(
        boundary.fold.visible_agents,
        snapshot,
        content_index=content_index,
    )
    return PreparedApplyBoundary(
        prep=boundary.prep,
        fold=boundary.fold,
        selection=boundary.selection,
        finalize=finalize_plan,
    )


def _filter_agents_by_query(
    agents: list[Agent],
    parsed_ast: QueryExpr,
    content_index: AgentContentSearchIndex | None,
) -> list[Agent]:
    """Filter *agents* by *parsed_ast*, preserving children of matching parents."""
    from ....agent_query import evaluate_agent_query

    now = datetime.now()

    def _matches(agent: Agent) -> bool:
        return evaluate_agent_query(
            parsed_ast, agent, now=now, content_cache=content_index
        )

    matching_parent_names: set[str] = set()
    for agent in agents:
        if not agent.is_workflow_child and _matches(agent):
            matching_parent_names.add(agent.agent_name or agent.cl_name)

    return [
        a
        for a in agents
        if (
            _matches(a)
            or (
                a.is_workflow_child
                and (a.agent_name or a.cl_name) in matching_parent_names
            )
        )
    ]


def _compute_query_plan(
    agents: list[Agent],
    snapshot: PreparedApplySnapshot,
    content_index: AgentContentSearchIndex | None,
) -> _PreparedQueryFilter:
    """Parse + evaluate the structured query off the UI thread.

    Cached AST entries from prior renders are honored when the raw query
    is unchanged so the worker mirrors the UI-thread caching behavior.
    Parse errors are surfaced as ``parse_error`` so the UI thread can
    notify and persist the message — they don't filter the list.
    """
    from ....agent_query import AgentQueryParseError, parse_agent_query

    raw = snapshot.agent_search_query or ""
    if not raw:
        return _PreparedQueryFilter(
            raw_query=raw,
            parsed_ast=None,
            parse_error=None,
            filtered_agents=list(agents),
        )

    cached = snapshot.agent_query_cache
    parsed: QueryExpr | None = None
    parse_error: str | None = None
    if cached is not None and cached[0] == raw:
        parsed = cached[1]
    else:
        try:
            parsed = parse_agent_query(raw)
        except AgentQueryParseError as e:
            parse_error = str(e)
            parsed = None

    if parsed is None:
        return _PreparedQueryFilter(
            raw_query=raw,
            parsed_ast=None,
            parse_error=parse_error,
            filtered_agents=list(agents),
        )

    filtered = _filter_agents_by_query(agents, parsed, content_index)
    return _PreparedQueryFilter(
        raw_query=raw,
        parsed_ast=parsed,
        parse_error=None,
        filtered_agents=filtered,
    )


def _compute_status_override_plan(
    agents: list[Agent],
    overrides: dict[tuple[AgentType, str, str | None], str],
) -> _PreparedStatusOverridePlan:
    """Determine which agent rows need an override applied or cleared."""
    loaded_identities = {a.identity for a in agents}
    to_apply: list[tuple[tuple[AgentType, str, str | None], str]] = []
    cleared: list[tuple[AgentType, str, str | None]] = []
    for agent in agents:
        if agent.status in DISMISSABLE_STATUSES:
            if agent.identity in overrides:
                cleared.append(agent.identity)
            continue
        if agent.identity in overrides:
            to_apply.append((agent.identity, overrides[agent.identity]))

    for identity in overrides:
        if identity not in loaded_identities and identity not in cleared:
            cleared.append(identity)
    return _PreparedStatusOverridePlan(
        overrides_to_apply=to_apply,
        cleared_identities=cleared,
    )


def _compute_selection_plan(
    agents: list[Agent],
    selection: PreparedApplySelectionInputs,
) -> _PreparedSelectionPlan:
    """Compute the restored cursor index using identity then visual row."""
    from ...util.selection import restore_selection_by_identity

    restored_idx = restore_selection_by_identity(
        agents,
        prior_identity=selection.selected_identity,
        prior_visual_row=selection.prior_visual_row,
        identity_fn=lambda agent: agent.identity,
    )
    identity_restored = (
        selection.selected_identity is not None
        and 0 <= restored_idx < len(agents)
        and agents[restored_idx].identity == selection.selected_identity
    )
    return _PreparedSelectionPlan(
        restored_idx=restored_idx,
        identity_restored=identity_restored,
    )


def make_finalize_stale_token(
    snapshot: PreparedApplySnapshot,
) -> _PreparedFinalizeStaleToken:
    """Capture the mutable inputs the finalize worker relied on."""
    fold_tuple: tuple[tuple[str, FoldLevel], ...] | None
    if snapshot.fold_levels is None:
        fold_tuple = None
    else:
        fold_tuple = tuple(sorted(snapshot.fold_levels.items()))
    cache_identity = (
        id(snapshot.agent_query_cache)
        if snapshot.agent_query_cache is not None
        else None
    )
    override_keys: frozenset[tuple[AgentType, str, str | None]] = frozenset(
        snapshot.agent_status_overrides.keys()
    )
    return _PreparedFinalizeStaleToken(
        on_agents_tab=snapshot.selection.on_agents_tab,
        selected_identity=snapshot.selection.selected_identity,
        prior_visual_row=snapshot.selection.prior_visual_row,
        fold_levels=fold_tuple,
        agent_search_query=snapshot.agent_search_query or "",
        agent_query_cache_identity=cache_identity,
        agent_status_override_keys=override_keys,
        grouping_mode=snapshot.grouping_mode,
        hide_non_run_agents=snapshot.hide_non_run_agents,
    )


def _compute_finalize_plan(
    visible_agents: list[Agent],
    snapshot: PreparedApplySnapshot,
    *,
    content_index: AgentContentSearchIndex | None = None,
) -> PreparedFinalizePlan:
    """Run the pure parts of ``finalize_agent_list`` off the UI thread.

    Returns query-filtered agents, the status-override apply plan, the
    selection-restoration math, and the group keys the UI registry GC
    needs — plus a :class:`_PreparedFinalizeStaleToken` capturing every
    mutable input. The UI thread re-captures the same inputs at apply
    time and discards the plan if any drift is detected.
    """
    from ...models.agent_groups import GroupingMode, enumerate_group_keys
    from ...util.trace import tui_trace

    with tui_trace("agents.finalize_query_filter", agents=len(visible_agents)):
        query_plan = _compute_query_plan(visible_agents, snapshot, content_index)
    override_plan = _compute_status_override_plan(
        query_plan.filtered_agents,
        snapshot.agent_status_overrides,
    )
    selection_plan = _compute_selection_plan(
        query_plan.filtered_agents,
        snapshot.selection,
    )
    grouping_mode = (
        snapshot.grouping_mode
        if snapshot.grouping_mode is not None
        else GroupingMode.STANDARD
    )
    group_keys = enumerate_group_keys(query_plan.filtered_agents, mode=grouping_mode)
    stale_token = make_finalize_stale_token(snapshot)
    return PreparedFinalizePlan(
        query=query_plan,
        overrides=override_plan,
        selection=selection_plan,
        group_keys=group_keys,
        stale_token=stale_token,
    )
