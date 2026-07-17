"""Pure-data finalize plan computation for :mod:`._loading_compute`.

The functions here run the off-thread half of ``finalize_agent_list``:
query filtering, status-override reconciliation, selection-restoration
math, and group-key enumeration. The UI thread later re-captures the
inputs in :func:`make_finalize_stale_token` and discards the plan if
anything drifted before applying it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.core.time import local_now

from ._loading_compute_types import (
    PreparedApplyBoundary,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    PreparedFinalizePlan,
)
from ._loading_helpers import (
    build_question_answer_family_index,
    should_clear_loaded_agent_status_override,
)

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_content_search import AgentContentSearchIndex
    from ...models.agent_groups import GroupingMode
    from ...models.fold_state import FoldLevel


@dataclass(frozen=True)
class PreparedQueryFilter:
    """Result of running the structured query filter off-thread."""

    raw_query: str
    parsed_ast: QueryExpr | None
    parse_error: str | None
    filtered_agents: list[Agent]


@dataclass(frozen=True)
class PreparedStatusOverridePlan:
    """Pure plan describing how the UI should reconcile status overrides."""

    overrides_to_apply: list[tuple[tuple[AgentType, str, str | None], str]]
    cleared_identities: list[tuple[AgentType, str, str | None]]


@dataclass(frozen=True)
class PreparedSelectionPlan:
    """Pure selection-restoration math for the post-finalize cursor."""

    restored_idx: int
    identity_restored: bool


@dataclass(frozen=True)
class PreparedFinalizeStaleToken:
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
    agent_status_overrides: frozenset[tuple[tuple[AgentType, str, str | None], str]]
    grouping_mode: GroupingMode | None
    agent_panels_grouped: bool
    hide_non_run_agents: bool


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

    now = local_now()

    def _matches(agent: Agent) -> bool:
        return evaluate_agent_query(
            parsed_ast, agent, now=now, content_cache=content_index
        )

    from ...models._agent_tree import filter_tree_rows

    return filter_tree_rows(agents, _matches)


def _compute_query_plan(
    agents: list[Agent],
    snapshot: PreparedApplySnapshot,
    content_index: AgentContentSearchIndex | None,
) -> PreparedQueryFilter:
    """Parse + evaluate the structured query off the UI thread.

    Cached AST entries from prior renders are honored when the raw query
    is unchanged so the worker mirrors the UI-thread caching behavior.
    Parse errors are surfaced as ``parse_error`` so the UI thread can
    notify and persist the message — they don't filter the list.
    """
    from ....agent_query import AgentQueryParseError, parse_agent_query

    raw = snapshot.agent_search_query or ""
    if not raw:
        return PreparedQueryFilter(
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
        return PreparedQueryFilter(
            raw_query=raw,
            parsed_ast=None,
            parse_error=parse_error,
            filtered_agents=list(agents),
        )

    filtered = _filter_agents_by_query(agents, parsed, content_index)
    return PreparedQueryFilter(
        raw_query=raw,
        parsed_ast=parsed,
        parse_error=None,
        filtered_agents=filtered,
    )


def _compute_status_override_plan(
    agents: list[Agent],
    overrides: dict[tuple[AgentType, str, str | None], str],
) -> PreparedStatusOverridePlan:
    """Determine which agent rows need an override applied or cleared."""
    loaded_identities = {a.identity for a in agents}
    family_index = build_question_answer_family_index(agents)
    to_apply: list[tuple[tuple[AgentType, str, str | None], str]] = []
    cleared: list[tuple[AgentType, str, str | None]] = []
    for agent in agents:
        override = overrides.get(agent.identity)
        if override is None:
            continue
        if should_clear_loaded_agent_status_override(agent, override, family_index):
            cleared.append(agent.identity)
            continue
        to_apply.append((agent.identity, override))

    for identity in overrides:
        if identity not in loaded_identities and identity not in cleared:
            cleared.append(identity)
    return PreparedStatusOverridePlan(
        overrides_to_apply=to_apply,
        cleared_identities=cleared,
    )


def _compute_selection_plan(
    agents: list[Agent],
    selection: PreparedApplySelectionInputs,
) -> PreparedSelectionPlan:
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
    return PreparedSelectionPlan(
        restored_idx=restored_idx,
        identity_restored=identity_restored,
    )


def make_finalize_stale_token(
    snapshot: PreparedApplySnapshot,
) -> PreparedFinalizeStaleToken:
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
    override_items: frozenset[tuple[tuple[AgentType, str, str | None], str]] = (
        frozenset(snapshot.agent_status_overrides.items())
    )
    return PreparedFinalizeStaleToken(
        on_agents_tab=snapshot.selection.on_agents_tab,
        selected_identity=snapshot.selection.selected_identity,
        prior_visual_row=snapshot.selection.prior_visual_row,
        fold_levels=fold_tuple,
        agent_search_query=snapshot.agent_search_query or "",
        agent_query_cache_identity=cache_identity,
        agent_status_overrides=override_items,
        grouping_mode=snapshot.grouping_mode,
        agent_panels_grouped=snapshot.agent_panels_grouped,
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
    needs — plus a :class:`PreparedFinalizeStaleToken` capturing every
    mutable input. The UI thread re-captures the same inputs at apply
    time and discards the plan if any drift is detected.
    """
    from ...models.agent_group_fold import enumerate_panel_group_keys
    from ...models.agent_groups import GroupingMode
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
    panel_group_keys = enumerate_panel_group_keys(
        query_plan.filtered_agents,
        mode=grouping_mode,
        merged=snapshot.agent_panels_grouped,
    )
    stale_token = make_finalize_stale_token(snapshot)
    return PreparedFinalizePlan(
        query=query_plan,
        overrides=override_plan,
        selection=selection_plan,
        panel_group_keys=panel_group_keys,
        stale_token=stale_token,
    )
