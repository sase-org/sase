"""Tests for wait/fork actions with marked Agents-tab rows."""

from __future__ import annotations

from tests.ace.tui._agent_marking_helpers import _FakeWaitApp, _make_agent


def test_wait_for_agent_no_marks_uses_single_agent_path() -> None:
    a1 = _make_agent(raw_suffix="20240101120000", agent_name="alice")
    app = _FakeWaitApp([a1])

    app.action_wait_for_agent()

    assert len(app.prompt_bar_calls) == 1
    call = app.prompt_bar_calls[0]
    assert call["initial_text"] == "%w:alice "
    assert call["display_name"] == "wait(alice)"


def test_wait_for_agent_family_root_uses_root_name() -> None:
    a1 = _make_agent(
        raw_suffix="20240101120000",
        agent_name="alice-plan",
        agent_family="alice",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = _FakeWaitApp([a1])

    app.action_wait_for_agent()

    assert app.prompt_bar_calls[0]["initial_text"] == "%w:alice "
    assert app.prompt_bar_calls[0]["display_name"] == "wait(alice)"


def test_fork_agent_family_root_uses_root_name() -> None:
    a1 = _make_agent(
        raw_suffix="20240101120000",
        status="DONE",
        agent_name="alice-plan",
        agent_family="alice",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = _FakeWaitApp([a1])

    app.action_fork_agent()

    assert app.prompt_bar_calls[0]["initial_text"] == "#fork:alice "
    assert app.prompt_bar_calls[0]["display_name"] == "fork(alice)"


def test_fork_running_named_agent_omits_explicit_wait() -> None:
    """A running named agent forks with #fork:<name> only.

    #fork:<name> now implies %w:<name>, so the prefill no longer carries a
    redundant explicit wait directive.
    """
    a1 = _make_agent(
        raw_suffix="20240101120000",
        status="RUNNING",
        agent_name="alice",
    )
    app = _FakeWaitApp([a1])

    app.action_fork_agent()

    assert app.prompt_bar_calls[0]["initial_text"] == "#fork:alice "
    assert app.prompt_bar_calls[0]["display_name"] == "fork(alice)"


def test_fork_failed_named_agent_prefills_fork_prompt() -> None:
    a1 = _make_agent(
        raw_suffix="20240101120000",
        status="FAILED",
        agent_name="alice",
    )
    app = _FakeWaitApp([a1])

    app.action_fork_agent()

    assert app.prompt_bar_calls[0]["initial_text"] == "#fork:alice "
    assert app.prompt_bar_calls[0]["display_name"] == "fork(alice)"


def test_fork_failed_unnamed_agent_warns() -> None:
    a1 = _make_agent(
        raw_suffix="20240101120000",
        status="FAILED",
        agent_name=None,
    )
    app = _FakeWaitApp([a1])

    app.action_fork_agent()

    assert app.prompt_bar_calls == []
    assert ("No agent name found", "warning") in app.notifications


def test_fork_stopped_agent_still_warns_not_finished() -> None:
    a1 = _make_agent(
        raw_suffix="20240101120000",
        status="STOPPED",
        agent_name="alice",
    )
    app = _FakeWaitApp([a1])

    app.action_fork_agent()

    assert app.prompt_bar_calls == []
    assert ("Agent not finished yet", "warning") in app.notifications


def test_wait_for_agent_one_mark_falls_through_to_single_agent() -> None:
    """A single mark behaves identically to single-agent path (cursor irrelevant)."""
    a1 = _make_agent(cl_name="cl_a", raw_suffix="20240101120000", agent_name="alice")
    a2 = _make_agent(cl_name="cl_b", raw_suffix="20240101130000", agent_name="bob")
    app = _FakeWaitApp([a1, a2])
    # Cursor is on a1 but only a2 is marked; we should wait on a2 not a1.
    app.current_idx = 0
    app._marked_agents = {a2.identity}

    app.action_wait_for_agent()

    assert len(app.prompt_bar_calls) == 1
    call = app.prompt_bar_calls[0]
    assert call["initial_text"] == "%w:bob "
    assert call["display_name"] == "wait(bob)"


def test_wait_for_agent_bulk_marks_joins_with_commas() -> None:
    a1 = _make_agent(cl_name="cl_a", raw_suffix="20240101120000", agent_name="alice")
    a2 = _make_agent(cl_name="cl_b", raw_suffix="20240101130000", agent_name="bob")
    app = _FakeWaitApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}

    app.action_wait_for_agent()

    assert len(app.prompt_bar_calls) == 1
    call = app.prompt_bar_calls[0]
    # Order follows _agents_with_children iteration: a1, then a2.
    assert call["initial_text"] == "%w:alice,bob "
    assert call["display_name"] == "wait(2 agents)"


def test_wait_for_agent_bulk_skips_unnamed_and_warns() -> None:
    a1 = _make_agent(cl_name="cl_a", raw_suffix="20240101120000", agent_name="alice")
    a2 = _make_agent(cl_name="cl_b", raw_suffix="20240101130000", agent_name="bob")
    a3 = _make_agent(cl_name="cl_c", raw_suffix="20240101140000", agent_name=None)
    app = _FakeWaitApp([a1, a2, a3])
    app._marked_agents = {a1.identity, a2.identity, a3.identity}

    app.action_wait_for_agent()

    assert len(app.prompt_bar_calls) == 1
    assert app.prompt_bar_calls[0]["initial_text"] == "%w:alice,bob "
    assert ("Skipped 1 marked agent(s) with no name", "warning") in app.notifications


def test_wait_for_agent_bulk_all_unnamed_warns_and_skips_prompt() -> None:
    a1 = _make_agent(cl_name="cl_a", raw_suffix="20240101120000", agent_name=None)
    a2 = _make_agent(cl_name="cl_b", raw_suffix="20240101130000", agent_name=None)
    app = _FakeWaitApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}

    app.action_wait_for_agent()

    assert app.prompt_bar_calls == []
    assert ("No marked agents have a name", "warning") in app.notifications
