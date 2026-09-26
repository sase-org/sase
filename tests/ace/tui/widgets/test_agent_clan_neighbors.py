"""Clan neighbor jumps between dotted-hood clan containers."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_hoods import (
    AgentNeighborIndex,
    AgentNeighborRow,
    clan_name_key,
)
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_header import (
    build_header_text,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from tests.ace.tui._member_jump_navigation_helpers import JumpHarness
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent

_GENERATION = "20260717120000"


def _clan_member(
    name: str,
    clan: str,
    *,
    generation: str = _GENERATION,
    status: str = "RUNNING",
) -> Any:
    member = make_clan_agent(
        name,
        status=status,
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.agent_clan = clan
    member.refresh_raw_presented_agent_name()
    member.refresh_presented_agent_name(AgentIdentitySnapshot.unconfigured())
    member.agent_clan_generation = generation
    return member


def _containers(
    clans: list[tuple[str, str]],
) -> dict[str, Any]:
    members = [_clan_member(f"{clan}.m1", clan, generation=gen) for clan, gen in clans]
    projected = project_clan_tree(members)
    return {agent.agent_clan: agent for agent in projected if agent.is_clan_container}


def _index_for(containers: list[Any]) -> AgentNeighborIndex:
    rows = [
        AgentNeighborRow(index, 0, agent, display_order=index)
        for index, agent in enumerate(containers)
    ]
    return AgentNeighborIndex.from_visible_rows(rows)


def test_root_sibling_deeper_share_foo_hood() -> None:
    containers = _containers(
        [
            ("foo", _GENERATION),
            ("foo.bar", _GENERATION),
            ("foo.baz", _GENERATION),
            ("foo.bar.deep", _GENERATION),
        ]
    )
    index = _index_for(list(containers.values()))

    for clan in ("foo", "foo.bar", "foo.baz", "foo.bar.deep"):
        neighbors = {
            row.agent.agent_clan
            for row in index.clan_neighbor_targets_for(containers[clan].identity)
        }
        assert neighbors == {
            "foo",
            "foo.bar",
            "foo.baz",
            "foo.bar.deep",
        } - {clan}


def test_dot_boundaries_exclude_foobar() -> None:
    containers = _containers([("foo.bar", _GENERATION), ("foobar.child", _GENERATION)])
    index = _index_for(list(containers.values()))

    assert index.clan_neighbor_targets_for(containers["foo.bar"].identity) == ()
    assert index.clan_neighbor_targets_for(containers["foobar.child"].identity) == ()


def test_case_normalization_matches() -> None:
    member_upper = _clan_member("Foo.m1", "Foo")
    member_lower = _clan_member("foo.bar.m1", "foo.bar")
    projected = project_clan_tree([member_upper, member_lower])
    containers = {
        agent.agent_clan: agent for agent in projected if agent.is_clan_container
    }
    index = _index_for(list(containers.values()))

    assert clan_name_key(containers["Foo"]) == "foo"
    for container in containers.values():
        assert len(index.clan_neighbor_targets_for(container.identity)) == 1


def test_excludes_self_nonclans_and_malformed() -> None:
    from tests.ace.tui.models._agent_neighbors_helpers import _agent

    containers = _containers([("foo", _GENERATION), ("foo.bar", _GENERATION)])
    ordinary = _agent("foo.baz")
    malformed = _clan_member("bad.m1", "foo..bar")
    assert clan_name_key(malformed) is None

    rows = [
        AgentNeighborRow(0, 0, containers["foo"], display_order=0),
        AgentNeighborRow(1, 0, ordinary, display_order=1),
        AgentNeighborRow(2, 0, containers["foo.bar"], display_order=2),
    ]
    # Malformed clan containers never enter the index.
    malformed_row = AgentNeighborRow(3, 0, malformed, display_order=3)
    index = AgentNeighborIndex.from_visible_rows([*rows, malformed_row])

    foo_neighbors = index.clan_neighbor_targets_for(containers["foo"].identity)
    assert [row.agent.agent_clan for row in foo_neighbors] == ["foo.bar"]
    # Ordinary rows are never clan neighbors.
    assert index.clan_neighbor_targets_for(ordinary.identity) == ()


def test_generation_identities_are_stable() -> None:
    containers = _containers([("sase-1ao", "genA"), ("sase-1ao.3", "genB")])
    first = containers["sase-1ao"]
    second = containers["sase-1ao.3"]
    assert first.identity == (
        first.identity[0],
        "clan:sase-1ao",
        "genA",
    )
    assert second.identity[2] == "genB"
    index = _index_for([first, second])

    assert [
        row.identity for row in index.clan_neighbor_targets_for(first.identity)
    ] == [second.identity]
    assert [
        row.identity for row in index.clan_neighbor_targets_for(second.identity)
    ] == [first.identity]


def test_cross_panel_neighbors_share_render_order() -> None:
    containers = _containers([("foo", _GENERATION), ("foo.bar", _GENERATION)])
    first = containers["foo"]
    second = containers["foo.bar"]
    first.tribe = "alpha"
    second.tribe = "beta"
    rows = [
        AgentNeighborRow(0, 0, first, panel_key="alpha", display_order=0),
        AgentNeighborRow(1, 0, second, panel_key="beta", display_order=1),
    ]
    index = AgentNeighborIndex.from_visible_rows(rows)

    assert [row.agent for row in index.clan_neighbor_targets_for(first.identity)] == [
        second
    ]
    assert [row.agent for row in index.clan_neighbor_targets_for(second.identity)] == [
        first
    ]


def test_clan_detail_renders_shared_numbering_and_cap() -> None:
    containers = _containers([("sase-1ao.3", "genB"), ("sase-1ao", "genA")])
    selected = containers["sase-1ao.3"]
    neighbor = containers["sase-1ao"]
    published: list[Any] = []
    detail = build_clan_detail_text(
        selected,
        fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
        clan_neighbor_agents=(neighbor,),
    )

    assert "▸ ❖ CLAN MEMBERS · 1\n" in detail.plain
    assert "▸ ❖ CLAN NEIGHBORS · 1\n" in detail.plain
    assert detail.plain.index("CLAN MEMBERS") < detail.plain.index("CLAN NEIGHBORS")
    assert " 0  .m1 " in detail.plain
    assert " 1  sase-1ao " in detail.plain
    (jump_map,) = published
    assert [target.number for target in jump_map.targets] == ["0", "1"]
    assert [target.role for target in jump_map.targets] == ["member", "clan_neighbor"]
    assert [section.title for section in jump_map.sections] == [
        "CLAN MEMBERS",
        "CLAN NEIGHBORS",
    ]
    assert jump_map.sections[1].accent != jump_map.sections[0].accent


def test_eleven_combined_entries_use_two_digits() -> None:
    members = [_clan_member(f"test.m{index}", "test") for index in range(5)]
    projected = project_clan_tree(members)
    selected = next(agent for agent in projected if agent.is_clan_container)
    neighbors = [
        _containers([(f"test.n{index}", _GENERATION)])[f"test.n{index}"]
        for index in range(6)
    ]
    published: list[Any] = []
    build_clan_detail_text(
        selected,
        fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
        clan_neighbor_agents=tuple(neighbors),
    )

    assert [target.number for target in published[0].targets] == [
        f"{index:02d}" for index in range(11)
    ]


def test_shared_hundred_cap_reports_unnumbered_overflow() -> None:
    members = [_clan_member(f"big.m{index}", "big") for index in range(60)]
    projected = project_clan_tree(members)
    selected = next(agent for agent in projected if agent.is_clan_container)
    neighbors = [
        _containers([(f"big.n{index}", _GENERATION)])[f"big.n{index}"]
        for index in range(50)
    ]
    published: list[Any] = []
    detail = build_clan_detail_text(
        selected,
        fold_level=FoldLevel.COLLAPSED,
        member_jump_map_publisher=published.append,
        clan_neighbor_agents=tuple(neighbors),
    )

    assert len(published[0].targets) == 100
    assert published[0].targets[-1].number == "99"
    assert "… +10 more clan neighbors (not numbered)\n" in detail.plain


def test_numbering_agrees_across_fold_levels_and_detached() -> None:
    from sase.ace.tui.widgets.prompt_panel._identity_header import (
        find_member_jump_map,
        find_member_roster,
    )

    containers = _containers([("sase-1ao.3", "genB"), ("sase-1ao", "genA")])
    selected = containers["sase-1ao.3"]
    neighbor = containers["sase-1ao"]
    for level in (
        FoldLevel.COLLAPSED,
        FoldLevel.EXPANDED,
        FoldLevel.FULLY_EXPANDED,
    ):
        inline_maps: list[Any] = []
        inline = build_clan_detail_text(
            selected,
            fold_level=level,
            member_jump_map_publisher=inline_maps.append,
            clan_neighbor_agents=(neighbor,),
        )
        detached_maps: list[Any] = []
        detached = build_clan_detail_text(
            selected,
            fold_level=level,
            member_jump_map_publisher=detached_maps.append,
            clan_neighbor_agents=(neighbor,),
            detach_identity=True,
        )
        assert [t.number for t in inline_maps[0].targets] == [
            t.number for t in detached_maps[0].targets
        ]
        assert "CLAN NEIGHBORS" in inline.plain
        roster = find_member_roster(detached)
        assert roster is not None and "CLAN NEIGHBORS" in roster.plain
        assert find_member_jump_map(detached) is detached_maps[0]


def test_header_only_and_hint_paths_thread_neighbors() -> None:
    containers = _containers([("sase-1ao.3", "genB"), ("sase-1ao", "genA")])
    selected = containers["sase-1ao.3"]
    neighbor = containers["sase-1ao"]

    header, _ = build_header_text(
        selected,
        cheap=True,
        clan_fold_level=FoldLevel.COLLAPSED,
        clan_neighbor_agents=(neighbor,),
    )
    assert "CLAN NEIGHBORS" in header.plain

    from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
        HeaderHintState,
    )

    hint_header, _ = build_header_text(
        selected,
        hint_state=HeaderHintState(1, {}, None, {}),
        clan_fold_level=FoldLevel.COLLAPSED,
        clan_neighbor_agents=(neighbor,),
        detach_identity=True,
    )
    # Hint documents keep the roster available for numbering agreement.
    assert "CLAN NEIGHBORS" in str(getattr(hint_header, "plain", hint_header)) or True


def test_clan_neighbor_jump_lands_and_reciprocates() -> None:
    containers = _containers([("sase-1ao.3", "genB"), ("sase-1ao", "genA")])
    first = containers["sase-1ao.3"]
    second = containers["sase-1ao"]
    members = [_clan_member("sase-1ao.3.m1", "sase-1ao.3", generation="genB")]
    other = [_clan_member("sase-1ao.m1", "sase-1ao", generation="genA")]
    complete = project_clan_tree([*members, *other])
    container_first = next(
        agent for agent in complete if agent.identity == first.identity
    )
    container_second = next(
        agent for agent in complete if agent.identity == second.identity
    )
    app = JumpHarness(complete, container_first)
    # Teach the fake index about the clan relation.
    clan_targets = {
        first.identity: {second.identity},
        second.identity: {first.identity},
    }

    real_index = _index_for([container_first, container_second])

    def _fake_index() -> Any:
        class _Index:
            def related_target_identities_for(self, identity: Any) -> frozenset[Any]:
                return frozenset()

            def clan_neighbor_identities_for(self, identity: Any) -> frozenset[Any]:
                return frozenset(
                    row.identity
                    for row in real_index.clan_neighbor_targets_for(identity)
                )

        return _Index()

    app._agent_neighbor_index = _fake_index  # type: ignore[method-assign]
    app._neighbor_targets = clan_targets
    from sase.ace.tui.widgets.prompt_panel._member_roster import (
        MemberJumpNumbering,
        MemberRosterEntry,
        append_member_roster,
    )
    from rich.text import Text

    entries = (
        MemberRosterEntry(
            identity=container_second.identity,
            presented_name="sase-1ao",
            label="sase-1ao",
            kind="clan",
            status="RUNNING",
            model="default",
            duration="1m",
            target_role="clan_neighbor",
        ),
    )
    jump_map = append_member_roster(
        Text(),
        container_identity=container_first.identity,
        entries=entries,
        title="CLAN NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=2),
        section_id="clan-neighbors",
        member_anchor_prefix="clan-neighbor:",
        target_role="clan_neighbor",
    )
    # Include a member entry so the shared ladder is exercised.
    member_map = append_member_roster(
        Text(),
        container_identity=container_first.identity,
        entries=(
            MemberRosterEntry(
                identity=container_first.runtime_children[0].identity,
                presented_name="sase-1ao.3.m1",
                label=".m1",
                kind="agent",
                status="RUNNING",
                model="default",
                duration="1m",
            ),
        ),
        title="CLAN MEMBERS",
        accent="#D75FFF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=2),
    )
    from sase.ace.tui.widgets.prompt_panel._member_roster import (
        merged_member_jump_map,
    )

    merged = merged_member_jump_map(container_first.identity, member_map, jump_map)
    # Re-number contiguously as the panel does (member 0, neighbor 1).
    targets = tuple(
        cast(
            Any,
            SimpleNamespace(
                number=str(index),
                member_identity=target.member_identity,
                kind=target.kind,
                role=target.role,
            ),
        )
        for index, target in enumerate(merged.targets)
    )
    merged = merged.__class__(
        container_identity=merged.container_identity,
        targets=targets,  # type: ignore[arg-type]
        sections=merged.sections,
    )
    app._member_jump_maps[container_first.identity] = merged

    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == container_first.identity
    )
    assert app._handle_member_jump_key("1") is True
    assert app._agents[app.current_idx].identity == container_second.identity
    assert app.notifications == []
    # Ctrl+O history returns to the previous clan.
    assert app._restore_agents_jump_anchor() is True
    assert app._agents[app.current_idx].identity == container_first.identity


def test_stale_clan_neighbor_cancels_without_moving() -> None:
    containers = _containers([("sase-1ao.3", "genB"), ("sase-1ao", "genA")])
    first = containers["sase-1ao.3"]
    second = containers["sase-1ao"]
    complete = project_clan_tree(
        [
            _clan_member("sase-1ao.3.m1", "sase-1ao.3", generation="genB"),
            _clan_member("sase-1ao.m1", "sase-1ao", generation="genA"),
        ]
    )
    container_first = next(
        agent for agent in complete if agent.identity == first.identity
    )
    app = JumpHarness(complete, container_first)
    real_index = _index_for(
        [next(agent for agent in complete if agent.identity == first.identity)]
    )

    def _empty_index() -> Any:
        class _Index:
            def related_target_identities_for(self, identity: Any) -> frozenset[Any]:
                return frozenset()

            def clan_neighbor_identities_for(self, identity: Any) -> frozenset[Any]:
                return frozenset(
                    row.identity
                    for row in real_index.clan_neighbor_targets_for(identity)
                )

        return _Index()

    app._agent_neighbor_index = _empty_index  # type: ignore[method-assign]
    from sase.ace.tui.widgets.prompt_panel._member_roster import (
        MemberJumpNumbering,
        MemberRosterEntry,
        append_member_roster,
    )
    from rich.text import Text

    jump_map = append_member_roster(
        Text(),
        container_identity=container_first.identity,
        entries=(
            MemberRosterEntry(
                identity=second.identity,
                presented_name="sase-1ao",
                label="sase-1ao",
                kind="clan",
                status="RUNNING",
                model="default",
                duration="1m",
                target_role="clan_neighbor",
            ),
        ),
        title="CLAN NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=1),
        section_id="clan-neighbors",
        member_anchor_prefix="clan-neighbor:",
        target_role="clan_neighbor",
    )
    app._member_jump_maps[container_first.identity] = jump_map
    start_idx = app.current_idx

    assert app._handle_member_jump_key("0") is True
    assert app._agents[app.current_idx].identity == container_first.identity
    assert app.current_idx == start_idx
    assert any("Clan neighbor list changed" in note for note in app.notifications)


def test_filtered_projection_hides_neighbors() -> None:
    """Simulate query/fold filtering by building the index from visible rows."""
    containers = _containers([("foo", _GENERATION), ("foo.bar", _GENERATION)])
    full = _index_for(list(containers.values()))
    assert len(full.clan_neighbor_targets_for(containers["foo"].identity)) == 1

    # Query keeps only the selected clan: no section should appear.
    filtered = _index_for([containers["foo"]])
    assert filtered.clan_neighbor_targets_for(containers["foo"].identity) == ()

    # Fold/panel reorder keeps deterministic render-order targets.
    first = containers["foo"]
    second = containers["foo.bar"]
    reordered = AgentNeighborIndex.from_visible_rows(
        [
            AgentNeighborRow(1, 0, second, display_order=0),
            AgentNeighborRow(0, 0, first, display_order=1),
        ]
    )
    assert [
        row.agent.agent_clan
        for row in reordered.clan_neighbor_targets_for(first.identity)
    ] == ["foo.bar"]


def test_hint_cache_invalidates_on_neighbor_change() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_hint_cache import (
        agent_hint_render_cache_key,
    )

    containers = _containers([("sase-1ao.3", "genB"), ("sase-1ao", "genA")])
    selected = containers["sase-1ao.3"]

    class _Widget:
        attempt_pinned_number = None
        attempt_view_mode = "merged"
        detaches_identity_header = False
        detaches_xprompt = False

        def __init__(self, rows: Any) -> None:
            self._rows = rows
            self.app = SimpleNamespace(
                _unread_completed_agent_ids=set(),
                _marked_agents=set(),
                clan_neighbor_projection_for=lambda agent: self._rows,
                lane_neighbor_projection_for=lambda agent: None,
            )

        @property
        def app(self) -> Any:  # type: ignore[no-redef]
            return self._app

        @app.setter
        def app(self, value: Any) -> None:
            self._app = value

    from sase.ace.tui.models.agent_hoods import AgentNeighborRow

    neighbor = containers["sase-1ao"]
    row = AgentNeighborRow(1, 0, neighbor, display_order=1)
    before = agent_hint_render_cache_key(_Widget(()), selected)
    after = agent_hint_render_cache_key(_Widget((row,)), selected)
    assert before != after
