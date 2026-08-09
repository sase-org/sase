"""Tests for discovering and navigating agent neighbors."""

from __future__ import annotations

from sase.ace.tui.actions.navigation._tree import TreeNavigationMixin
from sase.ace.tui.modals import AgentNeighborModal

from ._agent_neighbor_navigation_helpers import NeighborApp, make_agent


class _PatchSiblingApp(TreeNavigationMixin):
    def __init__(self) -> None:
        self.current_tab = "patches"
        self.patches = [object()]
        self._sibling_keys = {"~": "target"}
        self.navigated: list[tuple[str, bool, bool]] = []

    def _navigate_to_patch(
        self,
        target_name: str,
        is_ancestor: bool,
        is_sibling: bool = False,
    ) -> None:
        self.navigated.append((target_name, is_ancestor, is_sibling))


def test_patch_sibling_navigation_still_direct_jumps() -> None:
    app = _PatchSiblingApp()

    app.action_start_sibling_mode()

    assert app.navigated == [("target", False, True)]


def test_agent_neighbor_navigation_noops_without_visible_neighbor() -> None:
    app = NeighborApp([make_agent("foo.plan"), make_agent("bar.plan")])
    app._entry_jump_agents_anchor_stack = [("agent", 1, None)]

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app.acknowledged == []
    assert app.highlight_refreshes == 0
    assert app._entry_jump_agents_anchor_stack == [("agent", 1, None)]


def test_agent_neighbor_navigation_direct_jumps_to_single_neighbor() -> None:
    agents = [make_agent("foo.plan"), make_agent("foo.code")]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert app.current_attempt_number is None
    assert app._current_group_key is None
    assert app.armed_departures == [agents[0]]
    assert app.acknowledged == [agents[1]]
    assert app.highlight_refreshes == 1
    assert app.info_updates == 1
    assert app.detail_updates == 1
    assert app._agent_detail_debouncer.scheduled == 1
    assert app.refilter_calls == 0
    assert app.display_refreshes == []


def test_agent_neighbor_navigation_back_jump_restores_origin() -> None:
    agents = [make_agent("foo.plan"), make_agent("foo.code")]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()
    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("apostrophe")

    assert handled is True
    assert app.current_idx == 0
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 1


def test_agent_neighbor_navigation_fast_back_jump_restores_origin_without_hints() -> (
    None
):
    agents = [make_agent("foo.plan"), make_agent("foo.code")]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()
    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_agent_neighbor_navigation_opens_modal_for_dotless_root_descendants() -> None:
    agents = [make_agent("foo"), make_agent("foo.bar"), make_agent("foo.baz")]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [choice.group for choice in modal._choices] == [
        "descendant",
        "descendant",
    ]
    assert [choice.agent_name for choice in modal._choices] == ["foo.bar", "foo.baz"]


def test_agent_neighbor_navigation_fast_jumps_to_single_visible_descendant() -> None:
    agents = [make_agent("foo.bar"), make_agent("foo.bar.baz")]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.pushed_screens == []
    assert app.acknowledged == [agents[1]]


def test_agent_neighbor_navigation_fast_jumps_to_single_visible_ancestor() -> None:
    agents = [
        make_agent("foo", status="DONE"),
        make_agent("foo.bar", status="RUNNING"),
    ]
    app = NeighborApp(agents, current_idx=1)

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app._entry_jump_agents_anchor_stack == [("agent", 1, None)]
    assert app.armed_departures == [agents[1]]
    assert app.acknowledged == [agents[0]]


def test_agent_neighbor_navigation_opens_modal_with_ancestors_first() -> None:
    agents = [
        make_agent("foo"),
        make_agent("foo.bar"),
        make_agent("foo.bar.baz"),
        make_agent("foo.qux"),
    ]
    app = NeighborApp(agents, current_idx=1)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [choice.group for choice in modal._choices] == [
        "ancestor",
        "descendant",
        "neighbor",
    ]
    assert [choice.global_idx for choice in modal._choices] == [0, 2, 3]
    assert modal._title_text() == (
        "Neighbors of foo.bar  [1 ancestor - 1 descendant - 1 neighbor]"
    )
    assert [
        str(option.id) for option in modal._create_options() if option.disabled
    ] == [
        "header-ancestors",
        "header-descendants",
        "header-neighbors-0",
    ]

    app.pushed_callbacks[0](0)

    assert app.current_idx == 0
    assert app.acknowledged == [agents[0]]


def test_agent_neighbor_modal_matches_shared_lane_projection() -> None:
    agents = [
        make_agent("A"),
        make_agent("A.B"),
        make_agent("A.B.C"),
        make_agent("A.B.C.child"),
        make_agent("A.B.peer"),
        make_agent("A.other"),
    ]
    dismissed = make_agent("A.B.C.dismissed", status="DONE")
    app = NeighborApp(agents, current_idx=2)
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    app._dismiss_revive_epoch += 1

    projection = app.lane_neighbor_projection_for(agents[2])
    assert projection is not None

    app.action_start_sibling_mode()

    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [
        (
            choice.agent_name,
            choice.group,
            choice.hood,
            choice.dismissed,
        )
        for choice in modal._choices
    ] == [
        (
            row.agent.presented_agent_name or row.agent.display_name,
            row.relation,
            row.hood,
            row.is_dismissed,
        )
        for row in projection.rows
    ]


def test_selected_agent_neighbor_count_includes_ancestors() -> None:
    agents = [make_agent("foo"), make_agent("foo.bar")]
    app = NeighborApp(agents, current_idx=1)

    assert app._selected_agent_neighbor_count(agents[1]) == 1


def test_agent_neighbor_navigation_jumps_within_a_sub_hood() -> None:
    agents = [make_agent("foo.bar.baz"), make_agent("foo.bar.qux")]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.armed_departures == [agents[0]]
    assert app.acknowledged == [agents[1]]


def test_agent_neighbor_navigation_opens_modal_for_multiple_neighbors() -> None:
    agents = [
        make_agent("foo.plan"),
        make_agent("foo.code"),
        make_agent("foo.review"),
    ]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == []
    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [choice.global_idx for choice in modal._choices] == [1, 2]
    assert [choice.agent_name for choice in modal._choices] == [
        "foo.code",
        "foo.review",
    ]
    assert [choice.hood for choice in modal._choices] == ["foo", "foo"]

    app.pushed_callbacks[0](None)

    assert app.current_idx == 0
    assert app._entry_jump_agents_anchor_stack == []
    assert app.acknowledged == []

    app.pushed_callbacks[0](1)

    assert app.current_idx == 2
    assert app._entry_jump_agents_anchor_stack == [("agent", 0, None)]
    assert app.acknowledged == [agents[2]]


def test_agent_neighbor_navigation_groups_nephews_and_cousins() -> None:
    agents = [
        make_agent("A.B.C"),
        make_agent("a.b.d.e"),
        make_agent("a.z.1"),
        make_agent("unrelated.agent"),
    ]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()

    assert len(app.pushed_screens) == 1
    modal = app.pushed_screens[0]
    assert isinstance(modal, AgentNeighborModal)
    assert [choice.agent_name for choice in modal._choices] == [
        "a.b.d.e",
        "a.z.1",
    ]
    assert [choice.hood for choice in modal._choices] == ["A.B", "A"]
    assert [
        option.prompt.plain for option in modal._create_options() if option.disabled
    ] == [
        "-- Neighbors - A.B hood (1) --------------------",
        "-- Neighbors - A hood (1) --------------------",
    ]


def test_agent_neighbor_navigation_direct_jumps_to_single_nephew() -> None:
    agents = [make_agent("foo.bar"), make_agent("foo.baz.qux")]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.pushed_screens == []
    assert app.acknowledged == [agents[1]]


def test_agent_neighbor_navigation_top_level_family_mates_are_unrelated() -> None:
    app = NeighborApp([make_agent("fam--plan"), make_agent("fam--fix")])

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
    assert app.acknowledged == []


def test_agent_neighbor_navigation_direct_jumps_down_family_chain() -> None:
    agents = [make_agent("fam--plan"), make_agent("fam--plan--check")]
    app = NeighborApp(agents)

    app.action_start_sibling_mode()

    assert app.current_idx == 1
    assert app.pushed_screens == []
    assert app.acknowledged == [agents[1]]
