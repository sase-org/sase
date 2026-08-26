"""AXE-tab applicability predicates for command palette entries."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.ace.tui.commands.types import CommandContext, CommandSpec

if TYPE_CHECKING:
    from sase.ace.tui.widgets.bgcmd_list import AxeItem


def _is_bgcmd(item: AxeItem | None) -> bool:
    if item is None:
        return False
    from sase.ace.tui.widgets.bgcmd_list import BgCmdItem

    return isinstance(item, BgCmdItem)


def _is_chop(item: AxeItem | None) -> bool:
    if item is None:
        return False
    from sase.ace.tui.widgets.bgcmd_list import ChopItem

    return isinstance(item, ChopItem)


def _is_lumberjack(item: AxeItem | None) -> bool:
    if item is None:
        return False
    from sase.ace.tui.widgets.bgcmd_list import LumberjackItem

    return isinstance(item, LumberjackItem)


def axe_available(spec: CommandSpec, ctx: CommandContext) -> bool:
    """Return whether an AXE-tab command is runnable."""
    item = ctx.axe_item

    # kill_agent label changes between start/stop axe and kill, but it's
    # always meaningful from the AXE tab.
    if spec.id == "app.kill_agent":
        return True

    if spec.id == "app.open_agent_cleanup_panel":
        return True

    if spec.id == "app.edit_spec":
        return _is_lumberjack(item) or _is_chop(item)

    if spec.id == "app.toggle_axe_description":
        return _is_lumberjack(item) or _is_chop(item)

    if spec.id == "app.edit_panel":
        return _is_chop(item) and ctx.selected_axe_chop_run_total > 0

    if spec.id == "app.add_axe_item":
        return True

    # Re-run is only available on a done bgcmd row.
    if spec.id == "app.run_workflow":
        if _is_bgcmd(item):
            return ctx.selected_axe_slot_done
        return (
            _is_chop(item)
            and ctx.selected_axe_chop_enabled
            and not ctx.selected_axe_chop_running
        )

    # Copy-mode axe commands need a focused row.
    if spec.id.startswith("copy.axe."):
        return item is not None

    # Most Patch/agent actions don't apply on AXE - they're already
    # filtered by spec.tabs, so this branch only sees commands that
    # listed "axe" in their tabs (mode prefixes, navigation, etc.).
    return True
