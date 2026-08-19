"""Catalog, launch-spec, window-naming, and tmux launch engine.

Shared by the ``sase tmux-agent`` CLI and the ACE Launch Control panel: both
front ends build the same :class:`~sase.tmux_agent.models.TmuxAgentCatalog`
through :func:`~sase.tmux_agent.catalog.build_tmux_agent_catalog` and launch
through :func:`~sase.tmux_agent.launch.launch_agent_window`. Catalog assembly
and window naming are pure; tmux calls go through :class:`TmuxRunner`.
"""

from .catalog import build_tmux_agent_catalog
from .keys import MenuKeyCandidate, assign_menu_keys
from .launch import TmuxAgentLaunch, TmuxAgentLaunchError, launch_agent_window
from .launch_spec import (
    InvocationOptionProvider,
    LaunchSpec,
    resolve_effort_level,
    resolve_launch_argv,
)
from .menu import build_display_menu_args, run_display_menu
from .models import TmuxAgentCatalog, TmuxAgentEntry
from .renumber import renumber_agent_windows
from .tmux import (
    TmuxRunner,
    inside_tmux,
    parse_tmux_version,
    tmux_agent_self_command,
    tmux_available,
)
from .window import next_window_name, renumber_plan

__all__ = [
    "InvocationOptionProvider",
    "LaunchSpec",
    "MenuKeyCandidate",
    "TmuxAgentCatalog",
    "TmuxAgentEntry",
    "TmuxAgentLaunch",
    "TmuxAgentLaunchError",
    "TmuxRunner",
    "assign_menu_keys",
    "build_display_menu_args",
    "build_tmux_agent_catalog",
    "inside_tmux",
    "launch_agent_window",
    "next_window_name",
    "parse_tmux_version",
    "renumber_agent_windows",
    "renumber_plan",
    "resolve_effort_level",
    "resolve_launch_argv",
    "run_display_menu",
    "tmux_agent_self_command",
    "tmux_available",
]
