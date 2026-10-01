"""Session-sticky panel keys for the Agents-tab tribe stack."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_live_query_engine import agents_history_query_key
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.core.agent_tab import AgentTabKey

from ._agent_panels_display_helpers import (
    _FakeApp,
    _agent,
    _three_panel_agents,
)


def _clan_member(
    *,
    name: str,
    suffix: str,
    clan: str,
    generation: str,
    tribe: str | None,
    status: str = "DONE",
) -> Agent:
    """Build one loaded member of a synthetic clan."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        agent_name=name,
        tribe=tribe,
        raw_suffix=suffix,
        agent_clan=clan,
        agent_clan_generation=generation,
    )


def _folded_epic_clan_app() -> tuple[_FakeApp, Agent, Agent, Agent]:
    """Fake app with a folded two-member ``epic`` clan plus a default agent."""
    first = _clan_member(
        name="e1", suffix="s1", clan="alpha", generation="g", tribe="epic"
    )
    second = _clan_member(
        name="e2", suffix="s2", clan="alpha", generation="g", tribe="epic"
    )
    home = _agent(name="u1", tribe=None, suffix="t1")
    projected = project_clan_tree([first, second, home])
    container = next(a for a in projected if a.is_clan_container)
    # Folded: only the synthetic container is rendered; members stay loaded.
    app = _FakeApp([container, home], option_counts=[1, 1], container_height=30)
    app._agents_with_children = projected  # type: ignore[attr-defined]
    app._dismissed_agents = set()  # type: ignore[attr-defined]
    return app, container, first, second


def _complete_history_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )


def _bounded_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        has_more=False,
        returned_count=0,
    )


def _sticky_widget_keys(app: _FakeApp) -> list[str | None]:
    """Return the keys the panel widgets would mount for the app's roster."""
    from sase.ace.tui.models.agent_panels import panel_keys_for

    return app._sorted_widget_panel_keys(
        panel_keys_for(app._agents),
        occupancy_with_rows=app._occupancy_keys_with_rows(),
    )


def test_dismissing_last_tribe_node_retires_its_sticky_panel_key() -> None:
    """An explicit removal of a tribe's last node unmounts its panel widget."""
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    banana = agents[2]

    app._agents = [a for a in app._agents if a.identity != banana.identity]
    # Absence alone keeps the panel: the roster is not proof the row is gone.
    assert _sticky_widget_keys(app) == [None, "apple", "banana"]

    assert app._retire_session_mounted_identities({banana.identity}) == {"banana"}

    assert _sticky_widget_keys(app) == [None, "apple"]
    assert app._session_mounted_panel_key_set() == {None, "apple"}


def test_dismissing_every_node_retires_every_sticky_panel_key() -> None:
    """With nothing left, only the empty-state ``[None]`` occupancy remains."""
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()

    retired = app._retire_session_mounted_identities({a.identity for a in agents})
    app._agents = []

    assert retired == {None, "apple", "banana"}
    assert app._session_mounted_panel_key_set() == set()
    assert _sticky_widget_keys(app) == [None]


def test_dismissing_a_sibling_keeps_the_tribe_sticky_key() -> None:
    """A tribe that still has a mounted node keeps its key after a sibling goes."""
    first = _agent(name="a1", tribe="apple", suffix="t1")
    second = _agent(name="a2", tribe="apple", suffix="t2")
    app = _FakeApp([first, second], option_counts=[2], container_height=30)
    app._remember_session_mounted_occupancy()

    assert app._retire_session_mounted_identities({first.identity}) == set()

    app._agents = [second]
    assert app._session_mounted_panel_key_set() == {"apple"}
    assert _sticky_widget_keys(app) == ["apple"]


def test_emptied_roster_without_removal_keeps_sticky_panel_keys() -> None:
    """Absence never retires a key: an incomplete load must not unmount tribes."""
    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()

    app._agents = []

    assert app._session_mounted_panel_key_set() == {None, "apple", "banana"}
    assert set(_sticky_widget_keys(app)) == {None, "apple", "banana"}


def test_committed_query_change_clears_the_sticky_store() -> None:
    """A new committed Agents query starts a fresh session-sticky store."""
    app = _FakeApp(_three_panel_agents(), [1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    assert app._session_mounted_panel_key_set() == {None, "apple", "banana"}

    app._agent_search_query = "tribe:apple"

    assert app._session_mounted_panel_key_set() == set()


def test_moving_last_node_retires_its_old_sticky_panel_key() -> None:
    """A row rendered under a new key proves it left the old panel."""
    home = _agent(name="u1", tribe=None, suffix="t1")
    research = _agent(name="r1", tribe="research", suffix="t9")
    app = _FakeApp([home, research], option_counts=[1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    assert app._session_mounted_panel_key_set() == {None, "research"}

    research.tribe = "apple"
    app._remember_session_mounted_occupancy()

    assert app._session_mounted_panel_key_set() == {None, "apple"}


def test_dismissal_elsewhere_retires_an_unrendered_sticky_key() -> None:
    """A dismissed identity with no rendered rows stops keeping its key."""
    agents = _three_panel_agents()
    app = _FakeApp(agents, [1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    banana = agents[2]
    app._dismissed_agents = {banana.identity}  # type: ignore[attr-defined]

    # Dropped from the roster without any explicit retire call.
    app._agents = [agents[0], agents[1]]
    app._remember_session_mounted_occupancy()

    assert app._session_mounted_panel_key_set() == {None, "apple"}


def test_dismissal_elsewhere_keeps_a_rendered_sticky_key() -> None:
    """A dismissed identity does not prune a key that still renders rows."""
    agents = _three_panel_agents()
    app = _FakeApp(agents, [1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    app._dismissed_agents = {agents[1].identity}  # type: ignore[attr-defined]

    app._remember_session_mounted_occupancy()

    assert app._session_mounted_panel_key_set() == {None, "apple", "banana"}


def test_dismissed_clan_backing_retires_the_container_key() -> None:
    """A container whose members are all dismissed stops keeping its key."""
    app, container, first, second = _folded_epic_clan_app()
    app._remember_session_mounted_occupancy()
    assert app._session_mounted_panel_key_set() == {None, "epic"}

    app._dismissed_agents = {first.identity, second.identity}  # type: ignore[attr-defined]
    app._agents = [a for a in app._agents if a.identity != container.identity]
    app._remember_session_mounted_occupancy()

    assert app._session_mounted_panel_key_set() == {None}


def test_live_clan_backing_keeps_the_container_key() -> None:
    """A container with a surviving member keeps its key while rendered."""
    app, container, first, second = _folded_epic_clan_app()
    app._remember_session_mounted_occupancy()
    app._dismissed_agents = {first.identity}  # type: ignore[attr-defined]

    app._remember_session_mounted_occupancy()

    assert app._session_mounted_panel_key_set() == {None, "epic"}
    assert (
        container.identity in app._session_mounted_identity_map()[("default", "epic")]
    )


def test_explicit_member_removal_retires_the_container_key() -> None:
    """Removing a clan's last members retires its container in the same call."""
    app, container, first, second = _folded_epic_clan_app()
    app._remember_session_mounted_occupancy()

    retired = app._retire_session_mounted_identities({first.identity, second.identity})

    assert retired == {"epic"}
    assert app._session_mounted_panel_key_set() == {None}


def test_explicit_partial_member_removal_keeps_the_container_key() -> None:
    """Removing one of two clan members leaves the container recorded."""
    app, container, first, _second = _folded_epic_clan_app()
    app._remember_session_mounted_occupancy()

    assert app._retire_session_mounted_identities({first.identity}) == set()
    assert app._session_mounted_panel_key_set() == {None, "epic"}


def test_retiring_sticky_keys_is_active_scope_only_and_unscoped() -> None:
    agents = _three_panel_agents()
    app = _FakeApp(agents, [1, 1, 1], container_height=30)
    active_identity, other_identity = agents[1].identity, agents[2].identity
    app._active_agent_tab = AgentTabKey.named("sase")  # type: ignore[attr-defined]
    app._session_mounted_panel_identities = {  # type: ignore[attr-defined]
        ("named:sase", "apple"): {active_identity},
        ("default", "banana"): {other_identity},
    }

    retired = app._prune_session_mounted_gone({active_identity, other_identity})

    assert retired == {"apple"}
    mounted = app._session_mounted_panel_identities  # type: ignore[attr-defined]
    assert ("named:sase", "apple") not in mounted
    assert mounted[("default", "banana")] == {other_identity}


def test_complete_history_apply_retires_identities_missing_from_roster() -> None:
    """An authoritative roster omits a sticky key's identities: the key goes."""
    agents = _three_panel_agents()
    app = _FakeApp(agents, [1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    app._agents_with_children = [agents[0], agents[1]]  # type: ignore[attr-defined]

    retired = app._reconcile_session_mounted_for_apply(_complete_history_state())

    assert retired == {"banana"}
    assert app._session_mounted_panel_key_set() == {None, "apple"}


def test_bounded_apply_keeps_identities_missing_from_roster() -> None:
    """A bounded zero is not removal authority: sticky keys survive it."""
    agents = _three_panel_agents()
    app = _FakeApp(agents, [1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    app._agents_with_children = []  # type: ignore[attr-defined]

    assert app._reconcile_session_mounted_for_apply(_bounded_state()) == set()
    assert app._session_mounted_panel_key_set() == {None, "apple", "banana"}


def test_complete_history_apply_for_stale_query_keeps_sticky_keys() -> None:
    """A complete roster for another query never prunes this query's store."""
    agents = _three_panel_agents()
    app = _FakeApp(agents, [1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    app._agents_with_children = [agents[0]]  # type: ignore[attr-defined]
    stale = _complete_history_state()
    object.__setattr__(
        stale, "history_query_key", agents_history_query_key("tribe:apple")
    )

    assert app._reconcile_session_mounted_for_apply(stale) == set()
    assert app._session_mounted_panel_key_set() == {None, "apple", "banana"}


def test_readded_key_waits_for_its_retiring_widget_prune() -> None:
    """A key re-added before its prune lands neither duplicates nor vanishes."""
    from sase.ace.tui.actions.agents._display_helpers import (
        agent_list_widgets_in,
        panel_widget_id_for_key,
        panel_widget_is_retiring,
    )

    agents = _three_panel_agents()
    app = _FakeApp(agents, [1, 1, 1], container_height=30)
    container = app._container
    main_id = panel_widget_id_for_key(None)
    apple_id = panel_widget_id_for_key("apple")
    banana_id = panel_widget_id_for_key("banana")
    doomed = next(w for w in container.children if w.id == banana_id)

    # Retiring hides and marks in the same sync. The widget stays mounted:
    # the fake ``remove()`` is a no-op, the way Textual's only schedules.
    ordered = app._sync_mounted_panel_widgets(container, [None, "apple"])

    assert ordered is not None
    assert [w.id for w in ordered] == [main_id, apple_id]
    assert panel_widget_is_retiring(doomed)
    assert doomed.display is False
    assert [w.id for w in agent_list_widgets_in(container)] == [main_id, apple_id]
    assert doomed in agent_list_widgets_in(container, include_retiring=True)

    # Re-added while the id is still taken: no duplicate mount, and the sync
    # reports itself incomplete so a follow-up refresh mounts the replacement.
    assert app._sync_mounted_panel_widgets(container, [None, "apple", "banana"]) is None
    assert sum(1 for w in container.children if w.id == banana_id) == 1

    # The prune lands; the next sync mounts a fresh widget for the key.
    container.children.remove(doomed)
    ordered = app._sync_mounted_panel_widgets(container, [None, "apple", "banana"])

    assert ordered is not None
    assert [w.id for w in ordered] == [main_id, apple_id, banana_id]
    replacement = next(w for w in container.children if w.id == banana_id)
    assert replacement is not doomed
    assert not panel_widget_is_retiring(replacement)
    assert replacement in agent_list_widgets_in(container)


def test_folded_into_another_tribe_clan_retires_old_key() -> None:
    """A loose row folded into another tribe's clan retires its old panel."""
    from sase.ace.tui.models.agent_panels import panel_keys_for

    home = _agent(name="u1", tribe=None, suffix="t1")
    loose_epic = _agent(name="e1", tribe="epic", suffix="s1")
    app = _FakeApp([home, loose_epic], option_counts=[1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    assert app._session_mounted_panel_key_set() == {None, "epic"}

    folded = _clan_member(
        name="e1", suffix="s1", clan="alpha", generation="g", tribe="epic"
    )
    folded.clan_tribe = "research"
    other = _clan_member(
        name="r1", suffix="s2", clan="alpha", generation="g", tribe="research"
    )
    other.clan_tribe = "research"
    projected = project_clan_tree([folded, other, home])
    container = next(a for a in projected if a.is_clan_container)
    app._agents = [container, home]
    app._agents_with_children = projected  # type: ignore[attr-defined]

    retired = app._sync_panel_group()

    assert retired == {"epic"}
    assert app._session_mounted_panel_key_set() == {None, "research"}
    assert _sticky_widget_keys(app) == [None, "research"]
    assert panel_keys_for(app._agents) == ["research", None] or set(
        _sticky_widget_keys(app)
    ) == {None, "research"}


def test_moved_to_another_tab_retires_old_key_in_active_scope() -> None:
    """A row scoped to another tab stops pinning the active tab's panel."""
    home = _agent(name="u1", tribe=None, suffix="t1")
    apple = _agent(name="a1", tribe="apple", suffix="t2")
    app = _FakeApp([home, apple], [1, 1], container_height=30)
    tab_a = AgentTabKey.named("a")
    tab_b = AgentTabKey.named("b")
    app._active_agent_tab = tab_a  # type: ignore[attr-defined]

    class _Index:
        def __init__(self, mapping: dict[object, object]) -> None:
            self._mapping = mapping

        def key_for(self, row: object) -> object:
            return self._mapping.get(row.identity, tab_a)  # type: ignore[attr-defined]

    app._agent_tab_index = _Index({home.identity: tab_a, apple.identity: tab_a})  # type: ignore[attr-defined]
    app._remember_session_mounted_occupancy()
    assert app._session_mounted_panel_key_set() == {None, "apple"}

    app._agents = [home]
    app._agents_with_children = [home, apple]  # type: ignore[attr-defined]
    app._agent_tab_index = _Index({home.identity: tab_a, apple.identity: tab_b})  # type: ignore[attr-defined]

    retired = app._sync_panel_group()

    assert retired == {"apple"}
    assert app._session_mounted_panel_key_set() == {None}


def test_container_identity_change_retires_default() -> None:
    """A re-keyed clan container retires `@default` once members move."""
    from datetime import datetime as _datetime

    from sase.ace.tui.models.agent import Agent as _Agent
    from sase.ace.tui.models.agent import AgentType as _AgentType

    def _member(suffix: str, generation: str | None, clan_tribe: str | None) -> _Agent:
        return _Agent(
            agent_type=_AgentType.RUNNING,
            cl_name="cl",
            project_file="/r/p/p.sase",
            status="DONE",
            start_time=_datetime(2026, 4, 25, 12, 0, 0),
            agent_name="m1",
            tribe=None,
            raw_suffix=suffix,
            agent_clan="alpha",
            agent_clan_generation=generation,
            clan_tribe=clan_tribe,
        )

    old_proj = project_clan_tree([_member("s1", None, None), _member("s2", None, None)])
    old_container = next(a for a in old_proj if a.is_clan_container)
    app = _FakeApp([old_container], option_counts=[1], container_height=30)
    app._agents_with_children = old_proj  # type: ignore[attr-defined]
    app._remember_session_mounted_occupancy()
    assert app._session_mounted_panel_key_set() == {None}

    new_proj = project_clan_tree(
        [_member("s1", "g1", "research"), _member("s2", "g1", "research")]
    )
    new_container = next(a for a in new_proj if a.is_clan_container)
    app._agents = [new_container]
    app._agents_with_children = new_proj  # type: ignore[attr-defined]

    retired = app._sync_panel_group()

    assert retired == {None}
    assert app._session_mounted_panel_key_set() == {"research"}
    assert _sticky_widget_keys(app) == ["research"]


def test_unaccounted_bridge_holds_then_expires(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """An emptied roster bridges briefly, then retires once the window lapses."""
    import sase.ace.tui.actions.agents._display_panel_collection as coll

    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    app._agents = []

    now = [100.0]
    monkeypatch.setattr(coll, "_sticky_now", lambda: now[0])

    assert app._remember_session_mounted_occupancy() == set()
    assert app._session_mounted_panel_key_set() == {None, "apple", "banana"}

    now[0] = 101.0
    assert app._remember_session_mounted_occupancy() == set()
    assert app._session_mounted_panel_key_set() == {None, "apple", "banana"}

    now[0] = 100.0 + coll.STICKY_PANEL_BRIDGE_S
    assert app._remember_session_mounted_occupancy() == {None, "apple", "banana"}
    assert app._session_mounted_panel_key_set() == set()
    assert _sticky_widget_keys(app) == [None]


def test_bridge_clears_when_identity_returns(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """An identity that renders again within the window never unmounts."""
    import sase.ace.tui.actions.agents._display_panel_collection as coll

    agents = _three_panel_agents()
    app = _FakeApp(agents, option_counts=[1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()
    now = [200.0]
    monkeypatch.setattr(coll, "_sticky_now", lambda: now[0])

    app._agents = []
    assert app._remember_session_mounted_occupancy() == set()
    assert app._session_sticky_unaccounted_since_map()

    now[0] = 201.0
    app._agents = list(agents)
    assert app._remember_session_mounted_occupancy() == set()
    assert app._session_mounted_panel_key_set() == {None, "apple", "banana"}
    assert app._session_sticky_unaccounted_since_map() == {}


def test_query_filtered_row_bridges_then_retires(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A roster-present but filtered row bridges, then retires on expiry."""
    import sase.ace.tui.actions.agents._display_panel_collection as coll

    home = _agent(name="u1", tribe=None, suffix="t1")
    epic = _agent(name="e1", tribe="epic", suffix="t2")
    app = _FakeApp([home, epic], [1, 1], container_height=30)
    app._agents_with_children = [home, epic]  # type: ignore[attr-defined]
    app._remember_session_mounted_occupancy()

    now = [300.0]
    monkeypatch.setattr(coll, "_sticky_now", lambda: now[0])
    app._agents = [home]
    assert app._remember_session_mounted_occupancy() == set()
    assert app._session_mounted_panel_key_set() == {None, "epic"}

    now[0] = 300.0 + coll.STICKY_PANEL_BRIDGE_S
    assert app._remember_session_mounted_occupancy() == {"epic"}
    assert app._session_mounted_panel_key_set() == {None}


def test_complete_history_retirement_reaches_next_sync() -> None:
    """An already-empty strip retires via pending keys on the next sync."""
    agents = _three_panel_agents()
    home, apple, banana = agents
    app = _FakeApp(agents, [1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()

    app._agents = [home, apple]
    app._agents_with_children = [home, apple, banana]  # type: ignore[attr-defined]
    assert app._remember_session_mounted_occupancy() == set()
    assert app._session_mounted_panel_key_set() == {None, "apple", "banana"}

    app._agents_with_children = [home, apple]  # type: ignore[attr-defined]
    assert app._reconcile_session_mounted_for_apply(_complete_history_state()) == {
        "banana"
    }

    assert app._sync_panel_group() == {"banana"}
    assert app._session_sticky_pending_retired_set() == set()
    assert _sticky_widget_keys(app) == [None, "apple"]


def test_countdown_hook_expires_bridges() -> None:
    """The countdown hook is a no-op until a bridge actually expires."""
    import sase.ace.tui.actions.agents._display_panel_collection as coll

    agents = _three_panel_agents()
    app = _FakeApp(agents, [1, 1, 1], container_height=30)
    app._remember_session_mounted_occupancy()

    calls: list[dict[str, object]] = []

    def _refresh(*, previous_agents: object, defer_detail: bool = False) -> None:
        calls.append({"previous_agents": previous_agents, "defer": defer_detail})

    app._refresh_agents_display_after_finalize = _refresh  # type: ignore[attr-defined]
    app._maybe_expire_sticky_panel_bridges(now_mono=1000.0)
    assert calls == []

    app._agents = []
    app._session_sticky_unaccounted_since_map().update(
        {a.identity: 1000.0 for a in agents}
    )
    app._maybe_expire_sticky_panel_bridges(now_mono=1001.0)
    assert calls == []
    app._maybe_expire_sticky_panel_bridges(now_mono=1000.0 + coll.STICKY_PANEL_BRIDGE_S)
    assert len(calls) == 1
