"""Toast and Procs-routing tests for transcript blocks.

Completion toasts while hidden and the Procs ``⏎`` routing back to a
block for the ``:`` Command Line transcript.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.command_line.exits import (
    _completion_toast_text,
    deliver_command_line_exit,
)
from sase.ace.tui.command_line.session import CommandLineBlock
from sase.ace.tui.modals.procs_pane_agent_jump import (
    _is_command_line_row,
    _open_command_line_on_block,
)

__all__ = [
    "test_completion_toast_omits_hint_while_unbound",
    "test_completion_toast_text_success_and_failure",
    "test_deliver_exit_toasts_when_hidden_and_marks_unseen",
    "test_is_command_line_row_checks_tag",
    "test_open_command_line_on_block_reports_pruned",
    "test_open_command_line_on_block_selects_existing",
    "test_procs_enter_routes_command_line_rows_to_panel",
]


def _exit_app(**overrides: Any) -> SimpleNamespace:
    app = SimpleNamespace(screen=object())
    for key, value in overrides.items():
        setattr(app, key, value)
    return app


def test_completion_toast_text_success_and_failure() -> None:
    """Hidden finishes toast with exit metadata and the live ``:`` hint."""
    app = _exit_app(
        _keymap_registry=SimpleNamespace(app=SimpleNamespace(open_command_line="colon"))
    )
    done = CommandLineBlock(block_id="b1", line="bead list")
    done.status = "success"
    done.exit_code = 0
    done.elapsed = 0.9
    assert (
        _completion_toast_text(app, done) == "✓ bead list · exit 0 · 0.9s — : to view"
    )

    failed = CommandLineBlock(block_id="b2", line="bead close sase-zz")
    failed.status = "error"
    failed.exit_code = 2
    failed.elapsed = 0.7
    assert "✗ bead close sase-zz · exit 2 · 0.7s" in _completion_toast_text(app, failed)


def test_completion_toast_omits_hint_while_unbound() -> None:
    """The ``to view`` hint disappears while the panel key is unbound."""
    app = _exit_app(
        _keymap_registry=SimpleNamespace(
            app=SimpleNamespace(open_command_line="unbound")
        )
    )
    done = CommandLineBlock(block_id="b1", line="bead list")
    done.status = "success"
    done.exit_code = 0
    text = _completion_toast_text(app, done)
    assert "to view" not in text
    assert text.startswith("✓ bead list")


def test_deliver_exit_toasts_when_hidden_and_marks_unseen() -> None:
    """A finish while hidden toasts at error severity and dots the block."""
    from sase.ace.tui.command_line.session import command_line_session_for

    notices: list[tuple[str, str]] = []
    app = _exit_app(
        notify=lambda message, **kwargs: notices.append(
            (message, kwargs.get("severity", ""))
        ),
        _keymap_registry=SimpleNamespace(
            app=SimpleNamespace(open_command_line="colon")
        ),
    )
    session = command_line_session_for(app)
    block = session.add_block("bead close sase-zz")
    block.proc_id = "proc-1"
    block.status = "running"
    completion = SimpleNamespace(proc_id="proc-1", exit_code=2, status="done")
    assert deliver_command_line_exit(app, completion) is True
    assert block.status == "error"
    assert block.unseen is True
    assert len(notices) == 1
    assert notices[0][1] == "error"
    assert "✗ bead close sase-zz" in notices[0][0]


# -- Procs-pane routing ---------------------------------------------------------------


def test_is_command_line_row_checks_tag() -> None:
    """Only ``command-line``-tagged rows divert Procs ``⏎`` to the panel."""
    assert _is_command_line_row(SimpleNamespace(tags=("command-line",))) is True
    assert _is_command_line_row(SimpleNamespace(tags=())) is False
    assert _is_command_line_row(SimpleNamespace(tags=None)) is False


def test_open_command_line_on_block_reports_pruned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pruned jump still opens the panel and warns."""
    import sase.ace.tui.command_line.restore as restore_module

    opened: list[str] = []
    notices: list[str] = []
    app = SimpleNamespace(
        action_open_command_line=lambda: opened.append("panel"),
        notify=lambda message, **kwargs: notices.append(message),
    )
    monkeypatch.setattr(restore_module, "ensure_block_for_proc", lambda s, p: None)
    assert _open_command_line_on_block(app, "gone") is False
    assert opened == ["panel"]
    assert notices == ["Proc record pruned"]
    from sase.ace.tui.command_line.session import command_line_session_for

    assert command_line_session_for(app).focus_block_proc_id == "gone"


def test_open_command_line_on_block_selects_existing() -> None:
    """A jump to a known block opens the panel without a warning."""
    from sase.ace.tui.command_line.session import command_line_session_for

    opened: list[str] = []
    app = SimpleNamespace(
        action_open_command_line=lambda: opened.append("panel"),
        notify=lambda message, **kwargs: (_ for _ in ()).throw(
            AssertionError("no warning expected")
        ),
    )
    session = command_line_session_for(app)
    block = session.add_block("bead show p1")
    block.proc_id = "p1"
    assert _open_command_line_on_block(app, "p1") is True
    assert opened == ["panel"]
    assert session.focus_block_proc_id == "p1"


def test_procs_enter_routes_command_line_rows_to_panel() -> None:
    """``⏎`` on a command-line row opens the block; other rows keep routing."""
    from sase.ace.tui.modals.procs_pane_agent_jump import ProcsPaneAgentJumpMixin

    calls: list[str] = []

    class _StubPane(ProcsPaneAgentJumpMixin):
        jump_mode_active = False

        def __init__(self, task: Any) -> None:
            self._task = task

        def _get_selected_task(self) -> Any:
            return self._task

        def action_open_command_line_block(self) -> None:
            calls.append("block")

        def action_open_monitor_agent(self) -> None:
            calls.append("agent")

    event: Any = SimpleNamespace(stopped=False)
    event.stop = lambda: setattr(event, "stopped", True)
    _StubPane(SimpleNamespace(tags=("command-line",))).on_option_list_option_selected(
        event
    )
    assert calls == ["block"]
    assert event.stopped is True

    _StubPane(
        SimpleNamespace(tags=(), origin="ace", proc_id="p1")
    ).on_option_list_option_selected(event)
    assert calls == ["block", "agent"]
