"""GroupingMode: grouping-key shape and Patch-level skipping."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_groups import (
    GroupingMode,
    build_agent_tree,
    enumerate_group_keys,
)

from ._agent_groups_helpers import _NOW, _agent, _anchored_clan_agents, _kinds


def test_build_agent_tree_default_mode_matches_standard() -> None:
    """Omitting the (Phase 2/3-bound) mode preserves existing behavior."""
    a = _agent(cl_name="demo", agent_name="coder.claude")
    b = _agent(cl_name="demo", agent_name="coder.codex")
    # Both produce the existing project / patch / name-root tree.
    entries = build_agent_tree([a, b])
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 0),
        ("agent", 1),
    ]


def test_grouping_keys_for_agents_by_date_uses_bucket_at_l0() -> None:
    """Grouping keys under BY_DATE store the bucket as the L0 string."""
    from sase.ace.tui.models.agent_groups import _grouping_keys_for_agents

    today = _agent(start_time=datetime(2026, 4, 26, 9, 0, 0))
    earlier = _agent(start_time=datetime(2026, 4, 1, 9, 0, 0))
    keys = _grouping_keys_for_agents([today, earlier], GroupingMode.BY_DATE, _NOW)
    assert [k.project for k in keys] == ["Today", "Earlier"]
    # Patch is dropped in non-STANDARD modes.
    assert all(k.patch == "" for k in keys)


def test_grouping_keys_for_agents_by_status_uses_bucket_at_l0() -> None:
    from sase.ace.tui.models.agent_groups import _grouping_keys_for_agents

    needs = _agent(status="QUESTION")
    running = _agent(status="RUNNING")
    keys = _grouping_keys_for_agents([needs, running], GroupingMode.BY_STATUS, _NOW)
    assert [k.project for k in keys] == ["Stopped", "Running"]
    assert all(k.patch == "" for k in keys)


def test_panel_uses_patch_level_skipped_in_non_standard_modes() -> None:
    """BY_DATE / BY_STATUS never use the Patch layer, even when present."""
    from sase.ace.tui.models.agent_groups import _panel_uses_patch_level

    agents = [_agent(cl_name="demo")]
    assert _panel_uses_patch_level(agents, GroupingMode.STANDARD) is True
    assert _panel_uses_patch_level(agents, GroupingMode.BY_DATE) is False
    assert _panel_uses_patch_level(agents, GroupingMode.BY_STATUS) is False


def test_panel_uses_patch_level_ignores_project_scoped_agents() -> None:
    from sase.ace.tui.models.agent_groups import _panel_uses_patch_level

    agents = [_agent(cl_name="sase", project_file="/r/sase/sase.sase")]
    assert _panel_uses_patch_level(agents, GroupingMode.STANDARD) is False


def test_grouping_keys_for_agents_workflow_child_inherits_bucket() -> None:
    """Workflow children inherit their parent's bucket regardless of mode."""
    from sase.ace.tui.models.agent_groups import _grouping_keys_for_agents

    parent = _agent(
        cl_name="demo",
        agent_name="coder.claude",
        raw_suffix="ts1",
        status="DONE",
    )
    child = _agent(
        cl_name="step",
        agent_name="step.bash",
        parent_workflow="coder",
        parent_timestamp="ts1",
        status="RUNNING",
    )
    keys = _grouping_keys_for_agents([parent, child], GroupingMode.BY_STATUS, _NOW)
    # Both report the parent's bucket ("Done"), even though the child's
    # own status is "RUNNING".
    assert keys[0].project == "Done"
    assert keys[1].project == "Done"


def test_clan_descendants_inherit_outer_anchor_keys_in_every_mode() -> None:
    from sase.ace.tui.models.agent_groups import _grouping_keys_for_agents

    agents = _anchored_clan_agents()
    expectations = {
        GroupingMode.STANDARD: ("root", "", ""),
        GroupingMode.BY_STATUS: ("Running", "", ""),
        GroupingMode.BY_DATE: ("Today", "", "08:00"),
    }

    for mode, (l0, patch, subgroup) in expectations.items():
        keys = _grouping_keys_for_agents(agents, mode, _NOW)
        assert {key.project for key in keys} == {l0}
        assert {key.patch for key in keys} == {patch}
        assert {key.name_root for key in keys} == {""}
        assert {key.name_prefix for key in keys} == {""}
        assert {key.date_subgroup for key in keys} == {subgroup}

    assert enumerate_group_keys(agents, GroupingMode.STANDARD, _NOW) == [("root",)]
    assert enumerate_group_keys(agents, GroupingMode.BY_STATUS, _NOW) == [("Running",)]
    assert enumerate_group_keys(agents, GroupingMode.BY_DATE, _NOW) == [
        ("Today",),
        ("Today", "08:00"),
    ]
