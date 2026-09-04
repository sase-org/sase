"""App-level ``$`` link-follow behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event

from sase.ace.query_record import QueryRecord
from sase.ace.tui.actions import link_follow
from sase.ace.tui.actions.artifacts_query_history import (
    ArtifactsQueryHistoryActionsMixin,
)
from sase.ace.tui.actions.link_follow import LinkFollowMixin
from sase.ace.tui.modals.artifact_links_panel_modal import (
    ArtifactLinksPanelModal,
    ArtifactLinksPanelResult,
)
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
    ) -> None:
        self._targets = targets
        self.current = selected
        self.query = query
        self.target_after_limit = target_after_limit
        self._resolver = resolver
        self._foldable = foldable
        self._probe = probe
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

    def _artifacts_entry_navigator(self, pane_key: str | None = None) -> _Pane:
        return self._panes[pane_key or self.current_artifacts_pane_key]

    def _request_artifacts_entry(
        self,
        target: ArtifactEntryTarget,
        *,
        generation: int | None = None,
    ) -> LinkRequestState:
        self.current_artifacts_pane_key = target.pane_id
        return self._artifacts_entry_navigator(target.pane_id).request_entry_target(
            target, generation=generation
        )

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

    def _files_pane(self) -> _Pane:
        return self._artifacts_entry_navigator("files")

    def _beads_pane(self) -> _Pane:
        return self._artifacts_entry_navigator("beads")

    def _commits_pane(self) -> _Pane:
        return self._artifacts_entry_navigator("stitches")

    def _active_documents_pane(self) -> _Pane:
        return self._artifacts_entry_navigator("ref:plan")

    def _schedule_query_history_persist(self) -> None:
        return

    def _schedule_query_selection_persist(self) -> None:
        return


def test_action_double_dollar_follows_first_link_and_records_origin() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.7"))
    app = _App(
        chips=(_chip("bead:sase-ug.7", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin, query="limit:40"),
            "beads": _Pane(targets=(target,)),
        },
    )

    app.action_follow_artifact_link()
    assert app._pending_link_prefix is True
    app.action_follow_artifact_link()

    assert app.current_tab == "artifacts"
    assert app.current_artifacts_pane_key == "beads"
    assert app._artifacts_entry_navigator("beads").selected_entry_target() == target
    assert app.artifacts_project_scope == "demo"
    assert len(app._link_trail) == 1
    assert app._link_trail[0].origin == origin


def test_follow_link_drops_head_slice_limit_before_missing_warning() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("files", ("hidden.txt",))
    pane = _Pane(
        targets=(origin,),
        selected=origin,
        query="kind:log limit:40",
        target_after_limit=target,
    )
    app = _App(
        chips=(_chip("file:hidden.txt", target),),
        panes={"files": pane},
    )

    app._follow_link_number(1)

    assert pane.applied_queries == [("kind:log limit:all", True)]
    assert pane.selected_entry_target() == target
    assert app.notifications == [
        ("Revealed file:hidden.txt — press ^ to restore your query", None)
    ]
    assert len(app._link_trail) == 1


def test_projected_group_opens_scoped_links_panel_without_trail() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("stitches", ("sase", "0123456789abcdef"))
    app = _App(
        chips=(
            _chip(
                "stitch:sase@0123456789abcdef",
                target,
                origin="projected",
                created_by="projection:stitch-bead",
            ),
            _chip(
                "stitch:sase@fedcba9876543210",
                target,
                origin="projected",
                created_by="projection:stitch-bead",
            ),
        ),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )

    app._follow_link_number(1)

    assert app.notifications == []
    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, ArtifactLinksPanelModal)
    assert modal._subject_ref == "file:origin.txt"
    assert len(modal._chips) == 2
    assert modal._scoped_label == "2 stitches"
    assert app._link_trail == []


def test_zero_opens_links_panel_with_staleness_notice() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    app._link_index_errors = ("demo: bad aggregate",)
    app._link_index_loading = True

    app._open_artifact_links_panel()

    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, ArtifactLinksPanelModal)
    assert modal._subject_ref == "file:origin.txt"
    assert modal._staleness_notice == (
        "Link index refresh in progress; showing the previous index.\n"
        "Some project link indexes were skipped: demo: bad aggregate"
    )


def test_links_panel_follow_result_jumps_without_numbered_rail_item() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    chip = _chip("bead:sase-ug.9", target)
    app = _App(
        chips=(chip,),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": _Pane(targets=(target,)),
        },
    )

    app._open_artifact_links_panel()
    callback = app.screen_callbacks[0]
    assert callable(callback)
    callback(ArtifactLinksPanelResult(action="follow", chip=chip))

    assert app.current_artifacts_pane_key == "beads"
    assert app._artifacts_entry_navigator("beads").selected_entry_target() == target
    assert len(app._link_trail) == 1


def test_links_panel_add_result_dispatches_existing_authoring_action() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )

    app._open_artifact_links_panel()
    callback = app.screen_callbacks[0]
    assert callable(callback)
    callback(ArtifactLinksPanelResult(action="add"))

    assert app.artifact_link_marked == 1


async def test_links_panel_remove_result_uses_existing_store_remove(
    monkeypatch,
) -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    chip = _chip(
        "bead:sase-ug.9",
        ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9")),
        relation="implements",
        label="implemented-by",
        this_is_source=False,
    )
    app = _App(
        chips=(chip,),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    calls: list[tuple[str, str, str]] = []
    app.link_refresh_event = Event()

    def remove(source_ref: str, target_ref: str, relation: str) -> dict[str, object]:
        calls.append((source_ref, target_ref, relation))
        return {"rows": [{"relation": relation}]}

    monkeypatch.setattr(link_follow, "_remove_artifact_link", remove)
    monkeypatch.setattr(link_follow, "_artifact_link_index_drift_notice", lambda: "")

    app._open_artifact_links_panel()
    callback = app.screen_callbacks[0]
    assert callable(callback)
    callback(ArtifactLinksPanelResult(action="remove", chip=chip))
    assert await asyncio.wait_for(
        asyncio.to_thread(app.link_refresh_event.wait),
        timeout=1.0,
    )

    assert calls == [("bead:sase-ug.9", "file:origin.txt", "implements")]
    assert app.notifications == [
        (
            "removed 1 implements link @bead:sase-ug.9 -> @file:origin.txt",
            None,
        )
    ]
    assert app.active_artifacts_refreshes == 1
    assert app.link_index_refreshes == ["artifact_link_remove"]


def test_loaded_agent_link_prefers_agents_tab_over_artifacts_pane() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    artifact_target = ArtifactEntryTarget("agents", ("builder",))
    agent = _Agent(agent_name="builder", identity=("done", "builder", None))
    app = _App(
        chips=(_chip("agent:builder", artifact_target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "agents": _Pane(targets=()),
        },
        agents=(agent,),
    )

    app._follow_link_number(1)

    assert app.current_tab == "agents"
    assert app.current_idx == 0
    assert app._agents_last_identity == agent.identity
    assert app.refreshed == 1
    assert app.rail_refreshed == 1
    assert len(app._link_trail) == 1


def _resolving_only(
    expect: tuple[str, str],
    resolved: ArtifactEntryTarget,
) -> Callable[[str, str], ArtifactEntryTarget | None]:
    def resolver(kind: str, payload: str) -> ArtifactEntryTarget | None:
        return resolved if (kind, payload) == expect else None

    return resolver


def test_follow_link_resolves_epic_kind_mismatch_via_pane_resolver() -> None:
    """A bead ref's chip hint always synthesizes kind ``task`` (Class A)."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    wrong_kind_hint = ArtifactEntryTarget("beads", ("demo", "task", "sase-w3"))
    real_target = ArtifactEntryTarget("beads", ("demo", "epic", "sase-w3"))
    app = _App(
        chips=(_chip("bead:sase-w3", wrong_kind_hint),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": _Pane(
                targets=(real_target,),
                resolver=_resolving_only(("bead", "sase-w3"), real_target),
            ),
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("beads")
    assert pane.selected_entry_target() == real_target
    assert len(app._link_trail) == 1


def test_follow_link_resolves_proposed_plan_kind_mismatch_via_pane_resolver() -> None:
    """A plan ref's chip hint always synthesizes stage ``archive`` (Class A)."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    wrong_stage_hint = ArtifactEntryTarget(
        "ref:plan", ("demo", "archive", "202609/x.md")
    )
    real_target = ArtifactEntryTarget("ref:plan", ("demo", "proposal", "notif-1"))
    app = _App(
        chips=(_chip("plan:202609/x.md", wrong_stage_hint),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "ref:plan": _Pane(
                targets=(real_target,),
                resolver=_resolving_only(("plan", "202609/x.md"), real_target),
            ),
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("ref:plan")
    assert pane.selected_entry_target() == real_target


def test_follow_link_resolves_abbreviated_stitch_sha_via_pane_resolver() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    abbreviated_hint = ArtifactEntryTarget("stitches", ("sase", "abc1234"))
    real_target = ArtifactEntryTarget("stitches", ("sase", "abc1234567890"))
    app = _App(
        chips=(_chip("stitch:sase@abc1234", abbreviated_hint),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "stitches": _Pane(
                targets=(real_target,),
                resolver=_resolving_only(("stitch", "sase@abc1234"), real_target),
            ),
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("stitches")
    assert pane.selected_entry_target() == real_target


def test_follow_link_resolves_cross_project_patch_via_pane_resolver() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    unscoped_hint = ArtifactEntryTarget("patches", ("", "shared-name"))
    real_target = ArtifactEntryTarget("patches", ("beta", "shared-name"))
    app = _App(
        chips=(_chip("patch:shared-name", unscoped_hint),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "patches": _Pane(
                targets=(real_target,),
                resolver=_resolving_only(("patch", "shared-name"), real_target),
            ),
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("patches")
    assert pane.selected_entry_target() == real_target


def test_follow_link_uses_chip_target_hint_when_pane_resolver_has_no_answer() -> None:
    """A pane with no answer degrades to the old chip-hint behavior, not a miss."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.7"))
    app = _App(
        chips=(_chip("bead:sase-ug.7", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": _Pane(targets=(target,)),  # no resolver configured
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("beads")
    assert pane.selected_entry_target() == target


def test_follow_link_no_longer_falls_back_to_family_reveal_rung() -> None:
    """The FAMILY-role reveal rung is gone; a miss reports honestly instead."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": _Pane(targets=()),
        },
    )

    app._follow_link_number(1)

    pane = app._artifacts_entry_navigator("beads")
    assert pane.revealed is None
    assert app.notifications == [
        ("Bead has no bead:sase-ug.9 in its inventory", "warning")
    ]
    assert app._link_trail == []


def test_follow_into_deferred_pane_returns_pending_until_resolved() -> None:
    """A follow into a loading pane opens a transaction instead of failing."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    beads_pane = _DeferredPane(app=app)
    app._panes["beads"] = beads_pane

    app._follow_link_number(1)

    assert app._link_trail == []
    assert app.notifications == []
    assert app.rail_refreshed == 0
    assert beads_pane._pending_target == target
    assert app._link_follow_transaction is not None

    beads_pane.resolve(LinkRequestState.SELECTED, reveal=target)

    assert beads_pane.selected_entry_target() == target
    assert len(app._link_trail) == 1
    assert app._link_trail[0].origin == origin
    assert app.rail_refreshed == 1
    assert app._link_follow_transaction is None


def test_second_follow_supersedes_pending_and_ignores_stale_resolution() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    first_target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.1"))
    second_target = ArtifactEntryTarget("files", ("other.txt",))
    app = _App(
        chips=(
            _chip("bead:sase-ug.1", first_target),
            _chip("file:other.txt", second_target),
        ),
        panes={"files": _Pane(targets=(origin, second_target), selected=origin)},
    )
    beads_pane = _DeferredPane(app=app)
    app._panes["beads"] = beads_pane

    app._follow_link_number(1)
    first_generation = app._link_follow_transaction.generation
    assert beads_pane._pending_target == first_target

    app._follow_link_number(2)

    assert app.current_artifacts_pane_key == "files"
    assert app._artifacts_entry_navigator("files").selected_entry_target() == (
        second_target
    )
    assert len(app._link_trail) == 1
    assert app.rail_refreshed == 1
    assert app._link_follow_transaction is None

    # The superseded first request's later resolution is silently ignored:
    # no stale trail hop, no toast.
    app._complete_link_follow_request(first_generation, LinkRequestState.SELECTED)

    assert len(app._link_trail) == 1
    assert app.notifications == []


def test_pending_follow_resolves_to_authoritative_missing_after_limit_drop() -> None:
    """A later authoritative MISSING still tries the host fallback once."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    beads_pane = _DeferredPane(app=app)
    app._panes["beads"] = beads_pane

    app._follow_link_number(1)
    assert app.notifications == []

    beads_pane.resolve(LinkRequestState.MISSING)

    assert app.notifications == [
        ("Bead has no bead:sase-ug.9 in its inventory", "warning")
    ]
    assert app._link_trail == []
    assert app._link_follow_transaction is None


def test_pending_follow_resolves_to_failed_with_distinct_error_copy() -> None:
    """A load/query failure is never described as deletion or absence."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={"files": _Pane(targets=(origin,), selected=origin)},
    )
    beads_pane = _DeferredPane(app=app)
    app._panes["beads"] = beads_pane

    app._follow_link_number(1)
    beads_pane.resolve(LinkRequestState.FAILED)

    assert app.notifications == [("Failed to load Bead for bead:sase-ug.9", "error")]
    assert app._link_trail == []
    assert app._link_follow_transaction is None


async def _await_hydration(app: _App) -> None:
    """Drain every pump-free hydration task the app has spawned."""
    tasks = tuple(getattr(app, "_link_hydration_tasks", ()))
    if tasks:
        await asyncio.gather(*tasks)


def test_hydration_not_attempted_when_a_reveal_rung_succeeds() -> None:
    """Fold expansion satisfies the follow, so hydration never fires."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    beads_pane = _Pane(targets=(), foldable=True)
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)

    assert beads_pane.selected_entry_target() == target
    assert beads_pane.hydrate_calls == []


async def test_hydration_fires_after_ladder_exhaustion_and_installs_row() -> None:
    """Every rung misses, so hydration resolves and finalizes the follow."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    hydrated_target = ArtifactEntryTarget("beads", ("demo", "epic", "sase-ug.9"))

    def hydrate(kind: str, payload: str) -> HydrationResult:
        assert (kind, payload) == ("bead", "sase-ug.9")
        return HydrationResult(HydrationOutcome.FETCHED, payload="fetched-row")

    beads_pane = _Pane(
        targets=(),
        hydrate_fn=hydrate,
        install_fn=lambda payload: hydrated_target,
    )
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await _await_hydration(app)

    assert beads_pane.hydrate_calls == [("bead", "sase-ug.9")]
    assert beads_pane.installed_payloads == ["fetched-row"]
    assert beads_pane.selected_entry_target() == hydrated_target
    assert app.notifications == []
    # The row was reachable without any query rewrite once installed, so
    # no reveal rung ever touched the pane's host-limit query.
    assert beads_pane.applied_queries == []
    assert len(app._link_trail) == 1
    assert app.rail_refreshed == 1
    assert app._link_follow_transaction is None


async def test_slow_hydration_stays_pending_without_a_miss_toast() -> None:
    """A slow lookup keeps the transaction open instead of reporting absence."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    hydrated_target = ArtifactEntryTarget("beads", ("demo", "epic", "sase-ug.9"))
    release = Event()

    def hydrate(kind: str, payload: str) -> HydrationResult:
        del kind, payload
        release.wait(timeout=2)
        return HydrationResult(HydrationOutcome.FETCHED, payload="fetched-row")

    beads_pane = _Pane(
        targets=(),
        hydrate_fn=hydrate,
        install_fn=lambda payload: hydrated_target,
    )
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await asyncio.sleep(0.05)

    assert app.notifications == []
    assert app._link_follow_transaction is not None
    assert app._link_trail == []

    release.set()
    await _await_hydration(app)

    assert beads_pane.selected_entry_target() == hydrated_target
    assert app.notifications == []
    assert len(app._link_trail) == 1


async def test_duplicate_hydration_requests_coalesce_into_one_lookup() -> None:
    """A repeated follow for the same pending ref reuses the in-flight lookup."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    hydrated_target = ArtifactEntryTarget("beads", ("demo", "epic", "sase-ug.9"))
    release = Event()
    calls: list[tuple[str, str]] = []

    def hydrate(kind: str, payload: str) -> HydrationResult:
        calls.append((kind, payload))
        release.wait(timeout=2)
        return HydrationResult(HydrationOutcome.FETCHED, payload="fetched-row")

    beads_pane = _Pane(
        targets=(),
        hydrate_fn=hydrate,
        install_fn=lambda payload: hydrated_target,
    )
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await asyncio.sleep(0.05)
    first_generation = app._link_follow_transaction.generation

    # A second follow of the identical ref while the lookup is in flight
    # must not spawn a second blocking call.
    app._follow_link_number(1)
    second_generation = app._link_follow_transaction.generation

    assert calls == [("bead", "sase-ug.9")]
    assert second_generation != first_generation

    release.set()
    await _await_hydration(app)

    assert beads_pane.selected_entry_target() == hydrated_target
    assert len(app._link_trail) == 1


async def test_second_follow_supersedes_in_flight_hydration() -> None:
    """A follow into a different target while hydrating drops the stale result."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    first_target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    second_target = ArtifactEntryTarget("files", ("other.txt",))
    release = Event()

    def hydrate(kind: str, payload: str) -> HydrationResult:
        del kind, payload
        release.wait(timeout=2)
        return HydrationResult(HydrationOutcome.FETCHED, payload="fetched-row")

    beads_pane = _Pane(targets=(), hydrate_fn=hydrate, install_fn=lambda payload: None)
    files_pane = _Pane(targets=(origin, second_target), selected=origin)
    app = _App(
        chips=(
            _chip("bead:sase-ug.9", first_target),
            _chip("file:other.txt", second_target),
        ),
        panes={"files": files_pane, "beads": beads_pane},
    )

    app._follow_link_number(1)
    await asyncio.sleep(0.05)

    app._follow_link_number(2)

    assert app._artifacts_entry_navigator("files").selected_entry_target() == (
        second_target
    )
    assert len(app._link_trail) == 1

    release.set()
    await _await_hydration(app)

    # The superseded hydration's late FETCHED result must not install a
    # row, record a trail hop, or emit a toast.
    assert beads_pane.installed_payloads == []
    assert len(app._link_trail) == 1
    assert app.notifications == []


async def test_hydration_exception_maps_to_failed() -> None:
    """An exception from the resolver is reported as FAILED, not deletion."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))

    def hydrate(kind: str, payload: str) -> HydrationResult:
        del kind, payload
        raise RuntimeError("store unavailable")

    beads_pane = _Pane(targets=(), hydrate_fn=hydrate)
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await _await_hydration(app)

    assert app.notifications == [("Failed to load Bead for bead:sase-ug.9", "error")]
    assert app._link_trail == []
    assert app._link_follow_transaction is None


async def test_hydration_absent_maps_to_dangling_message() -> None:
    """An authoritative direct-lookup miss reads as dangling, not inventory-miss."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))

    def hydrate(kind: str, payload: str) -> HydrationResult:
        del kind, payload
        return HydrationResult(HydrationOutcome.ABSENT)

    beads_pane = _Pane(targets=(), hydrate_fn=hydrate)
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await _await_hydration(app)

    assert app.notifications == [("No such artifact: bead:sase-ug.9", "warning")]
    assert app._link_trail == []


async def test_hydration_unsupported_falls_back_to_inventory_miss() -> None:
    """A pane with no direct source keeps the pre-hydration miss toast."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.9"))
    beads_pane = _Pane(targets=())  # no hydrate_fn: defaults to UNSUPPORTED
    app = _App(
        chips=(_chip("bead:sase-ug.9", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)
    await _await_hydration(app)

    assert beads_pane.hydrate_calls == [("bead", "sase-ug.9")]
    assert app.notifications == [
        ("Bead has no bead:sase-ug.9 in its inventory", "warning")
    ]


def test_dangling_ref_never_attempts_hydration() -> None:
    """A parsed-but-unroutable ref fails fast without ever reaching a pane."""
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    beads_pane = _Pane(targets=())
    app = _App(
        chips=(_chip("bug:missing", None),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": beads_pane,
        },
    )

    app._follow_link_number(1)

    assert beads_pane.hydrate_calls == []
    assert app.notifications == [("No such artifact: bug:missing", "warning")]


def test_pane_is_loading_recognizes_stitches_collection_and_query_state() -> None:
    """Stitches collection/query-session in-flight work counts as loading."""

    class _RunningWorker:
        is_running = True

    class _StitchesPane:
        _collection_worker: object | None = None
        _query_result_pending = False

    pane = _StitchesPane()
    assert link_follow._pane_is_loading(pane) is False

    pane._collection_worker = _RunningWorker()
    assert link_follow._pane_is_loading(pane) is True

    pane._collection_worker = None
    pane._query_result_pending = True
    assert link_follow._pane_is_loading(pane) is True
