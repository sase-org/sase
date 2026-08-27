"""Tests for generalized Artifacts relation navigation."""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui._artifact_tab_model import PaneCapability
from sase.ace.tui.actions.navigation._tree import TreeNavigationMixin
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relation_layout import RelationKeymap, RelationRole


@dataclass(frozen=True)
class _Contract:
    id: str
    relations_enabled: bool = True

    def has(self, capability: PaneCapability) -> bool:
        return capability is PaneCapability.RELATIONS and self.relations_enabled


class _Pane:
    def __init__(
        self, *, select_result: bool = True, reveal_result: bool = False
    ) -> None:
        self.origin = ArtifactEntryTarget("beads", ("demo", "phase", "origin"))
        self.select_result = select_result
        self.reveal_result = reveal_result
        self.current = self.origin
        self.selected: ArtifactEntryTarget | None = None
        self.recorded: ArtifactEntryTarget | None = None
        self.revealed: tuple[ArtifactEntryTarget, RelationRole] | None = None

    def selected_entry_target(self) -> ArtifactEntryTarget:
        return self.current

    def record_relation_origin(self, origin: ArtifactEntryTarget) -> None:
        self.recorded = origin

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        self.selected = target
        if self.select_result:
            self.current = target
            return True
        return False

    def request_entry_target(self, target: ArtifactEntryTarget) -> bool:
        return self.select_entry_target(target)

    def reveal_entry_target(
        self,
        target: ArtifactEntryTarget,
        *,
        role: RelationRole,
    ) -> bool:
        self.revealed = (target, role)
        return self.reveal_result


class _App(TreeNavigationMixin):
    def __init__(
        self,
        *,
        keymap: RelationKeymap,
        pane: _Pane | None = None,
        relations_enabled: bool = True,
    ) -> None:
        self.current_tab = "artifacts"
        self.current_artifacts_pane_key = "beads"
        self.active_artifacts_contract = _Contract("beads", relations_enabled)
        self._relation_keymap = keymap
        self._ancestor_mode_active = False
        self._child_mode_active = False
        self._sibling_mode_active = False
        self._child_key_buffer = ""
        self.pane = pane or _Pane()
        self.panes = {"beads": self.pane, "ref:plan": _Pane()}
        self.requested: ArtifactEntryTarget | None = None
        self.synced = 0

    def _artifacts_entry_navigator(self, pane_key: str | None = None) -> _Pane:
        return self.panes[pane_key or self.current_artifacts_pane_key]

    def _request_artifacts_entry(self, target: ArtifactEntryTarget) -> bool:
        self.requested = target
        self.current_artifacts_pane_key = target.pane_id
        return self._artifacts_entry_navigator(target.pane_id).request_entry_target(
            target
        )

    def _sync_active_artifacts_entry_state(self) -> None:
        self.synced += 1


def test_ancestor_mode_selects_same_pane_target_and_records_origin() -> None:
    target = ArtifactEntryTarget("beads", ("demo", "epic", "parent"))
    app = _App(keymap=RelationKeymap(ancestors=(("<", target),)))

    app.action_start_ancestor_mode()

    assert app.pane.selected == target
    assert app.pane.recorded == app.pane.origin
    assert app.synced == 1


def test_relation_target_cross_pane_routes_request() -> None:
    target = ArtifactEntryTarget("ref:plan", ("demo", "active", "plan.md"))
    app = _App(keymap=RelationKeymap())

    app._navigate_to_relation_target(target, role=RelationRole.LINK)

    assert app.requested == target
    assert app.pane.recorded == app.pane.origin


def test_filtered_same_pane_target_reaches_reveal_hook() -> None:
    target = ArtifactEntryTarget("beads", ("demo", "phase", "hidden"))
    pane = _Pane(select_result=False, reveal_result=True)
    app = _App(keymap=RelationKeymap(), pane=pane)

    app._navigate_to_relation_target(target, role=RelationRole.DESCENDANT)

    assert pane.selected == target
    assert pane.revealed == (target, RelationRole.DESCENDANT)


def test_relation_mode_noops_when_capability_is_off() -> None:
    target = ArtifactEntryTarget("beads", ("demo", "epic", "parent"))
    app = _App(
        keymap=RelationKeymap(ancestors=(("<", target),)),
        relations_enabled=False,
    )

    app.action_start_ancestor_mode()

    assert app.pane.selected is None
