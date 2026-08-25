"""Tests for Agents-tab mark order tracking."""

from __future__ import annotations

from sase.ace.tui.models.agent import Agent

from tests.ace.tui._agent_marking_helpers import _FakeMarkApp, _make_agent


def _abc_app() -> tuple[_FakeMarkApp, Agent, Agent, Agent]:
    a = _make_agent(cl_name="a", raw_suffix="20240101120000")
    b = _make_agent(cl_name="b", raw_suffix="20240101130000")
    c = _make_agent(cl_name="c", raw_suffix="20240101140000")
    return _FakeMarkApp([a, b, c]), a, b, c


def test_mark_order_records_marking_sequence() -> None:
    app, a, b, c = _abc_app()

    # Mark a, then b, then c (toggle auto-advances the cursor each time).
    app.current_idx = 0
    app._toggle_mark_agent()  # marks a -> idx 1
    app._toggle_mark_agent()  # marks b -> idx 2
    app._toggle_mark_agent()  # marks c -> idx 0

    assert app._marked_agent_order == [a.identity, b.identity, c.identity]
    assert [ag.cl_name for ag in app._marked_agents_in_mark_order()] == [
        "a",
        "b",
        "c",
    ]


def test_unmark_then_remark_moves_identity_to_end() -> None:
    app, a, b, c = _abc_app()
    app.current_idx = 0
    app._toggle_mark_agent()  # a -> idx 1
    app._toggle_mark_agent()  # b -> idx 2
    app._toggle_mark_agent()  # c -> idx 0

    app.current_idx = 0
    app._toggle_mark_agent()  # unmark a -> idx 1
    assert app._marked_agent_order == [b.identity, c.identity]

    app.current_idx = 0
    app._toggle_mark_agent()  # re-mark a -> moves to end

    assert app._marked_agent_order == [b.identity, c.identity, a.identity]
    assert [ag.cl_name for ag in app._marked_agents_in_mark_order()] == [
        "b",
        "c",
        "a",
    ]


def test_clear_marks_resets_order() -> None:
    app, a, b, _c = _abc_app()
    app.current_idx = 0
    app._toggle_mark_agent()
    app._toggle_mark_agent()
    assert app._marked_agent_order == [a.identity, b.identity]

    app._clear_agent_marks()

    assert app._marked_agent_order == []
    assert app._marked_agents == set()


def test_prune_stale_marks_drops_order_entries() -> None:
    app, a, b, c = _abc_app()
    app.current_idx = 0
    app._toggle_mark_agent()  # a
    app._toggle_mark_agent()  # b
    app._toggle_mark_agent()  # c

    # b vanishes from the live agent list.
    app._agents = [a, c]
    app._agents_with_children = [a, c]

    app._prune_stale_marked_agents()

    assert app._marked_agent_order == [a.identity, c.identity]
    assert b.identity not in app._marked_agents


def test_bulk_kill_resets_mark_order() -> None:
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    done = _make_agent(
        cl_name="done_cl",
        raw_suffix="20240101130000",
        status="DONE",
        pid=None,
    )
    app = _FakeMarkApp([running, done])
    app.current_idx = 0
    app._toggle_mark_agent()  # running
    app._toggle_mark_agent()  # done
    assert app._marked_agent_order == [running.identity, done.identity]

    app._bulk_kill_marked_agents()
    assert app.pushed_callbacks, "Modal callback not registered"
    app.pushed_callbacks[0](True)  # confirm

    assert app._marked_agents == set()
    assert app._marked_agent_order == []


def test_marked_agents_in_mark_order_appends_unordered_marks() -> None:
    # Marks set directly (e.g. legacy/test path) have no order entry; the
    # reconciler appends them in display order without dropping any.
    app, a, b, c = _abc_app()
    app._marked_agents = {a.identity, b.identity, c.identity}
    app._marked_agent_order = [c.identity]  # only c is ordered

    ordered = app._marked_agents_in_mark_order()

    assert [ag.cl_name for ag in ordered] == ["c", "a", "b"]


def test_marked_agents_in_mark_order_skips_unmarked_order_entries() -> None:
    app, a, b, _c = _abc_app()
    app._marked_agents = {a.identity}
    # Order list still references b even though it is no longer marked.
    app._marked_agent_order = [b.identity, a.identity]

    ordered = app._marked_agents_in_mark_order()

    assert [ag.cl_name for ag in ordered] == ["a"]
