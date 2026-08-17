"""Agents-tab tree projection: containers, depths, generations, and anchors."""

from __future__ import annotations

from sase.ace.tui.models._agent_tree import (
    agent_fold_key,
    agent_parent_fold_key,
    presentation_anchor,
    presentation_anchor_lookup,
    project_clan_tree,
    _tree_parent,
    tree_parent_lookup,
)
from sase.ace.tui.models.agent_groups import build_agent_tree

from ._agent_tree_helpers import _GENERATION, _agent


def test_project_clan_tree_inserts_container_and_three_depths() -> None:
    family = _agent("research.family", "family", tribe="epic")
    family_member = _agent(
        "research.family--code",
        "family-code",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
        tribe="review",
    )
    solo = _agent("research.solo", "solo", status="DONE", tribe="review")

    projected = project_clan_tree([family, family_member, solo])

    container = projected[0]
    assert container.is_clan_container is True
    assert container.display_name == "research"
    assert container.agent_clan_generation == _GENERATION
    assert container.clan_tribes == ("epic", "review")
    assert container.runtime_children == [family, solo]
    assert projected == [container, family, family_member, solo]
    assert [row.tree_depth for row in projected] == [0, 1, 2, 1]
    clan_key = agent_fold_key(container)
    assert family.tree_parent_key == clan_key
    assert solo.tree_parent_key == clan_key
    assert family_member.tree_parent_key == family.raw_suffix
    assert agent_fold_key(family) == family.raw_suffix
    assert agent_parent_fold_key(family) == clan_key
    assert agent_parent_fold_key(family_member) == family.raw_suffix

    lookup = tree_parent_lookup(projected)
    assert _tree_parent(family_member, lookup) is family
    assert _tree_parent(family, lookup) is container
    anchors = presentation_anchor_lookup(projected, lookup)
    assert [anchors[id(row)] for row in projected] == [container] * 4


def test_presentation_anchor_handles_orphans_and_cycles_deterministically() -> None:
    orphan = _agent("orphan", "orphan", clan=None, generation=None)
    orphan.tree_parent_key = "missing"
    orphan.tree_depth = 2
    shallow = _agent("cycle.shallow", "shallow", clan=None, generation=None)
    deep = _agent("cycle.deep", "deep", clan=None, generation=None)
    shallow.tree_parent_key = deep.raw_suffix
    shallow.tree_depth = 1
    deep.tree_parent_key = shallow.raw_suffix
    deep.tree_depth = 2
    rows = [deep, orphan, shallow]

    parent_lookup = tree_parent_lookup(rows)
    anchors = presentation_anchor_lookup(rows, parent_lookup)

    assert anchors[id(orphan)] is orphan
    assert anchors[id(shallow)] is shallow
    assert anchors[id(deep)] is shallow
    assert presentation_anchor(orphan, parent_lookup) is orphan
    assert presentation_anchor(shallow, parent_lookup) is shallow
    assert presentation_anchor(deep, parent_lookup) is shallow


def test_project_clan_tree_keeps_generations_separate() -> None:
    old = _agent("research.old", "old", generation="old")
    new = _agent("research.new", "new", generation="new")

    projected = project_clan_tree([new, old])

    containers = [row for row in projected if row.is_clan_container]
    assert [row.agent_clan_generation for row in containers] == ["new", "old"]
    assert containers[0].runtime_children == [new]
    assert containers[1].runtime_children == [old]
    assert new.tree_parent_key == agent_fold_key(containers[0])
    assert old.tree_parent_key == agent_fold_key(containers[1])


def test_clan_tree_does_not_invent_a_patch_banner_from_one_member() -> None:
    one = _agent("first-patch", "one")
    two = _agent("second-patch", "two")
    projected = project_clan_tree([one, two])

    group_keys = [
        entry.group.group_key
        for entry in build_agent_tree(projected)
        if entry.group is not None
    ]

    assert group_keys == [("tmp",)]


def test_project_clan_tree_nests_disk_shaped_monitor_under_starter() -> None:
    family = _agent("sase-ns.6.6.6.1", "20260817055518")
    family.agent_family = "sase-ns.6.6.6.1"
    family.agent_family_role = "root"
    starter = _agent(
        "sase-ns.6.6.6.1--2",
        "20260817070811",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    starter.agent_family = family.agent_family
    starter.agent_family_role = "code"
    monitor = _agent(
        "sase-ns.6.6.6.1--mon-1",
        "20260817071511",
        parent_timestamp=starter.raw_suffix,
        clan=None,
        generation=None,
    )
    monitor.agent_family = family.agent_family
    monitor.agent_family_role = "monitor"
    peer = _agent("sase-ns.6.6.6.2", "20260817060000", status="DONE")

    projected = project_clan_tree([family, starter, monitor, peer])

    container = projected[0]
    assert container.is_clan_container is True
    assert monitor.agent_clan is None
    assert monitor.agent_clan_generation is None
    assert monitor.tree_parent_key == starter.raw_suffix
    assert monitor.tree_depth == starter.tree_depth + 1 == 3
    assert starter.tree_parent_key == family.raw_suffix
    assert starter.tree_depth == 2
    assert family.tree_depth == 1
    assert projected.index(monitor) == projected.index(starter) + 1
    assert projected == [container, family, starter, monitor, peer]


def test_project_clan_tree_keeps_tagged_and_disk_shaped_monitors_identical() -> None:
    family = _agent("research.family", "family")
    family.agent_family = "research.family"
    family.agent_family_role = "root"
    starter = _agent(
        "research.family--2",
        "starter",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    starter.agent_family = family.agent_family
    disk_monitor = _agent(
        "research.family--mon-1",
        "disk-mon",
        parent_timestamp=starter.raw_suffix,
        clan=None,
        generation=None,
    )
    disk_monitor.agent_family = family.agent_family
    disk_monitor.agent_family_role = "monitor"
    tagged_monitor = _agent(
        "research.family--mon-1",
        "tagged-mon",
        parent_timestamp=starter.raw_suffix,
        clan=family.agent_clan,
        generation=family.agent_clan_generation,
    )
    tagged_monitor.agent_family = family.agent_family
    tagged_monitor.agent_family_role = "monitor"

    disk_tree = project_clan_tree([family, starter, disk_monitor])
    tagged_tree = project_clan_tree([family, starter, tagged_monitor])

    assert [row.tree_depth for row in disk_tree] == [
        row.tree_depth for row in tagged_tree
    ]
    assert (
        disk_monitor.tree_parent_key
        == tagged_monitor.tree_parent_key
        == starter.raw_suffix
    )
    assert disk_monitor.tree_depth == tagged_monitor.tree_depth == 3
