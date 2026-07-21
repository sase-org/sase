"""Per-group agents-tab fold transition tests."""

from __future__ import annotations

from sase.ace.tui.models.agent_groups import GroupingMode

from ._agent_fold_transition_helpers import StubFoldApp, make_agent


def test_capital_h_on_agent_collapses_only_its_group() -> None:
    """Two projects A + B; pressing ``H`` in A leaves B untouched."""
    a = make_agent(cl_name="cl-a", project="projA")
    b = make_agent(cl_name="cl-b", project="projB")
    app = StubFoldApp([a, b], current_idx=0)

    app.action_hooks_or_collapse_all()

    assert app._group_fold_registry.is_collapsed(("projA", "cl-a")) is True
    assert app._group_fold_registry.is_collapsed(("projB", "cl-b")) is False
    assert app._current_group_key == ("projA", "cl-a")


def test_capital_h_inside_l1_collapses_l1_then_parent_l0() -> None:
    """Focus inside an L1: first ``H`` collapses L1, second collapses L0."""
    a = make_agent(agent_name="coder.claude")
    b = make_agent(agent_name="coder.codex")
    app = StubFoldApp([a, b], current_idx=0)
    l1 = ("proj", "demo", "coder")
    l0 = ("proj", "demo")

    app.action_hooks_or_collapse_all()
    assert app._group_fold_registry.is_collapsed(l1) is True
    assert app._group_fold_registry.is_collapsed(l0) is False
    assert app._current_group_key == l1

    app.action_hooks_or_collapse_all()
    assert app._group_fold_registry.is_collapsed(l0) is True
    assert app._current_group_key == l0


def test_l_on_collapsed_l1_banner_expands_only_that_l1() -> None:
    """``l`` while focused on a collapsed L1 expands only that group."""
    a = make_agent(agent_name="coder.claude")
    b = make_agent(agent_name="coder.codex")
    c = make_agent(agent_name="planner.claude")
    d = make_agent(agent_name="planner.codex")
    app = StubFoldApp([a, b, c, d], current_idx=0)
    coder = ("proj", "demo", "coder")
    planner = ("proj", "demo", "planner")
    app._group_fold_registry.collapse(coder)
    app._group_fold_registry.collapse(planner)
    app._current_group_key = coder

    app.action_expand_or_layout()

    assert app._group_fold_registry.is_collapsed(coder) is False
    assert app._group_fold_registry.is_collapsed(planner) is True


def test_l_expands_agent_fold_without_artifact_pane_focus() -> None:
    a = make_agent(agent_name="coder.claude")
    app = StubFoldApp([a], current_idx=0)
    key = ("proj", "demo", "coder")
    app._group_fold_registry.collapse(key)
    app._current_group_key = key
    app.focus_artifact_result = True

    app.action_expand_or_layout()

    assert app.focus_artifact_calls == 0
    assert app._group_fold_registry.is_collapsed(key) is False
    assert app.refilter_calls == 1


def test_capital_h_then_l_round_trip_clears_group_focus() -> None:
    """After ``H`` snaps to a banner, ``l`` expands and clears its focus."""
    a = make_agent(cl_name="cl-a", project="projA")
    app = StubFoldApp([a], current_idx=0)
    key = ("projA", "cl-a")

    app.action_hooks_or_collapse_all()
    assert app._current_group_key == key
    assert app._group_fold_registry.is_collapsed(key) is True

    app.action_expand_or_layout()
    assert app._group_fold_registry.is_collapsed(key) is False
    assert app._current_group_key is None


def test_equal_status_group_keys_fold_independently_between_panels() -> None:
    no_tribe = make_agent(status="DONE")
    tribe_assigned = make_agent(status="DONE", tribe="research")
    app = StubFoldApp([no_tribe, tribe_assigned], current_idx=0)
    app._grouping_mode = GroupingMode.BY_STATUS

    app.action_hooks_or_collapse_all()

    split_done = app._group_fold_registry.for_panel(None)
    tribe_assigned_done = app._group_fold_registry.for_panel("research")
    assert split_done.is_collapsed(("Done",)) is True
    assert tribe_assigned_done.is_collapsed(("Done",)) is False

    app._panel_group.focused_idx = 1
    app.current_idx = 1
    app._current_group_key = None
    app.action_hooks_or_collapse_all()
    assert tribe_assigned_done.is_collapsed(("Done",)) is True

    app.action_expand_or_layout()
    assert tribe_assigned_done.is_collapsed(("Done",)) is False
    assert split_done.is_collapsed(("Done",)) is True
