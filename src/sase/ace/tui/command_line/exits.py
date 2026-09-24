"""Exit-completion delivery for Command Line blocks.

The proc observer settles command-line procs from their store rows and
delivers :class:`ProcExitCompletion` records on the snapshot. This module
routes one completion into the app-held session: the block settles, the
submission is recorded in history, and the visible panel repaints.
Completion toasts while hidden arrive in the transcript-blocks phase; here
the block is marked unseen so the dot is ready.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sase.ace.tui.command_line.session import command_line_session_for
from sase.ace.tui.command_line.submit import apply_exit_completion


def deliver_command_line_exit(app: Any, completion: Any) -> bool:
    """Settle the block for one exit completion; True when it was ours."""
    session = command_line_session_for(app)
    block = session.block_for_proc(completion.proc_id)
    if block is None:
        return False
    apply_exit_completion(
        block,
        exit_code=completion.exit_code,
        status=completion.status,
    )
    block.unseen = not _panel_visible(app)
    _drop_tail_token(app, block.block_id)
    _record_history_async(app, block)
    _repaint_panel(app)
    return True


def _panel_visible(app: Any) -> bool:
    from sase.ace.tui.command_line.screen import CommandLineScreen

    try:
        return isinstance(app.screen, CommandLineScreen)
    except Exception:  # noqa: BLE001 - screen reads always degrade.
        return False


def _drop_tail_token(app: Any, block_id: str) -> None:
    from sase.ace.tui.command_line.screen import CommandLineScreen

    try:
        screen = app.screen
    except Exception:  # noqa: BLE001 - screen reads always degrade.
        return
    if not isinstance(screen, CommandLineScreen):
        return
    token = screen._tail_tokens.pop(block_id, None)
    if token is None:
        return
    observer = getattr(app, "_proc_observer", None)
    unsubscribe = getattr(observer, "unsubscribe_tail", None)
    if callable(unsubscribe):
        try:
            unsubscribe(token)
        except Exception:  # noqa: BLE001 - cleanup is best effort.
            pass


def _record_history_async(app: Any, block: Any) -> None:
    async def _record() -> None:
        from sase.ace.tui.command_line.context import resolve_working_context
        from sase.history.command_line import (
            locked_command_line_history,
            record_command_line,
        )

        session = command_line_session_for(app)
        context = await asyncio.to_thread(resolve_working_context, app, session)

        def _write() -> None:
            with locked_command_line_history():
                record_command_line(
                    block.line,
                    cwd=context.cwd,
                    project=context.project,
                    exit_code=block.exit_code,
                )

        await asyncio.to_thread(_write)

    run_worker = getattr(app, "run_worker", None)
    if callable(run_worker):
        try:
            run_worker(_record(), exclusive=False)
        except Exception:  # noqa: BLE001 - history is best effort.
            pass


def _repaint_panel(app: Any) -> None:
    from sase.ace.tui.command_line.screen import CommandLineScreen

    try:
        screen = app.screen
    except Exception:  # noqa: BLE001 - screen reads always degrade.
        return
    if isinstance(screen, CommandLineScreen):
        try:
            screen.refresh_transcript()
        except Exception:  # noqa: BLE001 - repaint is best effort.
            pass


__all__ = ["deliver_command_line_exit"]
