"""Roster generation counter and cached projection index (sase-1d7.4)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.actions.agents._roster_generation import (
    bump_roster_generation,
    cached_agent_node_projection_index,
    get_roster_generation,
    notify_roster_status_mutation,
    set_agents_roster,
)
from sase.ace.tui.actions.agents._unread_state import AgentUnreadStateMixin
from sase.ace.tui.actions.agents._notification_unread_projection import (
    AgentNotificationUnreadMixin,
)
from tests.ace.tui._agent_unread_helpers import make_agent

_ACTIONS_ROOT = (
    Path(__file__).resolve().parents[3] / "src" / "sase" / "ace" / "tui" / "actions"
)
_ROSTER_ATTRS = frozenset({"_agents", "_agents_with_children"})


def _raw_roster_stores(path: Path) -> list[str]:
    """Return stored ``_agents`` attribute writes (AST-exact, incl. unpacks)."""
    import ast

    stores: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr not in _ROSTER_ATTRS or not isinstance(node.ctx, ast.Store):
            continue
        stores.append(f"{path.relative_to(_ACTIONS_ROOT)}:{node.lineno}")
    return stores


_ALLOWED_RAW_ASSIGNMENT_FILES = frozenset(
    {"_roster_generation.py", "_state_init_agents.py"}
)


def test_roster_assignments_route_through_set_agents_roster() -> None:
    """Fail when a raw ``_agents`` assignment appears outside the setter."""
    offenders = []
    for path in sorted(_ACTIONS_ROOT.rglob("*.py")):
        if path.name in _ALLOWED_RAW_ASSIGNMENT_FILES:
            continue
        offenders.extend(_raw_roster_stores(path))
    assert not offenders, (
        "raw roster assignments must go through set_agents_roster:\n"
        + "\n".join(offenders)
    )


def _stub_app(roster: list) -> SimpleNamespace:
    app = SimpleNamespace()
    app._agents_roster_generation = 0
    app._agents_with_children = list(roster)
    app._agents = list(roster)
    app._unread_completed_agent_ids = set()
    app._manual_unread_agent_ids = set()
    return app


def _roster() -> list:
    return [
        make_agent(name="a", status="DONE", raw_suffix="20260507090001"),
        make_agent(name="b", status="RUNNING", raw_suffix="20260507090002"),
        make_agent(name="c", status="DONE", raw_suffix="20260507090003"),
    ]


def test_set_agents_roster_assigns_and_bumps_once() -> None:
    app = _stub_app([])
    set_agents_roster(app, agents_with_children=[1], agents=[2])
    assert app._agents_with_children == [1]
    assert app._agents == [2]
    assert get_roster_generation(app) == 1


def test_set_agents_roster_partial_assignment_still_bumps() -> None:
    app = _stub_app([])
    set_agents_roster(app, agents=[2])
    assert app._agents == [2]
    assert app._agents_with_children == []
    assert get_roster_generation(app) == 1


def test_notify_roster_status_mutation_bumps_generation() -> None:
    app = _stub_app([])
    assert notify_roster_status_mutation(app) == 1
    assert bump_roster_generation(app) == 2


def test_cached_index_reuses_build_within_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.models.agent_nodes as agent_nodes

    builds = []
    real_build = agent_nodes.agent_node_projection_index

    def _counting(roster):  # type: ignore[no-untyped-def]
        builds.append(1)
        return real_build(roster)

    monkeypatch.setattr(agent_nodes, "agent_node_projection_index", _counting)
    app = _stub_app(_roster())
    first = cached_agent_node_projection_index(app, app._agents_with_children)
    second = cached_agent_node_projection_index(app, list(app._agents_with_children))
    assert second is first
    assert len(builds) == 1


def test_cached_index_invalidates_on_assignment_and_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.models.agent_nodes as agent_nodes

    builds: list[int] = []
    real_build = agent_nodes.agent_node_projection_index

    def _counting(roster):  # type: ignore[no-untyped-def]
        builds.append(1)
        return real_build(roster)

    monkeypatch.setattr(agent_nodes, "agent_node_projection_index", _counting)
    app = _stub_app(_roster())
    cached_agent_node_projection_index(app, app._agents_with_children)
    assert len(builds) == 1
    set_agents_roster(app, agents=list(app._agents))
    cached_agent_node_projection_index(app, app._agents)
    assert len(builds) == 2
    notify_roster_status_mutation(app)
    cached_agent_node_projection_index(app, app._agents)
    assert len(builds) == 3


def test_unread_paths_share_one_build_per_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bulk-ack key pass and the reconcile pass share one index build."""
    import sase.ace.tui.models.agent_nodes as agent_nodes

    builds: list[int] = []
    real_build = agent_nodes.agent_node_projection_index

    def _counting(roster):  # type: ignore[no-untyped-def]
        builds.append(1)
        return real_build(roster)

    monkeypatch.setattr(agent_nodes, "agent_node_projection_index", _counting)
    roster = _roster()
    app = _stub_app(roster)
    AgentUnreadStateMixin._notification_keys_for_agents(app, roster[:1])
    AgentNotificationUnreadMixin._apply_reconciled_unread_from_completion_notifications(
        app, []
    )
    assert len(builds) == 1
