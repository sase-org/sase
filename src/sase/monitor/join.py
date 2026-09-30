"""Validation for ``sase monitor start -J/--join RUN``.

A join adopts an existing starter-scoped detached ToolRun into a new
monitor without starting another run. The run's executing proc stays the
owner; the monitor only follows it. Every refusal here happens before the
slow lane work and before the in-flight handoff marker, so a refused join
never disturbs the lane.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JoinRefusal:
    """A rejected join: the exit code and the stderr message."""

    exit_code: int
    message: str


@dataclass(frozen=True)
class JoinTarget:
    """A detached run a monitor may join."""

    run_id: str
    tool_name: str
    command: str
    caller_agent: str
    run: dict[str, Any]


def join_caller_agent() -> str | None:
    """Return the joining agent's name, or ``None`` outside an agent."""

    if not str(os.environ.get("SASE_AGENT") or "").strip():
        return None
    caller = str(os.environ.get("SASE_AGENT_NAME") or "").strip()
    return caller or None


def _canonical_join_words(run: dict[str, Any]) -> list[str]:
    """Return the canonical ``sase tool run`` words that started *run*.

    The ``show`` view projects no launch envelope, only ``tool_name`` (for
    named runs) and the redacted ``display_argv``. Named runs therefore
    replay the tool name; ad-hoc runs replay the recorded argv verbatim
    after ``--``. The words are display and request identity only: a join
    never re-runs the command.
    """

    tool_name = str(run.get("tool_name") or "").strip()
    if tool_name:
        return [tool_name]
    display = run.get("display_argv")
    argv = [str(part) for part in display] if isinstance(display, list) else []
    return ["--", *argv]


def _join_display_command(run: dict[str, Any]) -> str:
    """Return the display ``sase tool run ...`` command for a joined run."""

    words = _canonical_join_words(run)
    return " ".join(shlex.quote(part) for part in ["sase", "tool", "run", *words])


def _join_tool_name(run: dict[str, Any]) -> str:
    """Return the tool name printed in join labels and reasons."""

    name = str(run.get("tool_name") or "").strip()
    return name or "ad-hoc"


def default_join_label(run: dict[str, Any]) -> str:
    """Return the default monitor label for a joined run."""

    return f"tool:{_join_tool_name(run)} (joined)"


def default_join_reason(run: dict[str, Any]) -> str:
    """Return the default monitor reason for a joined run."""

    return f"finish {_join_tool_name(run)} (joined run)"


def show_pointer(run_id: str) -> str:
    """Return the ``sase tool show`` pointer for a refused join."""

    return f"sase tool show {run_id}"


def inspect_join_target(run_id: str, caller: str) -> JoinTarget | JoinRefusal:
    """Inspect *run_id* for a join by *caller*.

    Shape and ownership problems (unknown run, not detached, another
    agent's run) are exit ``2``; settled, stopped, and joined-elsewhere
    races are exit ``1`` with the run's state and a ``sase tool show``
    pointer. No monitor starts on any refusal.
    """

    from sase.core.tool_run import tool_run_show

    try:
        envelope = tool_run_show(run_id)
    except Exception as exc:  # noqa: BLE001 - query failures refuse the join.
        return JoinRefusal(exit_code=2, message=f"sase monitor start -J: {exc}")
    run = envelope.get("run")
    if not isinstance(run, dict):
        diagnostic = "; ".join(str(item) for item in envelope.get("diagnostics") or ())
        return JoinRefusal(
            exit_code=2,
            message=(
                f"sase monitor start -J: {diagnostic or f'tool run {run_id} was not found'}"
            ),
        )
    starter = run.get("starter")
    if not isinstance(starter, dict) or not str(starter.get("agent") or ""):
        return JoinRefusal(
            exit_code=2,
            message=(
                f"sase monitor start -J: tool run {run_id} is not a detached run "
                "(it has no starter scope); only starter-scoped detached runs "
                "can be joined"
            ),
        )
    if str(starter.get("agent") or "") != caller:
        return JoinRefusal(
            exit_code=2,
            message=(
                f"sase monitor start -J: tool run {run_id} belongs to agent "
                f"{str(starter.get('agent'))!r}, not {caller!r}"
            ),
        )
    state = str(run.get("state") or "")
    if state not in ("created", "running"):
        return JoinRefusal(
            exit_code=1,
            message=(
                f"sase monitor start -J: tool run {run_id} is already {state}; "
                f"nothing to join ({show_pointer(run_id)})"
            ),
        )
    if run.get("stop_request") is not None:
        return JoinRefusal(
            exit_code=1,
            message=(
                f"sase monitor start -J: tool run {run_id} already has a stop "
                f"request; nothing to join ({show_pointer(run_id)})"
            ),
        )
    join = run.get("join")
    if (
        isinstance(join, dict)
        and str(join.get("kind") or "")
        and str(join.get("id") or "")
    ):
        return JoinRefusal(
            exit_code=1,
            message=(
                f"sase monitor start -J: tool run {run_id} is already joined by "
                f"{join.get('kind')} {join.get('id')}; nothing to join "
                f"({show_pointer(run_id)})"
            ),
        )
    return JoinTarget(
        run_id=run_id,
        tool_name=_join_tool_name(run),
        command=_join_display_command(run),
        caller_agent=caller,
        run=run,
    )


__all__ = [
    "JoinRefusal",
    "JoinTarget",
    "default_join_label",
    "default_join_reason",
    "inspect_join_target",
    "join_caller_agent",
    "show_pointer",
]
