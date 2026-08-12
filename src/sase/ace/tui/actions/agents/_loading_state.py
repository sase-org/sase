"""Shared type declarations for the agent loading mixins."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ....patch import Patch
from ._loading_compute import (
    PreparedApplyBoundary,
    PreparedApplyData,
    PreparedApplySnapshot,
    PreparedFinalizePlan,
)
from ._loading_helpers import TabName

if TYPE_CHECKING:
    from ....agent_query import QueryExpr
    from ...models import Agent
    from ...models.agent import AgentType
    from ...models.agent_content_search import (
        AgentContentSearchCache,
        AgentContentSearchIndex,
    )
    from ...models.agent_group_fold import AgentGroupFoldRegistry
    from ...models.agent_loader import AgentLoadState
    from ...models.agent_runner_slots import RunnerCapacitySnapshot
    from ...models.fold_state import FoldStateManager
    from ...models.fold_state import FoldLevel
    from ...util.nav_gate import NavigationGate

AgentIdentity = tuple[Any, str, str | None]
ArtifactIndexMaintenanceRequest = tuple[
    set[AgentIdentity],
    set[AgentIdentity] | None,
    bool,
    str,
]


class AgentLoadingStateMixin:
    """Attribute declarations shared by the narrow loading mixins.

    AceApp initializes these attributes at runtime. Keeping the declarations
    in one base avoids repeating the same long annotation block across the
    split loading implementation modules.
    """

    # Patch state
    patches: list[Patch]
    current_idx: int
    current_tab: TabName
    refresh_interval: int
    hide_non_run_agents: bool
    _agents: list[Agent]
    _agents_with_children: list[Agent]
    _agent_runner_capacity: RunnerCapacitySnapshot
    _agents_last_idx: int
    _agents_last_identity: tuple[AgentType, str, str | None] | None
    _has_always_visible: bool
    _hidden_count: int
    _hideable_agents: list[Agent]

    # Fold state for workflow steps
    _fold_manager: FoldStateManager
    _fold_counts: dict[str, tuple[int, int]]

    # Per-group collapse state for the Agents-tab two-level grouping tree.
    # Always points to the active mode's slot in
    # ``_group_fold_registries`` (see startup.py).
    _group_fold_registry: AgentGroupFoldRegistry

    # Agent completion tracking for notifications
    _dismissed_agents: set[tuple[AgentType, str, str | None]]
    _dismissed_agents_disk_signature: tuple[int, int] | None
    _dismissed_agents_disk_identities: set[tuple[AgentType, str, str | None]]
    _dismissed_agents_disk_signature_initialized: bool
    _dismissed_agent_objects: list[Agent]
    _revived_agent_raw_suffixes: set[str]
    _unread_completed_agent_ids: set[tuple[AgentType, str, str | None]]
    _manual_unread_agent_ids: set[tuple[AgentType, str, str | None]]
    _agent_display_status_by_identity: dict[tuple[AgentType, str, str | None], str]

    # Agent status override system (for PLAN/PLAN APPROVED/QUESTION statuses)
    _agent_status_overrides: dict[tuple[AgentType, str, str | None], str]
    _agent_pre_question_status: dict[tuple[AgentType, str, str | None], str | None]

    # Agent search/filter query
    _agent_search_query: str
    _agent_content_search_cache: AgentContentSearchCache
    _agent_content_search_index: AgentContentSearchIndex | None
    _agent_content_search_source_generation: int
    _agent_content_search_refresh_generation: int
    _agent_content_search_refresh_task: asyncio.Task[None] | None
    # Cached (raw_query, parsed_ast) so re-renders re-use the parse. ``None``
    # AST means an empty query (no filter). The cache is invalidated whenever
    # the raw query string changes.
    _agent_query_cache: tuple[str, QueryExpr | None] | None
    # Last parse error message (for the modal to surface). ``None`` means the
    # current query parsed cleanly or is empty.
    _agent_query_parse_error: str | None

    # Loading guard
    _agents_loading: bool
    # Startup loading indicator flag: flipped to True once the first async
    # load completes; remains True forever afterward.
    _agents_first_load_done: bool
    # Last-request-wins coalescing: set when a refresh is requested while
    # another one is already running. The in-flight refresh re-schedules
    # itself once it finishes so the final UI state reflects disk state
    # after the last trigger.
    _agents_refresh_pending: bool
    _agents_refresh_pending_source: str
    _agents_refresh_pending_full_history: bool
    _agents_refresh_pending_full_history_reason: str | None
    _agents_refresh_pending_revalidate_index: bool
    _agents_refresh_pending_callbacks: list[Callable[[], None]]
    _agents_refresh_scheduled: bool
    _agents_refresh_scheduled_source: str
    _agents_refresh_scheduled_full_history: bool
    _agents_refresh_scheduled_full_history_reason: str | None
    _agents_refresh_scheduled_revalidate_index: bool
    _agents_refresh_active_source: str
    _agents_refresh_async_tasks: set[asyncio.Task[None]]
    _agents_artifact_delta_scheduled: Any | None
    _agents_artifact_delta_pending: Any | None
    # Loader self-healing cleanup runs independently after row application.
    # A burst keeps only the latest pending request and runs one trailing pass.
    _loader_cleanup_running: bool
    _loader_cleanup_pending: bool
    _loader_cleanup_pending_request: (
        tuple[
            set[tuple[AgentType, str, str | None]],
            list[Agent],
            str,
            str,
        ]
        | None
    )
    _loader_cleanup_async_tasks: set[asyncio.Task[None]]
    # Sticky deferred Tier 2 reconcile state. ``_pending`` is True while
    # the last load reported incomplete history and a full-history pass
    # has not yet been scheduled; ``_armed_mono`` is the monotonic time
    # at which the flag was first set, used by the idle-tick trigger.
    _agents_history_reconcile_pending: bool
    _agents_history_reconcile_armed_mono: float
    # Cached Tier 1 index reads are backed by an off-critical-path
    # revalidating query at a longer cadence than ordinary auto-refresh.
    _agents_index_revalidate_pending: bool
    _agents_index_revalidate_armed_mono: float
    _agents_index_revalidate_last_mono: float
    # Source-aware debounce gate for ``request_agents_refresh``: True while
    # a debounce timer is armed so a burst of fan-out spawn callbacks
    # collapses into a single deferred ``_schedule_agents_async_refresh``.
    _agents_refresh_debounce_armed: bool
    _agents_refresh_debounce_source: str
    _artifact_index_maintenance_running: bool
    _artifact_index_maintenance_pending: bool
    _artifact_index_maintenance_pending_request: ArtifactIndexMaintenanceRequest | None
    _artifact_index_maintenance_last_mono: float
    _artifact_index_schema_rebuild_in_flight: bool
    _artifact_index_schema_bypass: bool
    _dismissed_index_sync_pending_after_schema_rebuild: bool
    _dirty_agent_artifact_dirs: tuple[Path, ...]
    _dirty_agent_artifact_fallback_reason: str | None
    # Per-STARTING-agent ``agent_meta.json`` and ``waiting.json`` (mtime_ns,
    # size) cache used by the countdown-tick STARTING-transition poll.
    # Each tuple slot is ``None`` when that marker was absent on the
    # previous tick.
    _starting_poll_meta_cache: dict[
        tuple[AgentType, str, str | None],
        tuple[tuple[int, int] | None, tuple[int, int] | None],
    ]

    # Navigation gate (set up in startup.py). Used to defer the post-await
    # apply/render leg of `_run_agents_async_refresh` while the user is
    # mid j/k burst — the same protection `_on_artifact_change` and
    # `_on_auto_refresh` already apply to their refresh triggers.
    _nav_gate: NavigationGate
    _agent_load_state: AgentLoadState | None
    _agents_index_repair_notice_key: tuple[str | None, str | None] | None
    _agents_seen_complete_history: bool
    _agents_repro_capture: object | None

    def _apply_loaded_agents_prepared(
        self,
        prep: PreparedApplyData,
        *,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        load_state: AgentLoadState | None = None,
        persist_dismissed_changes: bool,
        dismissed_changes_include_removals: bool = False,
        incomplete_merge_already_applied: bool = False,
        precomputed_boundary: PreparedApplyBoundary | None = None,
        precomputed_fold_levels: dict[str, FoldLevel] | None = None,
        effective_runner_limit: int | None = None,
    ) -> None:
        raise NotImplementedError

    def _make_prepared_apply_snapshot(
        self,
        *,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        load_state: AgentLoadState | None,
    ) -> PreparedApplySnapshot:
        raise NotImplementedError

    async def _load_agents_async(
        self,
        *,
        full_history: bool = False,
        source: str = "unknown",
        index_freshness: Literal["revalidate", "cached"] = "cached",
    ) -> None:
        raise NotImplementedError

    def _load_agents(
        self,
        *,
        full_history: bool = False,
        source: str = "sync_load",
        index_freshness: Literal["revalidate", "cached"] = "cached",
    ) -> None:
        raise NotImplementedError

    def _schedule_artifact_index_maintenance(
        self,
        *,
        dismissed: Iterable[tuple[Any, str, str | None]],
        added: Iterable[tuple[Any, str, str | None]] | None = None,
        force: bool = False,
        source: str = "unknown",
    ) -> None:
        raise NotImplementedError

    async def _load_agent_artifact_delta_async(
        self,
        artifact_dirs: list[Path],
        *,
        source: str = "unknown",
        deleted_artifact_dirs: list[Path] | None = None,
    ) -> bool:
        raise NotImplementedError

    def _finalize_agent_list(
        self,
        on_agents_tab: bool,
        selected_identity: tuple[AgentType, str, str | None] | None,
        *,
        save_unfiltered: bool,
        fold_filter_already_applied: bool = False,
        prior_pos: int | None = None,
        precomputed_plan: PreparedFinalizePlan | None = None,
        previous_agents: list[Agent] | None = None,
        refresh_display: bool = True,
    ) -> None:
        raise NotImplementedError
