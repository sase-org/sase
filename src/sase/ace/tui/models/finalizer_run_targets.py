"""Run targets for the finalizer node view (TUI side).

Adapts agent rows into :class:`RunTarget` records for the TUI-agnostic
collector in ``sase.finalizers.run_view_inputs``. All TUI imports stay
inside the helper so the collector module keeps its no-TUI-imports
guarantee.
"""

from __future__ import annotations

import os
from typing import Any

from sase.finalizers.run_view_inputs import RunnerIdentity, RunTarget

__all__ = ["node_run_targets"]


def _target_for(
    turn: Any,
    *,
    number: int,
    artifacts_dir: str | None,
) -> RunTarget:
    """Build one :class:`RunTarget` from a concrete turn row."""
    identity = getattr(turn, "identity", None)
    if identity is not None:
        from sase.ace.tui.widgets.decks.card_block import card_block_id

        run_id = card_block_id(identity)
    else:
        run_id = str(getattr(turn, "agent_name", "agent turn"))
    summary = getattr(turn, "finalizer_status", None)
    summary_runner = getattr(summary, "runner", None) if summary is not None else None
    runner: RunnerIdentity | None = None
    if summary_runner is not None:
        runner = RunnerIdentity(
            pid=getattr(summary_runner, "pid", None),
            identity=getattr(summary_runner, "identity", None),
        )
    kind = "monitor" if bool(getattr(turn, "is_monitor", False)) else "agent"
    status = getattr(turn, "status", "RUNNING")
    return RunTarget(
        run_id=run_id,
        artifacts_dir=artifacts_dir,
        number=number,
        label=str(getattr(turn, "agent_name", None) or "agent turn"),
        kind=kind,
        turn_terminal=status != "RUNNING",
        runner=runner,
    )


def node_run_targets(
    agent: Any, attempt_number: int | None = None
) -> tuple[RunTarget, ...]:
    """Return one :class:`RunTarget` per concrete shell for *agent*.

    A lone turn gives one target. A session container gives its concrete
    turns in roster order (``concrete_agent_session_turn_rows`` with
    ``number`` as the roster index, matching Reply's rail). A pinned prior
    attempt (``D``) gives that attempt's dir
    (``<artifacts>/attempts/<N>``); prior-attempt snapshots predate
    finalizer artifacts, so those targets typically project as
    ``unavailable``.
    """
    from sase.ace.tui.models.agent_session_members import (
        concrete_agent_session_turn_rows,
        is_sequential_agent_session_container,
    )
    from sase.ace.tui.models.artifact_files import get_artifacts_dir

    if attempt_number is not None:
        try:
            base = get_artifacts_dir(agent)
        except Exception:
            base = getattr(agent, "artifacts_dir", None)
        pinned = (
            os.path.join(str(base), "attempts", str(attempt_number)) if base else None
        )
        return (_target_for(agent, number=0, artifacts_dir=pinned),)

    members: tuple[Any, ...] = ()
    try:
        if is_sequential_agent_session_container(agent):
            members = concrete_agent_session_turn_rows(agent)
    except Exception:
        members = ()
    if not members:
        try:
            artifacts_dir = get_artifacts_dir(agent)
        except Exception:
            artifacts_dir = getattr(agent, "artifacts_dir", None)
        return (_target_for(agent, number=0, artifacts_dir=artifacts_dir),)
    targets: list[RunTarget] = []
    for number, turn in enumerate(members):
        try:
            turn_dir = get_artifacts_dir(turn)
        except Exception:
            turn_dir = getattr(turn, "artifacts_dir", None)
        targets.append(_target_for(turn, number=number, artifacts_dir=turn_dir))
    return tuple(targets)
