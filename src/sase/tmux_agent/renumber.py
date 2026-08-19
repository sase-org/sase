"""Apply the agent-window renumber plan through tmux."""

from __future__ import annotations

from sase.config.tmux_agent import TmuxAgentConfig

from .tmux import TmuxRunner
from .window import renumber_plan


def renumber_agent_windows(*, config: TmuxAgentConfig, runner: TmuxRunner) -> int:
    """Rename agent CLI windows so they read ``base``, ``base2``, ``base3``, …

    Idempotent: already-correct names are left alone. A no-op when nothing
    matches *config*'s window-name base. Returns the number of renames issued.
    """
    planned = renumber_plan(config.window_name, runner.list_windows())
    for index, new_name in planned:
        runner.rename_window(index, new_name)
    return len(planned)


__all__ = [
    "renumber_agent_windows",
]
