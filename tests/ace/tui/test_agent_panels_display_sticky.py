"""Session-sticky panel keys for the Agents-tab tribe stack."""

from __future__ import annotations

from ._agent_panels_display_helpers import (
    _FakeApp,
    _agent,
    _three_panel_agents,
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
