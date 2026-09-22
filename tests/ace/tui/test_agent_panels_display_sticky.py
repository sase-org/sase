"""Session-sticky panel keys for the Agents-tab tribe stack."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_live_query_engine import agents_history_query_key
from sase.ace.tui.models.agent_loader import AgentLoadState

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
    assert container.identity in app._session_mounted_identity_map()["epic"]


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
