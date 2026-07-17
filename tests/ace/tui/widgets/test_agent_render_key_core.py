"""Tests for core per-row render-key extraction.

Phase 3 of sdd/plans/202604/instant_jk_navigation.md (bead sase-u.3).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.widgets._agent_list_rendering import agent_render_key

from ._agent_render_cache_helpers import agent as _agent
from ._agent_render_cache_helpers import bead_key as _bead_key


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


def test_render_key_changes_when_tag_label_changes() -> None:
    a = _agent()
    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        tag_label="alpha",
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
        tag_label="beta",
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
        fold_annotation=" 1 running",
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
        fold_annotation=" 1 done",
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


def test_render_key_changes_when_confirmed_bead_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.models.agent_bead import (
        _BEAD_DISPLAY_CACHE,
        resolve_bead_display,
    )
    from sase.bead.model import Issue

    _BEAD_DISPLAY_CACHE.clear()
    try:
        a = _agent(agent_name="sase-x.3")
        k_cold = _bead_key(a)

        monkeypatch.setattr(
            "sase.agent.bead_display.lookup_bead_issue",
            lambda candidate_id, **_: Issue(id=candidate_id, title="", description=""),
        )
        resolve_bead_display(a)
        k_confirmed = _bead_key(a)

        assert k_cold != k_confirmed
    finally:
        _BEAD_DISPLAY_CACHE.clear()


def test_render_key_preserves_confirmed_bead_state_after_cache_expiry() -> None:
    from sase.ace.tui.models.agent_bead import (
        _BEAD_DISPLAY_CACHE,
        _bead_display_cache_key,
    )

    _BEAD_DISPLAY_CACHE.clear()
    try:
        a = _agent(agent_name="sase-x.3")
        key = _bead_display_cache_key(a)
        assert key is not None
        _BEAD_DISPLAY_CACHE.set(key, "sase-x.3")
        k_fresh = _bead_key(a)

        _BEAD_DISPLAY_CACHE._entries[key] = (-1.0, "sase-x.3")
        k_expired = _bead_key(a)

        assert k_expired == k_fresh
    finally:
        _BEAD_DISPLAY_CACHE.clear()


def test_render_key_changes_each_second_for_waiting_time_floor() -> None:
    a = _agent(status="WAITING")
    a.wait_until = "2026-04-25T14:35:00"

    k1 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 0),
        wait_deps_satisfied=True,
    )
    k2 = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=datetime(2026, 4, 25, 14, 30, 1),
        wait_deps_satisfied=True,
    )

    assert k1 != k2


def test_render_key_changes_when_wait_deps_satisfied_flips() -> None:
    a = _agent(status="WAITING")
    a.wait_until = "2026-04-25T14:35:00"
    a.waiting_for = ["dep"]
    now = datetime(2026, 4, 25, 14, 30, 0)

    pending_key = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=now,
        wait_deps_satisfied=False,
    )
    satisfied_key = agent_render_key(
        a,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=now,
        wait_deps_satisfied=True,
    )

    assert pending_key != satisfied_key


def test_render_key_changes_when_runner_slot_count_changes() -> None:
    agent = _agent(status="WAITING")
    agent.wait_runners = 9
    agent.slot_requested_at = "2026-07-12T12:00:00Z"
    agent.runner_slots_in_use = 10

    first = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )
    agent.runner_slots_in_use = 9
    second = agent_render_key(
        agent,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=None,
    )

    assert first != second


def test_render_key_uses_wait_display_source_timer_fields() -> None:
    root = _agent(status="WAITING")
    child = _agent(
        cl_name="child",
        status="WAITING",
        raw_suffix="20260425143100",
    )
    child.waiting_for = ["dep"]
    child.wait_duration = 300.0
    root.wait_display_source = child
    now = datetime(2026, 4, 25, 14, 30, 0)

    pending_key = agent_render_key(
        root,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=now,
        wait_deps_satisfied=True,
    )
    child.wait_until = "2026-04-25T14:35:00"
    live_key = agent_render_key(
        root,
        0,
        is_selected=False,
        fold_annotation="",
        is_expanded=False,
        is_marked=False,
        hint_char=None,
        now=now,
        wait_deps_satisfied=True,
    )

    assert pending_key != live_key


def test_render_key_unchanged_when_unconfirmed_candidate_resolves_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The candidate id alone must not bust the row cache: a cold candidate and a
    # candidate confirmed-missing both render no glyph, so their keys match.
    from sase.ace.tui.models.agent_bead import (
        _BEAD_DISPLAY_CACHE,
        resolve_bead_display,
    )

    _BEAD_DISPLAY_CACHE.clear()
    try:
        a = _agent(agent_name="sase-x.3")
        k_cold = _bead_key(a)

        monkeypatch.setattr(
            "sase.agent.bead_display.lookup_bead_issue",
            lambda candidate_id, **_: None,
        )
        resolve_bead_display(a)
        k_missing = _bead_key(a)

        assert k_cold == k_missing
    finally:
        _BEAD_DISPLAY_CACHE.clear()
