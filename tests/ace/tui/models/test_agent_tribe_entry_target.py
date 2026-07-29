"""Pure panel-entry destination projection tests."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from sase.ace.tui.actions.agents._panel_entry_target import (
    PanelSelectionStop,
    resolve_panel_entry_stop,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import (
    tribe_entry_target_for_group,
    tribe_entry_target_for_row,
)


def _agent(
    name: str,
    *,
    suffix: str,
    agent_type: AgentType = AgentType.RUNNING,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name,
        project_file="/tmp/demo.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix=suffix,
        agent_name=name,
    )


def test_top_level_row_resolves_to_its_own_roster_unit() -> None:
    row = _agent("solo", suffix="solo")

    target = tribe_entry_target_for_row([row], row, key_label="x")

    assert target.unit_identity == row.identity
    assert target.label == "solo"
    assert target.kind == "unit"
    assert target.key_label == "x"


def test_family_member_resolves_to_family_roster_unit() -> None:
    root = _agent("build--plan", suffix="root")
    root.agent_family = "build"
    root.agent_family_role = "root"
    root.role_suffix = "--plan"
    root.plan_chain_root = True
    root.refresh_raw_presented_agent_name()
    child = _agent("build--code", suffix="child")
    child.agent_family = "build"
    child.agent_family_role = "code"
    child.role_suffix = "--code"
    child.parent_timestamp = root.raw_suffix
    child.refresh_raw_presented_agent_name()

    target = tribe_entry_target_for_row([root, child], child)

    assert target.unit_identity == root.identity
    assert target.label == "build › --code"
    assert target.kind == "member"


def test_clan_member_resolves_to_clan_container() -> None:
    member = _agent("research.worker", suffix="worker")
    member.agent_clan = "research"
    member.agent_clan_generation = "gen-1"
    projected = project_clan_tree([member])
    container = projected[0]

    target = tribe_entry_target_for_row(projected, projected[1])

    assert target.unit_identity == container.identity
    assert target.label == "research › .worker"
    assert target.kind == "member"


def test_workflow_child_resolves_to_workflow_root() -> None:
    root = _agent("release", suffix="root", agent_type=AgentType.WORKFLOW)
    child = _agent("release.test", suffix="child", agent_type=AgentType.WORKFLOW)
    child.parent_workflow = "release"
    child.tree_parent_key = root.raw_suffix
    child.tree_depth = 1

    target = tribe_entry_target_for_row([root, child], child)

    assert target.unit_identity == root.identity
    assert target.label == "release › .test"
    assert target.kind == "member"


def test_row_without_a_presented_anchor_keeps_label_but_has_no_cursor_unit() -> None:
    child = _agent("orphan.step", suffix="child", agent_type=AgentType.WORKFLOW)
    child.parent_workflow = "missing"
    child.tree_parent_key = "missing"
    child.tree_depth = 1

    target = tribe_entry_target_for_row([child], child)

    assert target.unit_identity is None
    assert target.label == "orphan.step"
    assert target.kind == "member"


def test_group_target_is_explicitly_labeled_as_a_group() -> None:
    target = tribe_entry_target_for_group("Done", key_label="<enter>")

    assert target.unit_identity is None
    assert target.label == "Done (group)"
    assert target.kind == "group"
    assert target.key_label == "<enter>"


@dataclass
class _EntryOwner:
    stops: list[PanelSelectionStop]
    remembered: PanelSelectionStop | None = None
    calls: list[bool] = field(default_factory=list)

    @property
    def _panel_selection_memory(
        self,
    ) -> dict[str, PanelSelectionStop]:
        return {"panel": self.remembered} if self.remembered is not None else {}

    def _panel_navigation_stops(
        self,
        *,
        include_panel_focus: bool = False,
    ) -> list[PanelSelectionStop]:
        self.calls.append(include_panel_focus)
        return self.stops


@pytest.mark.parametrize(
    ("stops", "remembered", "expected"),
    [
        (
            [("agent", 1), ("agent", 2)],
            ("agent", 2),
            ("agent", 2),
        ),
        (
            [("agent", 1), ("banner", ("Done",))],
            ("agent", 9),
            ("agent", 1),
        ),
        (
            [("banner", ("Done",))],
            None,
            ("banner", ("Done",)),
        ),
        ([], ("agent", 2), None),
    ],
)
def test_shared_resolver_uses_remembered_or_first_stop(
    stops: list[PanelSelectionStop],
    remembered: PanelSelectionStop | None,
    expected: PanelSelectionStop | None,
) -> None:
    owner = _EntryOwner(stops=stops, remembered=remembered)

    assert resolve_panel_entry_stop(owner, "panel") == expected
    assert owner.calls == [True]


def test_shared_resolver_preserves_legacy_no_keyword_fallback() -> None:
    class _LegacyOwner:
        _panel_selection_memory = {"panel": ("agent", 2)}

        def _panel_navigation_stops(self) -> list[PanelSelectionStop]:
            return [("agent", 1), ("agent", 2)]

    assert resolve_panel_entry_stop(_LegacyOwner(), "panel") == ("agent", 2)
