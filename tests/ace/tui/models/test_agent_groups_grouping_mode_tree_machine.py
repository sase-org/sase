"""GroupingMode: BY_MACHINE ``build_agent_tree`` shape and ordering."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import (
    GroupingMode,
    banner_label_for_group_key,
    build_agent_tree,
)

from ._agent_groups_helpers import _NOW, _agent, _group_keys, _kinds


def test_build_agent_tree_by_machine_orders_here_first_then_aliases() -> None:
    local = _agent(
        cl_name="local",
        agent_name="local.agent",
        start_time=datetime(2026, 4, 26, 8, 0, 0),
    )
    zeus = _agent(
        cl_name="zeus",
        agent_name="zeus.agent",
        start_time=datetime(2026, 4, 26, 12, 0, 0),
    )
    zeus.fleet_origin_alias = "zeus"
    apollo = _agent(
        cl_name="apollo",
        agent_name="apollo.agent",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    apollo.fleet_origin_alias = "apollo"

    entries = build_agent_tree(
        [zeus, local, apollo],
        mode=GroupingMode.BY_MACHINE,
        now=_NOW,
    )

    assert _group_keys(entries, level=0) == [("here",), ("apollo",), ("zeus",)]
    assert [entry.agent_idx for entry in entries if entry.kind == "agent"] == [
        1,
        2,
        0,
    ]


def test_build_agent_tree_by_machine_groups_name_roots_within_machine() -> None:
    first = _agent(cl_name="x", agent_name="coder.claude", status="RUNNING")
    first.fleet_origin_alias = "apollo"
    second = _agent(cl_name="y", agent_name="coder.codex", status="RUNNING")
    second.fleet_origin_alias = "apollo"
    solo = _agent(cl_name="z", agent_name="solo.gemini", status="RUNNING")
    solo.fleet_origin_alias = "apollo"

    entries = build_agent_tree(
        [first, second, solo],
        mode=GroupingMode.BY_MACHINE,
        now=_NOW,
    )

    # machine (L0) -> status subgroup (L1, always emitted) -> name-root (L2).
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 2),
        ("group", 2),
        ("agent", 0),
        ("agent", 1),
    ]
    assert _group_keys(entries, level=1) == [("apollo", "Running")]
    assert _group_keys(entries, level=2) == [("apollo", "Running", "coder")]


def test_build_agent_tree_by_machine_status_subgroups_priority_order() -> None:
    """Within each machine, status subgroups sort Stopped/Failed/Running/.../Starting."""
    apollo_running = _agent(
        cl_name="a", agent_name="a", status="RUNNING", start_time=_NOW
    )
    apollo_running.fleet_origin_alias = "apollo"
    apollo_done = _agent(cl_name="b", agent_name="b", status="DONE", start_time=_NOW)
    apollo_done.fleet_origin_alias = "apollo"
    apollo_failed = _agent(
        cl_name="c", agent_name="c", status="FAILED", start_time=_NOW
    )
    apollo_failed.fleet_origin_alias = "apollo"
    here_running = _agent(cl_name="d", agent_name="d", status="RUNNING")
    here_stopped = _agent(cl_name="e", agent_name="e", status="QUESTION")

    entries = build_agent_tree(
        [apollo_done, apollo_running, apollo_failed, here_running, here_stopped],
        mode=GroupingMode.BY_MACHINE,
        now=_NOW,
    )

    assert _group_keys(entries, level=0) == [("here",), ("apollo",)]
    assert _group_keys(entries, level=1) == [
        ("here", "Stopped"),
        ("here", "Running"),
        ("apollo", "Failed"),
        ("apollo", "Running"),
        ("apollo", "Done"),
    ]


def test_build_agent_tree_by_machine_family_splits_across_status_buckets() -> None:
    """A name-root split across buckets forms one root group per bucket."""
    running_a = _agent(cl_name="a", agent_name="coder.a", status="RUNNING")
    running_b = _agent(cl_name="b", agent_name="coder.b", status="RUNNING")
    done_a = _agent(cl_name="c", agent_name="coder.c", status="DONE")
    done_b = _agent(cl_name="d", agent_name="coder.d", status="DONE")

    entries = build_agent_tree(
        [running_a, running_b, done_a, done_b],
        mode=GroupingMode.BY_MACHINE,
        now=_NOW,
    )

    groups = [
        (e.group.level, e.group.group_key)  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None
    ]
    # Two separate "coder" name-root banners — one per status bucket —
    # never a single group spanning both buckets.
    assert groups == [
        (0, ("here",)),
        (1, ("here", "Running")),
        (2, ("here", "Running", "coder")),
        (1, ("here", "Done")),
        (2, ("here", "Done", "coder")),
    ]


def test_build_agent_tree_by_machine_keeps_standalone_lanes_above_subgroups() -> None:
    """Standalone-before-subgroups partitioning holds within a status bucket."""
    hh = _agent(
        cl_name="hh", agent_name="hh", start_time=datetime(2026, 4, 26, 12, 0, 0)
    )
    hi = _agent(
        cl_name="hi", agent_name="hi", start_time=datetime(2026, 4, 26, 8, 0, 0)
    )
    hk = _agent(
        cl_name="hk", agent_name="hk", start_time=datetime(2026, 4, 26, 11, 0, 0)
    )
    hk_followup = _agent(
        cl_name="hk-followup",
        agent_name="hk.f0",
        start_time=datetime(2026, 4, 26, 13, 0, 0),
    )
    agents = [hk_followup, hi, hk, hh]

    entries = build_agent_tree(agents, mode=GroupingMode.BY_MACHINE, now=_NOW)

    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 3),
        ("agent", 1),
        ("group", 2),
        ("agent", 0),
        ("agent", 2),
    ]
    assert _group_keys(entries, level=2) == [("here", "Running", "hk")]


def test_build_agent_tree_by_machine_collapse_cascade_is_per_level() -> None:
    """Collapsing machine / status / name-root each suppress only their own kids."""
    first = _agent(cl_name="x", agent_name="coder.claude", status="RUNNING")
    second = _agent(cl_name="y", agent_name="coder.codex", status="RUNNING")

    # Collapsing the status subgroup hides the name-root banner and agents,
    # but the machine (L0) banner stays visible.
    registry = AgentGroupFoldRegistry()
    registry.collapse(("here", "Running"))
    entries = build_agent_tree(
        [first, second], fold_registry=registry, mode=GroupingMode.BY_MACHINE, now=_NOW
    )
    assert _kinds(entries) == [("group", 0), ("group", 1)]

    # Collapsing the machine hides everything beneath it.
    registry2 = AgentGroupFoldRegistry()
    registry2.collapse(("here",))
    entries2 = build_agent_tree(
        [first, second],
        fold_registry=registry2,
        mode=GroupingMode.BY_MACHINE,
        now=_NOW,
    )
    assert _kinds(entries2) == [("group", 0)]


def test_banner_label_for_by_machine_status_subgroup_key_is_plain_bucket_name() -> None:
    assert banner_label_for_group_key(("apollo", "Running")) == "Running"
