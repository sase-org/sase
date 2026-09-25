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
    visible = _panel_visible(app)
    block.unseen = not visible
    _drop_tail_token(app, block.block_id)
    _record_history_async(app, block)
    if not visible:
        _toast_completion(app, block)
    _invalidate_provider_cache(app)
    _repaint_panel(app)
    return True


def _completion_toast_text(app: Any, block: Any) -> str:
    """Build the hidden-finish toast for a settled block (pure)."""
    glyph = "✓" if block.status == "success" else "✗"
    parts: list[str] = []
    if block.exit_code is not None:
        parts.append(f"exit {block.exit_code}")
    if block.elapsed is not None:
        parts.append(f"{block.elapsed:.1f}s")
    message = f"{glyph} {block.line}"
    if parts:
        message += f" · {' · '.join(parts)}"
    hint = _command_line_open_hint(app)
    if hint:
        message += f" — {hint} to view"
    return message


def _toast_completion(app: Any, block: Any) -> None:
    """Raise a completion toast; failures toast at error severity."""
    notify = getattr(app, "notify", None)
    if not callable(notify):
        return
    severity = "information" if block.status == "success" else "error"
    try:
        notify(_completion_toast_text(app, block), severity=severity)
    except Exception:  # noqa: BLE001 - toasts are best effort.
        pass


def _command_line_open_hint(app: Any) -> str:
    """Return the live ``open_command_line`` key name, or "" while unbound."""
    try:
        registry = getattr(app, "_keymap_registry", None)
        key = getattr(getattr(registry, "app", None), "open_command_line", "unbound")
        from sase.ace.tui.keymaps.display import key_display_name

        return key_display_name(key or "unbound")
    except Exception:  # noqa: BLE001 - hint reads always degrade.
        return ""


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


def _invalidate_provider_cache(app: Any) -> None:
    """Forget cached completion rows: the finished command may have changed them.

    ``plan approve X`` followed by ``plan approve <Tab>`` must not still offer
    ``X``. A hidden panel has no cache to clear; a reopened one starts empty.
    """
    from sase.ace.tui.command_line.screen import CommandLineScreen

    try:
        screen = app.screen
    except Exception:  # noqa: BLE001 - screen reads always degrade.
        return
    if isinstance(screen, CommandLineScreen):
        try:
            screen.invalidate_provider_cache()
        except Exception:  # noqa: BLE001 - invalidation is best effort.
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
