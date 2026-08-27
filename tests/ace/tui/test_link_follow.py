"""App-level ``$`` link-follow behavior."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Event

from sase.ace.tui.actions import link_follow
from sase.ace.tui.actions.link_follow import LinkFollowMixin
from sase.ace.tui.modals.artifact_links_panel_modal import (
    ArtifactLinksPanelModal,
    ArtifactLinksPanelResult,
)
from sase.ace.tui.relations.link_index import LinkChip
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import RelationRole
from sase.feature_flags import override_flags


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
    ) -> None:
        self._targets = targets
        self.current = selected
        self.query = query
        self.target_after_limit = target_after_limit
        self.applied_queries: list[tuple[str, bool]] = []
        self.revealed: tuple[ArtifactEntryTarget, RelationRole] | None = None
        self._loading = False
        self._loading_full = False

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        return self._targets

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        return self.current

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        if target not in self._targets:
            return False
        self.current = target
        return True

    def request_entry_target(self, target: ArtifactEntryTarget) -> bool:
        return self.select_entry_target(target)

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

    def apply_host_limit_query(self, query: str, *, grow: bool = False) -> None:
        self.query = query
        self.applied_queries.append((query, grow))
        if self.target_after_limit is not None:
            self._targets = (*self._targets, self.target_after_limit)


@dataclass
class _Agent:
    name: str
    identity: tuple[str, str, str | None]


class _App(LinkFollowMixin):
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

    def link_edges_for_selection(self) -> tuple[LinkChip, ...]:
        return self._chips

    def _artifacts_entry_navigator(self, pane_key: str | None = None) -> _Pane:
        return self._panes[pane_key or self.current_artifacts_pane_key]

    def _request_artifacts_entry(self, target: ArtifactEntryTarget) -> bool:
        self.current_artifacts_pane_key = target.pane_id
        return self._artifacts_entry_navigator(target.pane_id).request_entry_target(
            target
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

    with override_flags(link_rail=True):
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
        ("Expanded File limit to show linked file:hidden.txt", None)
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
    agent = _Agent(name="builder", identity=("done", "builder", None))
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
