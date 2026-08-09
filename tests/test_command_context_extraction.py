"""Tests for extracting command-palette context from AceApp state."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sase.ace.testing import make_changespec
from sase.ace.tui.commands import extract_command_context
from sase.ace.tui.commands.context import (
    _completed_agent_count,
    _selected_axe_slot_states,
    _stopped_agent_count,
    _unread_completed_agent_count,
)
from sase.ace.tui.widgets.bgcmd_list import BgCmdItem, LumberjackItem


def _make_app_stub(
    *,
    tab: str = "changespecs",
    changespecs: list | None = None,
    current_idx: int = 0,
    agents: list | None = None,
    axe_items: list | None = None,
    marked_indices: set | None = None,
    marked_agents: set | None = None,
    current_group_key: tuple | None = None,
    current_attempt_number: int | None = None,
    axe_running: bool = False,
    bgcmd_slots: list | None = None,
):
    """Build a SimpleNamespace that mimics AceApp for context extraction."""
    return SimpleNamespace(
        current_tab=tab,
        current_idx=current_idx,
        current_attempt_number=current_attempt_number,
        changespecs=changespecs or [],
        _agents=agents or [],
        _axe_items=axe_items or [],
        marked_indices=marked_indices or set(),
        _marked_agents=marked_agents or set(),
        _current_group_key=current_group_key,
        axe_running=axe_running,
        _bgcmd_slots=bgcmd_slots or [],
        # AceApp.query_one would crash on a SimpleNamespace; the file
        # panel helper swallows exceptions so it just falls through.
        query_one=MagicMock(side_effect=RuntimeError("no widgets")),
        _resolve_agent_cl_name=lambda _agent: None,
    )


def test_extract_context_changespecs_tab_picks_selected_cs() -> None:
    cs0 = make_changespec(name="alpha", cl="123")
    cs1 = make_changespec(name="beta")
    app = _make_app_stub(
        tab="changespecs",
        changespecs=[cs0, cs1],
        current_idx=1,
        marked_indices={0, 1},
    )
    ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.tab == "artifacts"
    assert ctx.changespec is cs1
    assert ctx.agent is None
    assert ctx.axe_item is None
    assert ctx.mark_count == 2
    assert ctx.completed_agent_count == 0


def test_extract_context_changespecs_tab_handles_empty_list() -> None:
    app = _make_app_stub(tab="changespecs", changespecs=[], current_idx=0)
    ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.changespec is None
    assert ctx.mark_count == 0


def test_extract_context_agents_tab_uses_agents_state() -> None:
    agent = SimpleNamespace(status="DONE", attempt_history=[], response_path=None)
    other = SimpleNamespace(status="PLAN", attempt_history=[], response_path=None)
    marked = {("workflow", "x", None), ("workflow", "y", None)}
    app = _make_app_stub(
        tab="agents",
        agents=[agent, other],
        current_idx=0,
        marked_agents=marked,
        current_group_key=None,
        current_attempt_number=None,
    )
    ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.tab == "agents"
    assert ctx.agent is agent
    assert ctx.mark_count == 2
    assert ctx.completed_agent_count == 1
    assert ctx.stopped_agent_count == 1
    assert ctx.group_focused is False
    assert ctx.attempt_pinned is False


def test_extract_context_agents_tab_group_banner_focused() -> None:
    agent = SimpleNamespace(status="DONE", attempt_history=[], response_path=None)
    app = _make_app_stub(
        tab="agents",
        agents=[agent],
        current_idx=0,
        current_group_key=("running",),
        current_attempt_number=5,
    )
    ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.group_focused is True
    assert ctx.attempt_pinned is True


def test_extract_context_collapsed_panel_clears_hidden_backing_agent() -> None:
    backing = SimpleNamespace(
        status="RUNNING",
        attempt_history=[],
        response_path=None,
    )
    app = _make_app_stub(
        tab="agents",
        agents=[backing],
        current_idx=0,
    )
    app._get_selected_agent = lambda: None
    app._resolve_focused_collapsed_panel = lambda: object()

    ctx = extract_command_context(app)  # type: ignore[arg-type]

    assert ctx.agent is None
    assert ctx.panel_focused is True
    assert ctx.panel_collapsed is True
    assert ctx.collapsed_panel_focused is True
    assert ctx.group_focused is False


def test_extract_context_expanded_panel_clears_hidden_backing_agent() -> None:
    backing = SimpleNamespace(
        status="RUNNING",
        attempt_history=[],
        response_path=None,
    )
    app = _make_app_stub(
        tab="agents",
        agents=[backing],
        current_idx=0,
    )
    app._get_selected_agent = lambda: None
    app._resolve_focused_panel = lambda: SimpleNamespace(
        collapsed=False,
        panel_key="builders",
    )

    ctx = extract_command_context(app)  # type: ignore[arg-type]

    assert ctx.agent is None
    assert ctx.panel_focused is True
    assert ctx.panel_collapsed is False
    assert ctx.focused_panel_key == "builders"
    assert ctx.collapsed_panel_focused is False
    assert ctx.group_focused is False


def test_extract_context_axe_tab_lumberjack_row_is_not_done() -> None:
    items = [LumberjackItem(name="hooks")]
    app = _make_app_stub(
        tab="axe",
        axe_items=items,
        current_idx=0,
        axe_running=True,
    )
    ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.tab == "axe"
    assert isinstance(ctx.axe_item, LumberjackItem)
    assert ctx.axe_running is True
    # selected_axe_slot_done only tracks bgcmd rows.
    assert ctx.selected_axe_slot_done is False
    assert ctx.selected_axe_slot_running is False


def test_extract_context_axe_tab_done_bgcmd_marks_done() -> None:
    item = BgCmdItem(slot=2)
    app = _make_app_stub(
        tab="axe",
        axe_items=[item],
        current_idx=0,
        bgcmd_slots=[(2, SimpleNamespace())],
    )
    with patch("sase.ace.tui.bgcmd.is_slot_running", return_value=False):
        ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.selected_axe_slot_done is True
    assert ctx.selected_axe_slot_running is False


def test_extract_context_axe_tab_running_bgcmd_marks_running() -> None:
    item = BgCmdItem(slot=3)
    app = _make_app_stub(
        tab="axe",
        axe_items=[item],
        current_idx=0,
        bgcmd_slots=[(3, SimpleNamespace())],
    )
    with patch("sase.ace.tui.bgcmd.is_slot_running", return_value=True):
        ctx = extract_command_context(app)  # type: ignore[arg-type]
    assert ctx.selected_axe_slot_done is False
    assert ctx.selected_axe_slot_running is True


def test_completed_agent_count_includes_done_and_failed() -> None:
    agents = [
        SimpleNamespace(status="DONE"),
        SimpleNamespace(status="FAILED"),
        SimpleNamespace(status="PLAN DONE"),
        SimpleNamespace(status="RUNNING"),
        SimpleNamespace(status="PLAN"),
        SimpleNamespace(status="WAITING INPUT"),
    ]
    app = SimpleNamespace(_agents=agents)
    assert _completed_agent_count(app) == 3  # type: ignore[arg-type]


def test_stopped_agent_count_uses_stopped_status_bucket() -> None:
    agents = [
        SimpleNamespace(status="PLAN"),
        SimpleNamespace(status="QUESTION"),
        SimpleNamespace(status="DONE"),
        SimpleNamespace(status="FAILED"),
        SimpleNamespace(status="WAITING INPUT"),
        SimpleNamespace(status="RUNNING"),
    ]
    app = SimpleNamespace(_agents=agents)
    assert _stopped_agent_count(app) == 2  # type: ignore[arg-type]


def test_unread_completed_agent_count_includes_plan_done() -> None:
    done = SimpleNamespace(status="DONE", identity=("run", "done", None))
    plan_done = SimpleNamespace(status="PLAN DONE", identity=("run", "plan", None))
    running = SimpleNamespace(status="RUNNING", identity=("run", "running", None))
    app = SimpleNamespace(
        _agents=[done, plan_done, running],
        _unread_completed_agent_ids={
            done.identity,
            plan_done.identity,
            running.identity,
        },
    )

    assert _unread_completed_agent_count(app) == 2  # type: ignore[arg-type]


def test_selected_axe_slot_states_non_bgcmd_returns_false() -> None:
    app = SimpleNamespace(_bgcmd_slots=[])
    assert _selected_axe_slot_states(app, LumberjackItem(name="hooks")) == (  # type: ignore[arg-type]
        False,
        False,
    )
    assert _selected_axe_slot_states(app, None) == (False, False)  # type: ignore[arg-type]
