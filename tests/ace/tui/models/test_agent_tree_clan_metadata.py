"""Clan-container tribe and summary metadata resolution."""

from __future__ import annotations

from sase.ace.tui.models._agent_loader_normalization import (
    apply_snapshot_clan_context,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models._loaders._meta_enrichment_wire import (
    enrich_agent_from_meta_wire,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentClanContextWire,
    AgentMetaWire,
)

from ._agent_tree_helpers import _agent


def test_project_clan_tree_uses_latest_explicit_clan_tribe() -> None:
    first = _agent(
        "research.first",
        "20260717100001",
        tribe="legacy",
        clan_tribe="alpha",
    )
    latest = _agent(
        "research.latest",
        "20260717100002",
        tribe="other-legacy",
        clan_tribe="beta",
    )
    later_without_declaration = _agent(
        "research.later",
        "20260717100003",
        tribe="ignored-legacy",
    )

    container = project_clan_tree([later_without_declaration, first, latest])[0]

    assert container.tribe == "beta"
    assert container.clan_tribe == "beta"
    assert container.clan_tribes == ("beta",)


def test_project_clan_tree_uses_context_when_declarer_is_omitted() -> None:
    context = AgentClanContextWire(
        agent_clan="toobig-0",
        agent_clan_generation="g1",
        clan_tribe="chop",
        clan_summary="Chop generation",
        clan_tribe_source_launch_timestamp="20260701000000",
        clan_tribe_source_identity="/tmp/declarer",
    )
    first = _agent(
        "toobig-0.first",
        "20260701000001",
        clan="toobig-0",
        generation="g1",
    )
    second = _agent(
        "toobig-0.second",
        "20260701000002",
        clan="toobig-0",
        generation="g1",
    )
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        clan_context=[context],
    )
    apply_snapshot_clan_context([first, second], snapshot)

    container, *members = project_clan_tree([first, second])

    assert members == [first, second]
    assert container.runtime_children == [first, second]
    assert container.clan_tribe == "chop"
    assert container.clan_summary == "Chop generation"
    assert container.clan_tribes == ("chop",)
    assert container.tribe == "chop"


def test_wire_enrichment_loads_clan_summary() -> None:
    agent = _agent("research.first", "one")

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(clan_summary="[bold]Research[/bold]"),
        None,
    )

    assert agent.clan_summary == "[bold]Research[/bold]"


def test_project_clan_tree_uses_latest_explicit_clan_summary() -> None:
    first = _agent(
        "research.first",
        "20260717100001",
        clan_summary="First summary",
    )
    latest = _agent(
        "research.latest",
        "20260717100002",
        clan_summary="[bold]Latest summary[/bold]",
    )
    later_without_declaration = _agent(
        "research.later",
        "20260717100003",
    )

    container = project_clan_tree([later_without_declaration, first, latest])[0]

    assert container.clan_summary == "[bold]Latest summary[/bold]"


def test_project_clan_tree_omits_summary_without_declaration() -> None:
    container = project_clan_tree(
        [
            _agent("research.first", "one"),
            _agent("research.second", "two"),
        ]
    )[0]

    assert container.clan_summary is None


def test_project_clan_tree_retains_direct_tribe_fallback() -> None:
    first = _agent("research.first", "one", tribe="alpha")
    second = _agent("research.second", "two", tribe="beta")

    container = project_clan_tree([first, second])[0]

    assert container.tribe is None
    assert container.clan_tribe is None
    assert container.clan_tribes == ("alpha", "beta")
