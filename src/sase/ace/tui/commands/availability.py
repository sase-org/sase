"""Pure applicability predicates for command palette entries.

The palette default-omits inapplicable commands. This module is the
import-compatible dispatcher for the per-tab predicate modules. Predicates
take a :class:`CommandSpec` and a :class:`CommandContext` and return a bool.

Tab scope is always checked here first. The tab-specific details live in:

- ``_availability_artifacts`` for Artifacts and Patch-row commands.
- ``_availability_agents`` for Agents-tab row and panel commands.
- ``_availability_axe`` for AXE-tab bgcmd/chop/lumberjack commands.

Predicates are intentionally conservative: when in doubt, the command stays
visible.
"""

from __future__ import annotations

from sase.ace.tui.commands._availability_agents import (
    agents_available as _agents_available,
)
from sase.ace.tui.commands._availability_artifacts import (
    artifacts_available as _patches_available,
)
from sase.ace.tui.commands._availability_axe import axe_available as _axe_available
from sase.ace.tui.commands.types import CommandContext, CommandSpec


def is_command_available(spec: CommandSpec, ctx: CommandContext) -> bool:
    """Return ``True`` if *spec* is runnable given *ctx*.

    Composes tab-scope filtering with per-tab entry predicates.
    Default: visible. Predicates only return ``False`` when a real
    precondition is violated.
    """
    if ctx.tab not in spec.tabs:
        return False
    if spec.id == "app.follow_artifact_link":
        return ctx.link_edges_present is not False

    if ctx.tab == "artifacts":
        return _patches_available(spec, ctx)
    if ctx.tab == "agents":
        return _agents_available(spec, ctx)
    if ctx.tab == "axe":
        return _axe_available(spec, ctx)

    return True
