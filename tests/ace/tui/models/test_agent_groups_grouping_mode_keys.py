"""GroupingMode: grouping-key shape and ChangeSpec-level skipping."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree

from ._agent_groups_helpers import _NOW, _agent, _kinds


def test_build_agent_tree_default_mode_matches_standard() -> None:
    """Omitting the (Phase 2/3-bound) mode preserves existing behavior."""
    a = _agent(cl_name="demo", agent_name="coder.claude")
    b = _agent(cl_name="demo", agent_name="coder.codex")
    # Both produce the existing project / changespec / name-root tree.
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
    # ChangeSpec is dropped in non-STANDARD modes.
    assert all(k.changespec == "" for k in keys)


def test_grouping_keys_for_agents_by_status_uses_bucket_at_l0() -> None:
    from sase.ace.tui.models.agent_groups import _grouping_keys_for_agents

    needs = _agent(status="QUESTION")
    running = _agent(status="RUNNING")
    keys = _grouping_keys_for_agents([needs, running], GroupingMode.BY_STATUS, _NOW)
    assert [k.project for k in keys] == ["Needs Attention", "Running"]
    assert all(k.changespec == "" for k in keys)


def test_panel_uses_changespec_level_skipped_in_non_standard_modes() -> None:
    """BY_DATE / BY_STATUS never use the ChangeSpec layer, even when present."""
    from sase.ace.tui.models.agent_groups import _panel_uses_changespec_level

    agents = [_agent(cl_name="demo")]
    assert _panel_uses_changespec_level(agents, GroupingMode.STANDARD) is True
    assert _panel_uses_changespec_level(agents, GroupingMode.BY_DATE) is False
    assert _panel_uses_changespec_level(agents, GroupingMode.BY_STATUS) is False


def test_panel_uses_changespec_level_ignores_project_scoped_agents() -> None:
    from sase.ace.tui.models.agent_groups import _panel_uses_changespec_level

    agents = [_agent(cl_name="sase", project_file="/r/sase/sase.gp")]
    assert _panel_uses_changespec_level(agents, GroupingMode.STANDARD) is False


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
