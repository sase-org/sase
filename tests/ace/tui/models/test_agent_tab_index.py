"""Per-root agent-tab index model tests."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from sase.ace.tui.models import agent_tab_index as index_mod
from sase.ace.tui.models._agent_tree_clan import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tab_index import (
    build_agent_tab_index,
    cached_agent_tab_index,
    clear_agent_tab_index_cache,
)
from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.core.agent_tab import (
    AgentTabKey,
    agent_tab_key_token,
    parse_agent_tab_key_token,
)


@pytest.fixture(autouse=True)
def _clear_index_cache() -> Iterator[None]:
    clear_agent_tab_index_cache()
    yield
    clear_agent_tab_index_cache()


def _view(
    *,
    machine_mode: bool = False,
    machine_order: tuple[tuple[str, str], ...] = (),
    pinned_by_alias: dict[str, str] | None = None,
    named_order: dict[str, int] | None = None,
    token: tuple[Any, ...] = ("test", 1),
) -> AgentTabsViewConfig:
    return AgentTabsViewConfig(
        machine_mode=machine_mode,
        machine_order=machine_order,
        pinned_by_alias=pinned_by_alias or {},
        named_order=named_order or {},
        token=token,
    )


def _row(
    suffix: str,
    *,
    tab: str | None = None,
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
    fleet_origin_alias: str | None = None,
    fleet_origin_installation_id: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="proj",
        project_file="/proj/project.yml",
        status=status,
        start_time=None,
        raw_suffix=suffix,
        parent_timestamp=parent_timestamp,
        agent_tab=tab,
        agent_clan=agent_clan,
        agent_clan_generation=agent_clan_generation,
        fleet_origin_alias=fleet_origin_alias,
        fleet_origin_installation_id=fleet_origin_installation_id,
    )


def test_zero_roots() -> None:
    index = build_agent_tab_index([], _view())
    assert index.catalog == ()
    assert index.signature == ()


def test_one_tab() -> None:
    roster = [_row("a"), _row("b")]
    index = build_agent_tab_index(roster, _view())
    assert [entry.key for entry in index.catalog] == [AgentTabKey.default()]
    assert index.root_count(AgentTabKey.default()) == 2
    assert index.has(AgentTabKey.default())
    assert not index.has(AgentTabKey.named("sase"))
    assert index.root_count(AgentTabKey.named("sase")) == 0
    for row in roster:
        assert index.key_for(row) == AgentTabKey.default()


def test_two_tabs() -> None:
    roster = [_row("a"), _row("b", tab="sase"), _row("c", tab="sase")]
    index = build_agent_tab_index(roster, _view())
    assert {entry.key: entry.root_count for entry in index.catalog} == {
        AgentTabKey.default(): 1,
        AgentTabKey.named("sase"): 2,
    }
    assert index.key_for(roster[0]) == AgentTabKey.default()
    assert index.key_for(roster[1]) == AgentTabKey.named("sase")
    assert index.signature == tuple(
        (entry.key, entry.label, entry.root_count) for entry in index.catalog
    )


def test_many_tabs() -> None:
    roster = [
        _row(f"r{i}", tab=tab) for i, tab in enumerate([None, "b", "a", "c", "b", None])
    ]
    index = build_agent_tab_index(roster, _view())
    assert {entry.key: entry.root_count for entry in index.catalog} == {
        AgentTabKey.default(): 2,
        AgentTabKey.named("a"): 1,
        AgentTabKey.named("b"): 2,
        AgentTabKey.named("c"): 1,
    }
    assert len(index.signature) == 4


def test_starting_roots_count_toward_catalog() -> None:
    roster = [_row("a", status="STARTING"), _row("b", tab="sase", status="STARTING")]
    index = build_agent_tab_index(roster, _view())
    assert index.root_count(AgentTabKey.default()) == 1
    assert index.root_count(AgentTabKey.named("sase")) == 1


def test_children_resolve_to_root_tab() -> None:
    roster = [
        _row("root-1", tab="sase"),
        _row("child-1", parent_timestamp="root-1"),
        _row("root-2"),
    ]
    index = build_agent_tab_index(roster, _view())
    assert index.key_for(roster[1]) == AgentTabKey.named("sase")
    assert index.key_for(roster[2]) == AgentTabKey.default()


def test_session_followup_with_own_tab_resolves() -> None:
    roster = [
        _row("root-1", tab="sase"),
        _row("follow-1", tab="sase", parent_timestamp="root-1"),
    ]
    index = build_agent_tab_index(roster, _view())
    assert index.key_for(roster[1]) == AgentTabKey.named("sase")


def test_rebuilt_row_resolves_by_identity_fallback() -> None:
    roster = [_row("root-1", tab="sase"), _row("root-2")]
    index = build_agent_tab_index(roster, _view())
    rebuilt = _row("root-1", tab="sase")
    assert rebuilt is not roster[0]
    assert rebuilt.identity == roster[0].identity
    assert index.key_for(rebuilt) == AgentTabKey.named("sase")


def test_clan_members_and_container_share_root_tab() -> None:
    members = [
        _row("m1", tab="sase", agent_clan="team", agent_clan_generation="g1"),
        _row("m2", tab="sase", agent_clan="team", agent_clan_generation="g1"),
        _row("solo"),
    ]
    roster = project_clan_tree(members)
    container = next(row for row in roster if row.is_clan_container)
    assert container.agent_tab == "sase"
    index = build_agent_tab_index(roster, _view())
    assert index.key_for(container) == AgentTabKey.named("sase")
    for row in roster:
        if row is not container and row.agent_clan == "team":
            assert index.key_for(row) == AgentTabKey.named("sase")


def test_clan_container_takes_earliest_non_empty_tab() -> None:
    members = [
        _row("m1", agent_clan="team", agent_clan_generation="g1"),
        _row("m2", tab="blog", agent_clan="team", agent_clan_generation="g1"),
    ]
    roster = project_clan_tree(members)
    container = next(row for row in roster if row.is_clan_container)
    assert container.agent_tab == "blog"


def test_machine_mode_on_off_and_auto() -> None:
    view_on = _view(
        machine_mode=True,
        machine_order=(("install-apollo", "apollo"),),
        pinned_by_alias={"apollo": "install-apollo"},
    )
    roster = [
        _row("local-1"),
        _row(
            "remote-1",
            fleet_origin_alias="apollo",
            fleet_origin_installation_id="install-apollo",
        ),
    ]
    index = build_agent_tab_index(roster, view_on)
    assert index.key_for(roster[0]) == AgentTabKey.default()
    assert index.key_for(roster[1]) == AgentTabKey.machine("install-apollo")

    index_off = build_agent_tab_index(roster, _view(token=("test", 2)))
    assert index_off.key_for(roster[1]) == AgentTabKey.default()


def test_provisional_and_authoritative_remote_rows_share_key() -> None:
    view = _view(
        machine_mode=True,
        machine_order=(("install-apollo", "apollo"),),
        pinned_by_alias={"apollo": "install-apollo"},
    )
    roster = [
        _row(
            "dispatch:apollo:op-1",
            fleet_origin_alias="apollo",
            fleet_origin_installation_id=None,
        ),
        _row(
            "remote-1",
            fleet_origin_alias="apollo",
            fleet_origin_installation_id="install-apollo",
        ),
    ]
    index = build_agent_tab_index(roster, view)
    assert index.key_for(roster[0]) == AgentTabKey.machine("install-apollo")
    assert index.key_for(roster[1]) == AgentTabKey.machine("install-apollo")


def test_unknown_installation_id_is_unresolved_with_no_token() -> None:
    view = _view(
        machine_mode=True,
        machine_order=(("install-apollo", "apollo"),),
        pinned_by_alias={"apollo": "install-apollo"},
    )
    roster = [
        _row(
            "dispatch:ghost:op-9",
            fleet_origin_alias="ghost",
            fleet_origin_installation_id=None,
        )
    ]
    index = build_agent_tab_index(roster, view)
    key = AgentTabKey.unresolved_machine("ghost")
    assert index.key_for(roster[0]) == key
    assert index.has(key)
    assert agent_tab_key_token(key) is None


def test_catalog_key_tokens_round_trip() -> None:
    roster = [_row("a"), _row("b", tab="sase")]
    view = _view(
        machine_mode=True,
        machine_order=(("install-apollo", "apollo"),),
        pinned_by_alias={"apollo": "install-apollo"},
    )
    roster.append(
        _row(
            "remote-1",
            fleet_origin_alias="apollo",
            fleet_origin_installation_id="install-apollo",
        )
    )
    index = build_agent_tab_index(roster, view)
    for entry in index.catalog:
        token = agent_tab_key_token(entry.key)
        assert isinstance(token, str)
        assert parse_agent_tab_key_token(token) == entry.key


def test_memo_hit_and_miss() -> None:
    roster = [_row("a"), _row("b", tab="sase")]
    view = _view(token=("test", 1))
    first = cached_agent_tab_index(roster, view)
    assert cached_agent_tab_index(roster, view) is first
    other_token = _view(token=("test", 2))
    assert cached_agent_tab_index(roster, other_token) is not first
    other_roster = [_row("a"), _row("b", tab="sase")]
    assert cached_agent_tab_index(other_roster, view) is not first


def test_memo_survives_roster_identity_reuse() -> None:
    roster = [_row("a")]
    view = _view(token=("test", 9))
    first = cached_agent_tab_index(roster, view)
    assert first.root_count(AgentTabKey.default()) == 1
    assert index_mod._index_cache[(id(roster), len(roster), view.token)][0] is roster
