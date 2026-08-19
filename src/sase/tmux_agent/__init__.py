"""Catalog, launch-spec, and window-naming engine for the tmux Agent feature.

Shared by the ``sase tmux-agent`` CLI and the ACE Launch Control panel: both
front ends build the same :class:`~sase.tmux_agent.models.TmuxAgentCatalog`
through :func:`~sase.tmux_agent.catalog.build_tmux_agent_catalog` and render
it differently. Every module here is pure and injectable except
``catalog.py``, which does the (test-seamed) impure gathering.
"""

from .catalog import build_tmux_agent_catalog
from .keys import MenuKeyCandidate, assign_menu_keys
from .launch_spec import (
    InvocationOptionProvider,
    LaunchSpec,
    resolve_effort_level,
    resolve_launch_argv,
)
from .models import TmuxAgentCatalog, TmuxAgentEntry
from .window import next_window_name, renumber_plan

__all__ = [
    "InvocationOptionProvider",
    "LaunchSpec",
    "MenuKeyCandidate",
    "TmuxAgentCatalog",
    "TmuxAgentEntry",
    "assign_menu_keys",
    "build_tmux_agent_catalog",
    "next_window_name",
    "renumber_plan",
    "resolve_effort_level",
    "resolve_launch_argv",
]
