"""Tests for sibling navigation mode scoping and the neighbor index."""

from __future__ import annotations

from sase.ace.tui.actions.navigation._tree import TreeNavigationMixin
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import RelationKeymap

from ._agent_neighbor_navigation_helpers import NeighborApp, make_agent


class _PatchSiblingApp(TreeNavigationMixin):
    def __init__(self) -> None:
        self.current_tab = "patches"
        self.target = ArtifactEntryTarget("patches", ("demo", "target"))
        self.navigator = _PatchNavigator()
        self._relation_keymap = RelationKeymap(siblings=(("~", self.target),))

    def _artifacts_entry_navigator(self, pane_key: str | None = None) -> object:
        assert pane_key == "patches"
        return self.navigator


class _PatchNavigator:
    def __init__(self) -> None:
        self.origin = ArtifactEntryTarget("patches", ("demo", "origin"))
        self.selected: ArtifactEntryTarget | None = None

    def selected_entry_target(self) -> ArtifactEntryTarget:
        return self.origin

    def record_relation_origin(self, origin: ArtifactEntryTarget) -> None:
        assert origin == self.origin

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        self.selected = target
        return True

    def reveal_entry_target(self, target: ArtifactEntryTarget, *, role: object) -> bool:
        del target, role
        return False


def test_patch_sibling_navigation_still_direct_jumps() -> None:
    app = _PatchSiblingApp()

    app.action_start_sibling_mode()

    assert app.navigator.selected == app.target


def test_selected_agent_neighbor_count_includes_ancestors() -> None:
    agents = [make_agent("foo"), make_agent("foo.bar")]
    app = NeighborApp(agents, current_idx=1)

    assert app._selected_agent_neighbor_count(agents[1]) == 1


def test_agents_sibling_mode_is_noop_with_neighbors() -> None:
    """`~` on the Agents tab pushes no screen and keeps the selection."""
    agents = [make_agent("foo.plan"), make_agent("foo.code")]
    app = NeighborApp(agents)

    assert app._selected_agent_neighbor_count(agents[0]) > 0

    app.action_start_sibling_mode()

    assert app.current_idx == 0
    assert app.pushed_screens == []
