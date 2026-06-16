"""Tests for Agents-tab mark toggling and bulk mark actions."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType

from tests.ace.tui._agent_marking_helpers import _FakeMarkApp, _make_agent


def test_toggle_mark_adds_identity() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])

    app._toggle_mark_agent()

    assert a1.identity in app._marked_agents
    assert a2.identity not in app._marked_agents


def test_toggle_mark_auto_advances_cursor() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])

    app._toggle_mark_agent()

    assert app.current_idx == 1


def test_toggle_mark_wraps_around() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])
    app.current_idx = 1

    app._toggle_mark_agent()

    assert app.current_idx == 0


def test_toggle_mark_advances_in_rendered_agent_order() -> None:
    agents = [
        _make_agent(project_file="/tmp/projects/zeta/zeta.sase", cl_name="z1"),
        _make_agent(project_file="/tmp/projects/alpha/alpha.sase", cl_name="a1"),
        _make_agent(project_file="/tmp/projects/beta/beta.sase", cl_name="b1"),
    ]
    app = _FakeMarkApp(agents)
    app.current_idx = 1  # alpha, visually first

    app._toggle_mark_agent()

    assert app.current_idx == 2
    assert app._agents[app.current_idx].cl_name == "b1"


def test_toggle_mark_wraps_in_rendered_agent_order() -> None:
    agents = [
        _make_agent(project_file="/tmp/projects/zeta/zeta.sase", cl_name="z1"),
        _make_agent(project_file="/tmp/projects/alpha/alpha.sase", cl_name="a1"),
        _make_agent(project_file="/tmp/projects/beta/beta.sase", cl_name="b1"),
    ]
    app = _FakeMarkApp(agents)
    app.current_idx = 0  # zeta, visually last

    app._toggle_mark_agent()

    assert app.current_idx == 1
    assert app._agents[app.current_idx].cl_name == "a1"


def test_toggle_mark_skips_collapsed_banner_rows() -> None:
    agents = [
        _make_agent(project_file="/tmp/projects/alpha/alpha.sase", cl_name="a1"),
        _make_agent(project_file="/tmp/projects/beta/beta.sase", cl_name="b1"),
    ]
    app = _FakeMarkApp(agents)
    app._group_fold_registry.collapse(("alpha",))
    app.current_idx = 1

    app._toggle_mark_agent()

    assert app.current_idx == 1
    assert app._agents[app.current_idx].cl_name == "b1"


def test_toggle_mark_twice_removes_identity() -> None:
    a1 = _make_agent()
    app = _FakeMarkApp([a1])

    app._toggle_mark_agent()
    # With a single entry, cursor stays at 0 (no wraparound needed)
    assert app.current_idx == 0
    assert a1.identity in app._marked_agents
    app._toggle_mark_agent()

    assert a1.identity not in app._marked_agents


def test_toggle_mark_empty_panel_warns() -> None:
    app = _FakeMarkApp([])

    app._toggle_mark_agent()

    assert app._marked_agents == set()
    assert app.notifications == [("No agent selected", "warning")]


def test_clear_agent_marks_removes_all() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}

    app._clear_agent_marks()

    assert app._marked_agents == set()
    assert any(msg.startswith("Cleared") for msg, _ in app.notifications)


def test_clear_agent_marks_when_empty_warns() -> None:
    app = _FakeMarkApp([_make_agent()])

    app._clear_agent_marks()

    assert app.notifications == [("No marks to clear", "warning")]


def test_prune_stale_marked_agents_drops_missing() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    app = _FakeMarkApp([a1])
    ghost_identity: tuple[AgentType, str, str | None] = (
        AgentType.RUNNING,
        "missing",
        "20240101999999",
    )
    app._marked_agents = {a1.identity, ghost_identity}

    app._prune_stale_marked_agents()

    assert app._marked_agents == {a1.identity}


def test_bulk_kill_partitions_and_clears_marks() -> None:
    """Bulk kill with confirm delegates one batched call."""
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    done = _make_agent(
        cl_name="done_cl",
        raw_suffix="20240101130000",
        status="DONE",
        pid=None,
    )
    app = _FakeMarkApp([running, done])
    app._marked_agents = {running.identity, done.identity}

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app._bulk_kill_marked_agents()
        assert app.pushed_callbacks, "Modal callback not registered"
        # Simulate user confirming the modal
        app.pushed_callbacks[0](True)

    mock_bulk.assert_called_once_with([running], [done])


def test_bulk_kill_cancel_preserves_marks() -> None:
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    app = _FakeMarkApp([running])
    app._marked_agents = {running.identity}

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app._bulk_kill_marked_agents()
        # Simulate user cancelling the modal
        app.pushed_callbacks[0](False)

    mock_bulk.assert_not_called()
    assert app._marked_agents == {running.identity}


def test_save_marked_agents_dispatches_on_agents_tab() -> None:
    """The Agents-tab save action delegates to the save/dismiss flow."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])

    with patch.object(app, "_prompt_and_save_marked_agent_group") as mock_save:
        app.action_save_marked_agents()

    mock_save.assert_called_once_with()


def test_bulk_change_status_does_not_save_marked_agents_on_agents_tab() -> None:
    """The uppercase bulk-status action is CL-only."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])

    with patch.object(app, "_prompt_and_save_marked_agent_group") as mock_save:
        app.action_bulk_change_status()

    mock_save.assert_not_called()


def test_bulk_change_status_keeps_changespec_status_flow() -> None:
    """The CLs tab still opens the bulk status modal."""

    class _Spec:
        status = "WIP"

    app = _FakeMarkApp([])
    app.current_tab = "changespecs"
    app.changespecs = [_Spec()]  # type: ignore[list-item]
    app.marked_indices = {0}

    app.action_bulk_change_status()

    assert len(app.pushed_modals) == 1
    assert app.pushed_callbacks[0] is not None


def test_toggle_mark_dispatches_to_agents_tab_from_action() -> None:
    """action_toggle_mark on agents tab routes to _toggle_mark_agent."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])

    app.action_toggle_mark()

    assert a1.identity in app._marked_agents
    # ChangeSpec mark set is independent
    assert app.marked_indices == set()


def test_toggle_mark_on_changespecs_does_not_touch_agent_marks() -> None:
    """action_toggle_mark on changespecs tab leaves _marked_agents alone."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])
    app.current_tab = "changespecs"
    app.changespecs = [object()]  # type: ignore[list-item]

    app.action_toggle_mark()

    assert app._marked_agents == set()


def test_clear_marks_dispatches_to_agents_tab_from_action() -> None:
    """action_clear_marks on agents tab routes to _clear_agent_marks."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])
    app._marked_agents = {a1.identity}

    app.action_clear_marks()

    assert app._marked_agents == set()


# --- mark order tracking ---------------------------------------------------


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
