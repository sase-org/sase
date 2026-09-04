"""Shared fixtures for ``$`` link-follow tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sase.ace.query_record import QueryRecord
from sase.ace.tui.actions.artifacts_query_history import (
    ArtifactsQueryHistoryActionsMixin,
)
from sase.ace.tui.actions.link_follow import LinkFollowMixin
from sase.ace.tui.relations.link_index import LinkChip
from sase.ace.tui.widgets.artifacts.entry_navigation import (
    HydrationOutcome,
    HydrationResult,
    LinkRequestState,
)
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import RelationRole


def _chip(
    neighbor_ref: str,
    neighbor_target: ArtifactEntryTarget | None,
    *,
    origin: str = "manual",
    created_by: str = "tester",
    relation: str = "cites",
    label: str = "cites",
    this_is_source: bool = True,
    writable: bool | None = None,
) -> LinkChip:
    return LinkChip(
        relation=relation,
        label=label,
        directed=True,
        this_is_source=this_is_source,
        neighbor_ref=neighbor_ref,
        neighbor_target=neighbor_target,
        accent="#00D7AF",
        icon="◆",
        why="",
        origin=origin,
        uses=1,
        created_by=created_by,
        created_at="2026-08-26T00:00:00Z",
        writable=origin != "projected" if writable is None else writable,
    )


class _Pane:
    def __init__(
        self,
        *,
        targets: tuple[ArtifactEntryTarget, ...],
        selected: ArtifactEntryTarget | None = None,
        query: str | None = None,
        target_after_limit: ArtifactEntryTarget | None = None,
        resolver: Callable[[str, str], ArtifactEntryTarget | None] | None = None,
        foldable: bool = False,
        probe: object | None = None,
        reveal_when: Callable[[str], bool] | None = None,
        filter_session_open: bool = False,
        hydrate_fn: Callable[[str, str], HydrationResult] | None = None,
        install_fn: Callable[[object], ArtifactEntryTarget | None] | None = None,
        query_profile: object | None = None,
        identity_row: object | None = None,
    ) -> None:
        self._targets = targets
        self.current = selected
        self.query = query
        self.target_after_limit = target_after_limit
        self._resolver = resolver
        self._foldable = foldable
        self._probe = probe
        self._query_profile = query_profile
        self._identity_row = identity_row
        self.reveal_when = reveal_when
        self.applied_queries: list[tuple[str, bool]] = []
        self.expanded_folds: list[ArtifactEntryTarget] = []
        self.closed_sessions = 0
        self._filter_session_open = filter_session_open
        self._hydrate_fn = hydrate_fn
        self._install_fn = install_fn
        self.hydrate_calls: list[tuple[str, str]] = []
        self.installed_payloads: list[object] = []
        self.revealed: tuple[ArtifactEntryTarget, RelationRole] | None = None
        self._loading = False
        self._loading_full = False
        self.app: object | None = None
        self.pane_id: str | None = None

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        return self._targets

    def entry_target_for_ref(
        self, kind: str, payload: str
    ) -> ArtifactEntryTarget | None:
        return None if self._resolver is None else self._resolver(kind, payload)

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        return self.current

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        if target not in self._targets:
            return False
        self.current = target
        return True

    def request_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        generation: int | None = None,
    ) -> LinkRequestState:
        del generation
        if self.select_entry_target(target):
            return LinkRequestState.SELECTED
        return LinkRequestState.MISSING

    def reveal_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        role: RelationRole,
    ) -> bool:
        self.revealed = (target, role)
        return False

    def host_limit_query(self) -> str:
        return "" if self.query is None else self.query

    def query_history_record(self) -> QueryRecord:
        query = self.host_limit_query()
        return QueryRecord(source=query, canonical=query)

    def apply_query_history_record(self, record: QueryRecord) -> bool:
        self.query = record.source
        return True

    def expand_fold_for_entry_target(self, target: ArtifactEntryTarget) -> bool:
        if not self._foldable or target in self._targets:
            return False
        self._targets = (*self._targets, target)
        self.expanded_folds.append(target)
        return True

    def close_host_filter_session(self) -> None:
        if self._filter_session_open:
            self._filter_session_open = False
            self.closed_sessions += 1

    def hydrate_ref(self, kind: str, payload: str) -> HydrationResult:
        self.hydrate_calls.append((kind, payload))
        if self._hydrate_fn is None:
            return HydrationResult(HydrationOutcome.UNSUPPORTED)
        return self._hydrate_fn(kind, payload)

    def install_hydrated_row(self, payload: object) -> ArtifactEntryTarget | None:
        self.installed_payloads.append(payload)
        if self._install_fn is None:
            return None
        target = self._install_fn(payload)
        if target is not None and target not in self._targets:
            self._targets = (*self._targets, target)
        return target

    def host_query_row_for_target(self, target: ArtifactEntryTarget) -> object | None:
        del target
        return self._identity_row

    def host_query_probe(self, target: ArtifactEntryTarget) -> object | None:
        del target
        return self._probe

    def apply_host_limit_query(self, query: str, *, grow: bool = False) -> None:
        old = self.host_limit_query()
        old_target = self.current
        self.query = query
        self.applied_queries.append((query, grow))
        should_reveal = (
            self.reveal_when(query)
            if self.reveal_when is not None
            else self.target_after_limit is not None
        )
        if should_reveal and self.target_after_limit is not None:
            if self.target_after_limit not in self._targets:
                self._targets = (*self._targets, self.target_after_limit)
        app = getattr(self, "app", None)
        pane_id = getattr(self, "pane_id", None)
        recorder = getattr(app, "_record_artifacts_query_transition", None)
        if callable(recorder) and pane_id is not None:
            recorder(
                pane_id,
                old_source=old,
                old_canonical=old,
                old_profile_digest=None,
                new_canonical=query,
                selected_target=old_target,
            )


class _DeferredPane:
    """A minimal async-pane stand-in that defers until :meth:`resolve` fires.

    Unlike :class:`_Pane` (which always resolves synchronously, mirroring
    Patches), this models the async panes (Agents/Beads/Files/Plans/
    Stitches): a miss returns ``PENDING`` and retains the generation, and a
    later refresh reports the real outcome through the same
    ``app._complete_link_follow_request`` seam the shared
    ``ArtifactEntryNavigator._complete_entry_request`` helper uses.
    """

    def __init__(
        self,
        *,
        app: _App,
        targets: tuple[ArtifactEntryTarget, ...] = (),
    ) -> None:
        self.app = app
        self._targets = targets
        self.current: ArtifactEntryTarget | None = None
        self._pending_target: ArtifactEntryTarget | None = None
        self._pending_generation: int | None = None
        self._loading = False
        self._loading_full = False

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        return self._targets

    def entry_target_for_ref(
        self, kind: str, payload: str
    ) -> ArtifactEntryTarget | None:
        del kind, payload
        return None

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        return self.current

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        if target not in self._targets:
            return False
        self.current = target
        return True

    def request_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        generation: int | None = None,
    ) -> LinkRequestState:
        if self.select_entry_target(target):
            return LinkRequestState.SELECTED
        self._pending_target = target
        self._pending_generation = generation
        return LinkRequestState.PENDING

    def resolve(
        self,
        state: LinkRequestState,
        *,
        reveal: ArtifactEntryTarget | None = None,
    ) -> None:
        """Simulate a later async refresh reporting *state* for the pending request."""
        target = self._pending_target
        generation = self._pending_generation
        self._pending_target = None
        self._pending_generation = None
        if reveal is not None:
            self._targets = (*self._targets, reveal)
        if state is LinkRequestState.SELECTED and target is not None:
            self.select_entry_target(target)
        if generation is not None:
            self.app._complete_link_follow_request(generation, state)

    def host_limit_query(self) -> str:
        return ""

    def apply_host_limit_query(self, query: str, *, grow: bool = False) -> None:
        del query, grow


@dataclass
class _Agent:
    agent_name: str
    identity: tuple[str, str, str | None]


class _App(LinkFollowMixin, ArtifactsQueryHistoryActionsMixin):
    def __init__(
        self,
        *,
        chips: tuple[LinkChip, ...],
        panes: dict[str, _Pane],
        agents: tuple[_Agent, ...] = (),
    ) -> None:
        self.focused = None
        self.current_tab = "artifacts"
        self.current_artifacts_pane_key = "files"
        self.current_idx = 0
        self.artifacts_project_scope = None
        self._pending_link_prefix = False
        self._link_trail = []
        self._link_follow_generation = 0
        self._link_follow_transaction = None
        self._link_follow_dispatching = False
        self._link_reveals = {}
        self._collapsed_query_transitions = None
        self._collapsed_query_transition_recorded = False
        self._query_history = {}
        self._query_selections = {}
        self._chips = chips
        self._panes = panes
        self._agents = list(agents)
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self.notifications: list[tuple[str, str | None]] = []
        self.pushed_screens: list[object] = []
        self.screen_callbacks: list[object] = []
        self.artifact_link_marked = 0
        self.active_artifacts_refreshes = 0
        self.link_index_refreshes: list[str] = []
        self._link_index = object()
        self._link_index_errors = ()
        self._link_index_loading = False
        self._link_index_pending = False
        self.saved_positions = 0
        self.synced = 0
        self.refreshed = 0
        self.rail_refreshed = 0
        for pane_id, pane in panes.items():
            pane.pane_id = pane_id
            pane.app = self

    def link_edges_for_selection(self) -> tuple[LinkChip, ...]:
        return self._chips

    def _artifacts_entry_navigator(self, pane_key: str | None = None) -> _Pane | None:
        return self._panes.get(pane_key or self.current_artifacts_pane_key)

    def _request_artifacts_entry(
        self,
        target: ArtifactEntryTarget,
        *,
        generation: int | None = None,
    ) -> LinkRequestState:
        self.current_artifacts_pane_key = target.pane_id
        pane = self._artifacts_entry_navigator(target.pane_id)
        if pane is None:
            return LinkRequestState.MISSING
        return pane.request_entry_target(target, generation=generation)

    def _set_artifacts_project_scope(
        self, project: str | None, *, picked: bool
    ) -> None:
        del picked
        self.artifacts_project_scope = project

    def _sync_active_artifacts_entry_state(self) -> None:
        self.synced += 1

    def _save_current_tab_position(self) -> None:
        self.saved_positions += 1

    def _refresh_current_tab(self) -> None:
        self.refreshed += 1

    def refresh_link_rail(self) -> None:
        self.rail_refreshed += 1

    def _get_selected_agent(self) -> _Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def push_screen(self, screen: object, callback: object | None = None) -> None:
        self.pushed_screens.append(screen)
        self.screen_callbacks.append(callback)

    def action_artifacts_link_marked(self) -> None:
        self.artifact_link_marked += 1

    def _request_active_artifacts_refresh(self) -> None:
        self.active_artifacts_refreshes += 1

    def _schedule_link_index_refresh(self, *, source: str) -> None:
        self.link_index_refreshes.append(source)
        event = getattr(self, "link_refresh_event", None)
        if event is not None:
            event.set()

    def _files_pane(self) -> _Pane | None:
        return self._artifacts_entry_navigator("files")

    def _beads_pane(self) -> _Pane | None:
        return self._artifacts_entry_navigator("beads")

    def _commits_pane(self) -> _Pane | None:
        return self._artifacts_entry_navigator("stitches")

    def _active_documents_pane(self) -> _Pane | None:
        return self._artifacts_entry_navigator("ref:plan")

    def _schedule_query_history_persist(self) -> None:
        return

    def _schedule_query_selection_persist(self) -> None:
        return


def _resolving_only(
    expect: tuple[str, str],
    resolved: ArtifactEntryTarget,
) -> Callable[[str, str], ArtifactEntryTarget | None]:
    def resolver(kind: str, payload: str) -> ArtifactEntryTarget | None:
        return resolved if (kind, payload) == expect else None

    return resolver
