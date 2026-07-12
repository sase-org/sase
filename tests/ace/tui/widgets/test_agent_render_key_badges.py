"""Tests for render-key inputs from row badges and timing labels."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_render_cache import agent_file_change_hint
from sase.ace.tui.widgets._agent_list_rendering import agent_render_key

from ._agent_render_cache_helpers import agent as _agent


def _root_plan(*, diff_has_real_edits: bool | None = None) -> Agent:
    plan = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="demo",
        project_file="/tmp/p.sase",
        status="PLAN APPROVED",
        start_time=datetime(2026, 4, 25, 14, 30, 0),
        raw_suffix="20260425143000",
        role_suffix="-plan",
        plan_chain_root=True,
    )
    plan.diff_has_real_edits = diff_has_real_edits
    return plan


def _active_coder_child() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo-code",
        project_file="/tmp/p.sase",
        status="PLAN APPROVED",
        start_time=datetime(2026, 4, 25, 14, 31, 0),
        raw_suffix="20260425143000-code",
        parent_timestamp="20260425143000",
        role_suffix="-code",
    )


def test_render_key_changes_when_diff_path_appears_or_disappears() -> None:
    a = _agent()
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    a.diff_path = "/tmp/sase/demo.diff"
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    a.diff_path = None
    k3 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    assert k1 != k2
    assert k1 == k3


def test_render_key_changes_when_diff_badge_classification_changes() -> None:
    a = _agent()
    a.diff_path = "/tmp/sase/demo.diff"
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    a.diff_has_real_edits = False
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    a.diff_has_real_edits = True
    k3 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    assert k1 != k2
    assert k1 == k3


def test_render_key_changes_when_live_file_change_hint_changes() -> None:
    a = _agent(status="RUNNING")
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    a.live_file_change_hint = True
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    a.live_file_change_hint = False
    k3 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    # The pencil appears (k1 -> k2) and disappears (k2 -> k3) as the live hint
    # flips, so the selective-patch cache must see distinct keys.
    assert k1 != k2
    assert k2 != k3
    assert k1 == k3


def test_render_key_changes_when_reverted_flips() -> None:
    a = _agent()
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    a.reverted = True
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    a.reverted = False
    k3 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    assert k1 != k2
    assert k1 == k3


def test_render_key_changes_across_seconds_for_ticking_parent_status() -> None:
    a = _agent(status="PLAN APPROVED")
    child = _agent(
        cl_name="demo.code",
        status="RUNNING",
        raw_suffix="20260425143100",
    )
    child.run_start_time = datetime(2026, 4, 25, 14, 30, 0)
    a.runtime_children.append(child)

    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 1),
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 2),
    )

    assert k1 != k2


def test_render_key_changes_when_plan_runtime_timestamp_changes() -> None:
    a = _agent(status="DONE")

    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 1),
    )
    a.plan_times.append(datetime(2026, 4, 25, 14, 35, 0))
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 1),
    )

    assert k1 != k2


def test_render_key_changes_when_code_runtime_timestamp_changes() -> None:
    a = _agent(status="PLAN APPROVED")
    a.plan_times.append(datetime(2026, 4, 25, 14, 35, 0))

    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 40, 1),
    )
    a.code_time = datetime(2026, 4, 25, 14, 36, 0)
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 40, 1),
    )

    assert k1 != k2


def test_redirected_plan_badge_renders_from_live_hint_over_bookkeeping() -> None:
    """A redirected plan row shows a pencil from its live hint, not its own diff.

    The plan row's persisted ``diff_has_real_edits`` is bookkeeping-only while a
    coder child owns the workspace, so the badge must follow the deferred live
    hint that mirrors the detail panel's ``Deltas:``.
    """
    plan = _root_plan(diff_has_real_edits=False)
    plan.followup_agents.append(_active_coder_child())

    # No live hint yet → no badge, even though something could be inferred.
    assert plan.live_file_change_hint is None
    assert agent_file_change_hint(plan) is False

    # Deferred scan reports real child edits → pencil, despite the plan row's
    # own diff_has_real_edits=False.
    plan.live_file_change_hint = True
    assert agent_file_change_hint(plan) is True

    plan.live_file_change_hint = False
    assert agent_file_change_hint(plan) is False


def test_non_redirected_row_badge_prefers_persisted_over_stale_live_hint() -> None:
    a = _agent(status="DONE")
    a.diff_has_real_edits = True
    a.live_file_change_hint = False

    # Not redirected: the persisted classification stays authoritative and wins
    # over a stale live hint.
    assert agent_file_change_hint(a) is True


def test_active_row_badge_prefers_live_hint_over_persisted_fallback() -> None:
    agent = _agent(status="RUNNING")
    agent.diff_has_real_edits = True
    agent.live_file_change_hint = False

    assert agent_file_change_hint(agent) is False


def test_plan_row_without_active_child_uses_own_classification() -> None:
    plan = _root_plan(diff_has_real_edits=True)

    # No active coder child → not redirected → the plan row's own persisted
    # classification drives the badge.
    assert agent_file_change_hint(plan) is True
