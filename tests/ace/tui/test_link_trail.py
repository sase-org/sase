"""App-level link-trail back/forward walking (bead:sase-ug.8)."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.actions.link_follow import LinkFollowMixin, LinkTrailHop
from sase.ace.tui.actions.link_trail import LinkTrailMixin, link_trail_breadcrumb_text
from sase.ace.tui.relations.link_index import LinkChip
from sase.ace.tui.models.fold_state import FoldLevel, FoldStateManager
from sase.ace.tui.widgets.bgcmd_list import ChopItem, LumberjackItem
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import RelationRole


def _chip(
    neighbor_ref: str,
    neighbor_target: ArtifactEntryTarget | None,
    *,
    origin: str = "manual",
    created_by: str = "tester",
) -> LinkChip:
    return LinkChip(
        relation="cites",
        label="cites",
        directed=True,
        this_is_source=True,
        neighbor_ref=neighbor_ref,
        neighbor_target=neighbor_target,
        accent="#00D7AF",
        icon="◆",
        why="",
        origin=origin,
        uses=1,
        created_by=created_by,
        created_at="2026-08-26T00:00:00Z",
        writable=origin != "projected",
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
        self.applied_queries: list[str] = []
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
        del target, role
        return False

    def host_limit_query(self) -> str:
        return "" if self.query is None else self.query

    def apply_host_limit_query(self, query: str, *, grow: bool = False) -> None:
        self.query = query
        self.applied_queries.append(query)
        if grow and self.target_after_limit is not None:
            self._targets = (*self._targets, self.target_after_limit)


@dataclass
class _Agent:
    agent_name: str
    identity: tuple[str, str, str | None]


class _App(LinkFollowMixin, LinkTrailMixin):
    def __init__(
        self,
        *,
        chips: tuple[LinkChip, ...] = (),
        panes: dict[str, _Pane] | None = None,
        agents: tuple[_Agent, ...] = (),
        axe_items: tuple[object, ...] = (),
    ) -> None:
        self.focused = None
        self.current_tab = "artifacts"
        self.current_artifacts_pane_key = "files"
        self.current_idx = 0
        self.artifacts_project_scope = None
        self._pending_link_prefix = False
        self._link_trail: list[LinkTrailHop] = []
        self._link_trail_forward: list[LinkTrailHop] = []
        self._link_trail_guard = False
        self._chips = chips
        self._panes = panes or {}
        self._agents = list(agents)
        self._agents_last_idx = 0
        self._agents_last_identity = None
        self._axe_items = list(axe_items)
        self._axe_last_idx = 0
        self._axe_last_item_key = None
        self.notifications: list[tuple[str, str | None]] = []
        self.saved_positions = 0
        self.synced = 0
        self.refreshed = 0
        self.rail_refreshed = 0
        self.entry_jump_restores = 0

    def link_edges_for_selection(self) -> tuple[LinkChip, ...]:
        return self._chips

    def _artifacts_entry_navigator(self, pane_key: str | None = None) -> _Pane | None:
        return self._panes.get(pane_key or self.current_artifacts_pane_key)

    def _request_artifacts_entry(self, target: ArtifactEntryTarget) -> bool:
        self.current_artifacts_pane_key = target.pane_id
        pane = self._artifacts_entry_navigator(target.pane_id)
        return bool(pane is not None and pane.request_entry_target(target))

    def _set_artifacts_project_scope(
        self, project: str | None, *, picked: bool
    ) -> None:
        del picked
        self.artifacts_project_scope = project

    def _sync_active_artifacts_entry_state(self) -> None:
        self.synced += 1
        self._note_artifacts_selection_for_link_trail()

    def _save_current_tab_position(self) -> None:
        self.saved_positions += 1

    def _refresh_current_tab(self) -> None:
        self.refreshed += 1

    def _refresh_after_entry_jump_restore(self) -> None:
        self.entry_jump_restores += 1

    def refresh_link_rail(self) -> None:
        self.rail_refreshed += 1

    def _get_selected_agent(self) -> _Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))


def _follow_first(app: _App) -> None:
    app._follow_link_number(1)


def test_back_and_forward_round_trip_between_artifacts_and_agents() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    agent_target = ArtifactEntryTarget("agents", ("builder",))
    agent = _Agent(agent_name="builder", identity=("done", "builder", None))
    files_pane = _Pane(targets=(origin,), selected=origin)
    app = _App(
        chips=(_chip("agent:builder", agent_target),),
        panes={"files": files_pane},
        agents=(agent,),
    )

    _follow_first(app)
    assert app.current_tab == "agents"
    assert app.current_idx == 0
    assert len(app._link_trail) == 1

    assert app._walk_link_trail_back() is True
    assert app.current_tab == "artifacts"
    assert app.current_artifacts_pane_key == "files"
    assert files_pane.selected_entry_target() == origin
    assert app._link_trail == []
    assert len(app._link_trail_forward) == 1
    assert app.entry_jump_restores == 1

    assert app._walk_link_trail_forward() is True
    assert app.current_tab == "agents"
    assert app.current_idx == 0
    assert app._agents_last_identity == agent.identity
    assert app._link_trail_forward == []
    assert len(app._link_trail) == 1


def test_back_restores_narrowed_query_widened_by_the_forward_hop() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("files", ("hidden.txt",))
    pane = _Pane(
        targets=(origin,),
        selected=origin,
        query="kind:log limit:40",
        target_after_limit=target,
    )
    app = _App(chips=(_chip("file:hidden.txt", target),), panes={"files": pane})

    _follow_first(app)
    assert pane.applied_queries == ["kind:log limit:all"]
    assert pane.selected_entry_target() == target

    assert app._walk_link_trail_back() is True
    assert pane.query == "kind:log limit:40"
    assert pane.selected_entry_target() == origin


def test_back_restores_project_scope_changed_by_the_forward_hop() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("beads", ("demo", "task", "sase-ug.7"))
    app = _App(
        chips=(_chip("bead:sase-ug.7", target),),
        panes={
            "files": _Pane(targets=(origin,), selected=origin),
            "beads": _Pane(targets=(target,)),
        },
    )

    _follow_first(app)
    assert app.artifacts_project_scope == "demo"

    assert app._walk_link_trail_back() is True
    assert app.artifacts_project_scope is None


def test_axe_hop_restores_across_tabs_and_expands_the_lumberjack() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    chop_target_ref = "chop:hooks/build"
    axe_items = (LumberjackItem(name="hooks"), ChopItem("hooks", "build"))
    files_pane = _Pane(targets=(origin,), selected=origin)
    app = _App(
        chips=(_chip(chop_target_ref, None),),
        panes={"files": files_pane},
        axe_items=axe_items,
    )

    _follow_first(app)
    assert app.current_tab == "axe"
    assert app.current_idx == 1

    assert app._walk_link_trail_back() is True
    assert app.current_tab == "artifacts"
    assert files_pane.selected_entry_target() == origin

    assert app._walk_link_trail_forward() is True
    assert app.current_tab == "axe"
    assert app.current_idx == 1
    assert app._axe_last_item_key == ("chop", "hooks", "build")


class _FoldingAxeApp(_App):
    """An app whose AXE tree really folds, so expansion can be undone.

    The plain ``_App`` has no fold manager, which is the "nothing to restore"
    case every other AXE test exercises. This one reveals chops only while
    their lumberjack is expanded, so a forward hop to a chop under a collapsed
    lumberjack has to expand it -- and walking back has to put it back.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._axe_fold_manager = FoldStateManager()
        self._build_axe_items()

    def _build_axe_items(self) -> None:
        expanded = (
            self._axe_fold_manager.get("lumberjack:hooks") is not FoldLevel.COLLAPSED
        )
        self._axe_items = [LumberjackItem(name="hooks")]
        if expanded:
            self._axe_items.append(ChopItem("hooks", "build"))

    @property
    def hooks_expanded(self) -> bool:
        return self._axe_fold_manager.get("lumberjack:hooks") is not FoldLevel.COLLAPSED


def test_back_walk_re_collapses_the_lumberjack_the_forward_hop_expanded() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    files_pane = _Pane(targets=(origin,), selected=origin)
    app = _FoldingAxeApp(
        chips=(_chip("chop:hooks/build", None),),
        panes={"files": files_pane},
    )
    assert app.hooks_expanded is False

    _follow_first(app)
    assert app.current_tab == "axe"
    assert app.hooks_expanded is True
    assert app._link_trail[-1].axe_fold_expanded == "hooks"

    assert app._walk_link_trail_back() is True
    assert app.current_tab == "artifacts"
    assert app.hooks_expanded is False, "Ctrl+O left the AXE tree expanded"

    assert app._walk_link_trail_forward() is True
    assert app.hooks_expanded is True

    assert app._walk_link_trail_back() is True
    assert app.hooks_expanded is False, (
        "the expansion was lost on the round trip, so the second Ctrl+O "
        "could not undo it"
    )


def test_back_walk_leaves_a_lumberjack_the_hop_did_not_expand_alone() -> None:
    """A hop that changed no fold must not collapse one on the way back.

    ``FoldStateManager`` has three rungs, and a lumberjack the user already
    drove to the top rung cannot advance further, so the hop records nothing
    and ``Ctrl+O`` must leave their tree exactly as they left it.
    """
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    files_pane = _Pane(targets=(origin,), selected=origin)
    app = _FoldingAxeApp(
        chips=(_chip("chop:hooks/build", None),),
        panes={"files": files_pane},
    )
    app._axe_fold_manager.expand("lumberjack:hooks")
    app._axe_fold_manager.expand("lumberjack:hooks")
    app._build_axe_items()
    assert app._axe_fold_manager.get("lumberjack:hooks") is FoldLevel.FULLY_EXPANDED

    _follow_first(app)
    assert app._link_trail[-1].axe_fold_expanded is None

    assert app._walk_link_trail_back() is True
    assert app._axe_fold_manager.get("lumberjack:hooks") is FoldLevel.FULLY_EXPANDED, (
        "walking back collapsed a lumberjack the user had opened themselves"
    )


def test_agents_to_axe_hop_round_trips_the_last_untested_tab_pair() -> None:
    """The third pair: neither endpoint is the Artifacts tab.

    Both other pairs start on Artifacts, whose restore path carries the pane
    key, query, and project scope. Agents and AXE restore from an agent name
    and an item key instead, so this is the pair that proves the walk does
    not quietly depend on the Artifacts branch.
    """
    agent = _Agent(agent_name="builder", identity=("done", "builder", None))
    axe_items = (LumberjackItem(name="hooks"), ChopItem("hooks", "build"))
    app = _App(
        chips=(_chip("chop:hooks/build", None),),
        agents=(agent,),
        axe_items=axe_items,
    )
    app.current_tab = "agents"

    _follow_first(app)
    assert app.current_tab == "axe"
    assert app.current_idx == 1
    assert [hop.tab for hop in app._link_trail] == ["agents"]

    assert app._walk_link_trail_back() is True
    assert app.current_tab == "agents"
    assert app.current_idx == 0
    assert app._agents_last_identity == agent.identity
    assert app._link_trail == []

    assert app._walk_link_trail_forward() is True
    assert app.current_tab == "axe"
    assert app.current_idx == 1
    assert app._axe_last_item_key == ("chop", "hooks", "build")


def test_walking_back_with_an_empty_trail_is_a_noop() -> None:
    app = _App()

    assert app._walk_link_trail_back() is False
    assert app._walk_link_trail_forward() is False
    assert app.notifications == []


def test_link_follow_does_not_clear_its_own_trail_mid_chain() -> None:
    """``$1 $1`` must accumulate two hops, not wipe the first mid-jump."""
    a = ArtifactEntryTarget("files", ("a.txt",))
    b = ArtifactEntryTarget("files", ("b.txt",))
    c = ArtifactEntryTarget("files", ("c.txt",))
    pane = _Pane(targets=(a, b, c), selected=a)
    app = _App(chips=(_chip("file:b.txt", b),), panes={"files": pane})

    _follow_first(app)
    assert len(app._link_trail) == 1

    app._chips = (_chip("file:c.txt", c),)
    _follow_first(app)
    assert len(app._link_trail) == 2
    assert app._link_trail[0].origin == a
    assert app._link_trail[1].origin == b


def test_other_navigation_clears_the_trail() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("files", ("hidden.txt",))
    other = ArtifactEntryTarget("files", ("other.txt",))
    pane = _Pane(targets=(origin, target, other), selected=origin)
    app = _App(chips=(_chip("file:hidden.txt", target),), panes={"files": pane})

    _follow_first(app)
    assert app._link_trail != []

    # Simulate the user moving the cursor by hand, unrelated to the trail.
    pane.select_entry_target(other)
    app._note_artifacts_selection_for_link_trail()

    assert app._link_trail == []
    assert app._link_trail_forward == []


def test_marking_a_row_does_not_clear_the_trail() -> None:
    origin = ArtifactEntryTarget("files", ("origin.txt",))
    target = ArtifactEntryTarget("files", ("hidden.txt",))
    pane = _Pane(targets=(origin, target), selected=origin)
    app = _App(chips=(_chip("file:hidden.txt", target),), panes={"files": pane})

    _follow_first(app)
    assert app._link_trail != []

    # A mark toggle re-syncs footer state without moving the selection.
    app._note_artifacts_selection_for_link_trail()
    app._note_artifacts_selection_for_link_trail()

    assert app._link_trail != []


def test_breadcrumb_text_is_none_with_an_empty_trail() -> None:
    app = _App()

    assert link_trail_breadcrumb_text(app) is None


def test_breadcrumb_text_shows_hidden_count_beyond_the_top_hop() -> None:
    a = ArtifactEntryTarget("files", ("a.txt",))
    b = ArtifactEntryTarget("files", ("b.txt",))
    c = ArtifactEntryTarget("files", ("c.txt",))
    pane = _Pane(targets=(a, b, c), selected=a)
    app = _App(chips=(_chip("file:b.txt", b),), panes={"files": pane})

    _follow_first(app)
    assert link_trail_breadcrumb_text(app) == "⟨ ▤ a.txt ⟩"

    app._chips = (_chip("file:c.txt", c),)
    _follow_first(app)
    assert link_trail_breadcrumb_text(app) == "⟨ …1 › ▤ b.txt ⟩"
