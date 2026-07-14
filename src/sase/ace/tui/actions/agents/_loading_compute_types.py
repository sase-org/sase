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
    agent_panels_grouped: bool = False


@dataclass(frozen=True)
class PreparedFinalizePlan:
    """Pure-data finalize plan computable off the UI thread."""

    query: PreparedQueryFilter
    overrides: PreparedStatusOverridePlan
    selection: PreparedSelectionPlan
    panel_group_keys: dict[AgentPanelFoldScope, list[GroupKey]]
    stale_token: PreparedFinalizeStaleToken


@dataclass(frozen=True)
class PreparedApplyBoundary:
    """Prepared post-load data the UI thread can apply without recomputing."""

    prep: PreparedApplyData
    fold: PreparedFoldFiltering
    selection: PreparedApplySelectionInputs
    finalize: PreparedFinalizePlan | None = None
