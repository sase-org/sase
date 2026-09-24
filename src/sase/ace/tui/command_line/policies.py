"""Run-policy routing for the ``:`` Command Line panel (run-policies phase).

At submit time the panel reads the resolver's ``LineContext.run_policy``:

- ``proc`` (default): submit as an ordinary tagged proc (existing path).
- ``foreground``: suspend the TUI and run in the real terminal, then add a
  ``↗ ran in terminal · exit N`` block. No proc is created.
- ``deny``: add a ``⊘ not run`` block containing the policy note, and record
  nothing (no history entry).

Confirmation-aware blocks: when ``confirms`` is true, ``-y/--yes`` was
absent, and the exit code is non-zero, the block is marked ``declined`` and
``R`` reruns the line with ``-y`` appended visibly, as a new block.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any, Literal

from sase.completion.command_line_grammar import LineContext

SubmitRoute = Literal["proc", "foreground", "deny"]

#: Pattern matching a ``-y``/``--yes`` flag already present on a line.
_CONFIRM_FLAG_RE = re.compile(r"(?:^|\s)(?:-y|--yes)(?:\s|$|=)")


def submit_route_for(context: LineContext | None) -> SubmitRoute:
    """Return the submit route for a resolver context (``proc`` by default)."""
    if not context:
        return "proc"
    policy = str((context.get("run_policy") or {}).get("policy", "") or "proc")
    if policy in ("proc", "foreground", "deny"):
        return policy  # type: ignore[return-value]
    return "proc"


def deny_note_for(context: LineContext | None) -> str:
    """Return the deny-policy note for a block body, never blank."""
    if context:
        note = str((context.get("run_policy") or {}).get("note", "") or "").strip()
        if note:
            return note
    return "not runnable from the Command Line"


def run_in_terminal(
    app: Any,
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str] | None = None,
) -> int:
    """Run *argv* in the real terminal with the TUI suspended.

    Follows ``modals/xprompt_select_modal.py``: ``app.suspend()`` hands the
    terminal back, then ``subprocess.run`` executes synchronously. Returns
    the process exit code. Raises ``OSError`` when the spawn fails.
    """
    with app.suspend():
        completed = subprocess.run(argv, cwd=cwd or None, env=env, check=False)
    return completed.returncode


def append_confirm_flag(line: str) -> str:
    """Append ``-y`` visibly unless the line already carries ``-y``/``--yes``."""
    if _CONFIRM_FLAG_RE.search(line) is None:
        return f"{line} -y"
    return line


def is_confirmation_declined(
    *,
    confirms: bool,
    confirm_flag_present: bool,
    exit_code: int | None,
) -> bool:
    """Return True when a finished block is a confirmation decline.

    A decline is a command that asks to confirm, ran without ``-y``/``--yes``,
    and exited non-zero (the CLI's safety prompts fail closed on ``/dev/null``
    stdin, so the denial text is the command's own output).
    """
    return bool(confirms and not confirm_flag_present and (exit_code or 0) != 0)


__all__ = [
    "SubmitRoute",
    "append_confirm_flag",
    "deny_note_for",
    "is_confirmation_declined",
    "run_in_terminal",
    "submit_route_for",
]
