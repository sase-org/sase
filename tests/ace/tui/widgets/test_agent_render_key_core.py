"""Tests for core per-row render-key extraction.

Phase 3 of sdd/plans/202604/instant_jk_navigation.md (bead sase-u.3).
"""

from __future__ import annotations

from sase.ace.tui.widgets._agent_list_rendering import agent_render_key

from ._agent_render_cache_helpers import agent as _agent


def test_render_key_changes_when_approve_flips() -> None:
    a = _agent(approve=False)
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
    a.approve = True
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
    assert k1 != k2


def test_render_key_stable_for_unchanged_inputs() -> None:
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
    assert k1 == k2


def test_render_key_changes_when_tribe_label_changes() -> None:
    a = _agent()
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        tribe_label="alpha",
        now=None,
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        tribe_label="beta",
        now=None,
    )
    assert k1 != k2


def test_render_key_changes_when_panel_tribe_changes() -> None:
    a = _agent()
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        panel_tribe="epic",
        now=None,
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        panel_tribe=None,
        now=None,
    )
    assert k1 != k2


def test_render_key_changes_when_unread_flips() -> None:
    a = _agent()
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        is_unread=False,
        hint_char=None,
        now=None,
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        is_unread=True,
        hint_char=None,
        now=None,
    )
    assert k1 != k2


def test_render_key_changes_when_fold_restore_marker_flips() -> None:
    a = _agent()
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        fold_restore_marked=False,
        hint_char=None,
        now=None,
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        fold_restore_marked=True,
        hint_char=None,
        now=None,
    )
    assert k1 != k2


def test_render_key_changes_when_llm_provider_changes() -> None:
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
    a.llm_provider = "codex"
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
    assert k1 != k2


def test_render_key_changes_when_runtime_child_provider_changes() -> None:
    a = _agent()
    child = _agent(
        cl_name="demo.plan",
        raw_suffix="20260425143100",
    )
    child.llm_provider = "claude"
    a.runtime_children.append(child)

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
    child.llm_provider = "codex"
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

    assert k1 != k2


def test_render_key_changes_when_provider_child_is_attached() -> None:
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

    child = _agent(
        cl_name="demo.code",
        raw_suffix="20260425143100",
    )
    child.llm_provider = "codex"
    a.runtime_children.append(child)
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

    assert k1 != k2


def test_render_key_changes_when_parallel_member_counts_change() -> None:
    root = _agent(status="RUNNING")
    member = _agent(
        cl_name="demo.phase",
        status="RUNNING",
        raw_suffix="20260425143100",
    )
    member.agent_family_parallel = True
    root.runtime_children.append(member)

    running_key = agent_render_key(
        root,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    member.status = "DONE"
    done_key = agent_render_key(
        root,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    assert running_key != done_key


def test_render_key_changes_when_bead_agent_name_changes() -> None:
    a = _agent(agent_name="sase-x.3")
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
    assert "sase-x.3" in k1

    a.agent_name = "sase-x.land"
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

    assert "sase-x.land" in k2
    assert k1 != k2
