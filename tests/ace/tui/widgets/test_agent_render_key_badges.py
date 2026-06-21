"""Tests for render-key inputs from row badges and timing labels."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.widgets._agent_list_rendering import agent_render_key

from ._agent_render_cache_helpers import agent as _agent


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
