"""Pure-data dataclass types shared across the loading compute pipeline.

These types are imported by the worker-thread compute helpers in
:mod:`._loading_compute`, :mod:`._loading_compute_merge`, and
:mod:`._loading_compute_finalize`. They are re-exported from
``_loading_compute`` so callers can keep using the original module path.

Dataclasses that wrap pieces produced by a single sibling module live
in that sibling module (``PreparedFoldFiltering`` in
:mod:`._loading_compute`; ``PreparedQueryFilter``,
``PreparedStatusOverridePlan``, ``PreparedSelectionPlan``, and
``PreparedFinalizeStaleToken`` in :mod:`._loading_compute_finalize`).
The annotations referencing those types here resolve as forward-string
references thanks to ``from __future__ import annotations``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..._proc_observer_models import ProcProjection
from ...models.agent_runner_slots import RunnerCapacitySnapshot

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_group_fold import AgentPanelFoldScope, GroupKey
    from ...models.agent_groups import GroupingMode
    from ...models.agent_loader import AgentLoadState
    from ...models.fold_state import FoldLevel

    from ._loading_compute import PreparedFoldFiltering
    from ._loading_compute_finalize import (
        PreparedFinalizeStaleToken,
        PreparedQueryFilter,
        PreparedSelectionPlan,
        PreparedStatusOverridePlan,
    )


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
    capacity_agents: list[Agent] = field(default_factory=list)
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
    """Pure snapshot of app-owned state needed to prepare loaded agents.

    ``frozen=True`` only freezes these snapshot fields. Cached ``Agent`` rows
    remain mutable presentation objects shared with the live UI until
    :func:`own_prepared_apply_snapshot` copies them. Cheap UI capture (stale
    tokens, selection, folds) must not deep-copy the archive-sized graph.
    """

    cached_agents_with_children: list[Agent]
    dismissed_agents: set[tuple[AgentType, str, str | None]]
    agents_seen_complete_history: bool
    hide_non_run_agents: bool
    load_state: AgentLoadState | None
    fold_levels: dict[str, FoldLevel] | None
    selection: PreparedApplySelectionInputs
    capacity_agents_with_children: list[Agent] = field(default_factory=list)
    agent_search_query: str = ""
    agent_query_cache: tuple[str, QueryExpr | None] | None = None
    agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = field(
        default_factory=dict
    )
    grouping_mode: GroupingMode | None = None
    agent_panels_grouped: bool = False
    capacity_generation: int = 0
    # Snapshot of completion-notification unread ids for the ``unread:``
    # agents-live query field (sase-zf.2). Captured at request time; the
    # notification-store reconcile that follows finalize may drift by one
    # cycle, the same bounded staleness the query engine accepts elsewhere.
    unread_agent_ids: frozenset[tuple[AgentType, str, str | None]] = frozenset()
    proc_projection: ProcProjection | None = None
    proc_generation: int = 0
    dismissed_proc_shells: frozenset[str] = frozenset()
    # False only when the cached roster was applied under a different committed
    # query than this load covers; bounded loads may not patch across that.
    cache_query_matches: bool = True
    # Fleet rows (with unreconciled dispatch provisionals) the UI thread would
    # project into the roster after this load. Captured on the UI thread
    # because reconciling provisionals mutates app state; the boundary projects
    # them so the finalize plan is computed over the roster that gets published.
    fleet_rows: tuple[Agent, ...] = ()


@dataclass(frozen=True)
class PreparedFinalizePlan:
    """Pure-data finalize plan computable off the UI thread."""

    query: PreparedQueryFilter
    overrides: PreparedStatusOverridePlan
    selection: PreparedSelectionPlan
    panel_group_keys: dict[AgentPanelFoldScope, list[GroupKey]]
    stale_token: PreparedFinalizeStaleToken
    # Identities of the rows the plan was computed over, in order. The stale
    # token compares mutable UI state and cannot see a plan computed over a
    # different roster than the one the UI thread publishes (for example a
    # local-only roster before the fleet projection widened it), so the commit
    # step compares this against the roster it is about to publish.
    input_row_identities: tuple[tuple[AgentType, str, str | None], ...] = ()


@dataclass(frozen=True)
class PreparedApplyBoundary:
    """Prepared post-load data the UI thread can apply without recomputing."""

    prep: PreparedApplyData
    fold: PreparedFoldFiltering
    selection: PreparedApplySelectionInputs
    runner_capacity: RunnerCapacitySnapshot = field(
        default_factory=RunnerCapacitySnapshot
    )
    capacity_generation: int = 0
    proc_generation: int = 0
    finalize: PreparedFinalizePlan | None = None
    # The live fleet rows (by object) the boundary's rosters were projected
    # from. The UI thread publishes the boundary's rows only while these are
    # still the app's fleet rows; a fleet refresh in between replaces them.
    fleet_source_rows: tuple[Agent, ...] = ()
