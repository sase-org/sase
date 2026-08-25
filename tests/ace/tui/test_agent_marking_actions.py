"""Tests for Agents-tab mark clearing and bulk action dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType

from tests.ace.tui._agent_marking_helpers import _FakeMarkApp, _make_agent


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
    """The uppercase bulk-status action is Patch-only."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])

    with patch.object(app, "_prompt_and_save_marked_agent_group") as mock_save:
        app.action_bulk_change_status()

    mock_save.assert_not_called()


def test_bulk_change_status_keeps_patch_status_flow() -> None:
    """The Patches tab still opens the bulk status modal."""

    class _Spec:
        status = "WIP"

    app = _FakeMarkApp([])
    app.current_tab = "patches"
    app.patches = [_Spec()]  # type: ignore[list-item]
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
    # Patch mark set is independent
    assert app.marked_indices == set()


def test_toggle_mark_on_patches_does_not_touch_agent_marks() -> None:
    """action_toggle_mark on patches tab leaves _marked_agents alone."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])
    app.current_tab = "patches"
    app.patches = [SimpleNamespace(project_name="proj", name="patch-1")]

    app.action_toggle_mark()

    assert app._marked_agents == set()


def test_clear_marks_dispatches_to_agents_tab_from_action() -> None:
    """action_clear_marks on agents tab routes to _clear_agent_marks."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])
    app._marked_agents = {a1.identity}

    app.action_clear_marks()

    assert app._marked_agents == set()
