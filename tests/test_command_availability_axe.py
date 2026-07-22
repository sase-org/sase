"""Command palette applicability predicates for the Axe tab."""

from __future__ import annotations

from sase.ace.tui.commands import CommandContext, is_command_available
from sase.ace.tui.widgets.bgcmd_list import BgCmdItem, ChopItem, LumberjackItem
from tests._command_availability_helpers import catalog_by_id as _catalog_by_id


def test_axe_run_workflow_only_on_done_bgcmd_row() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.run_workflow"]
    lumberjack_ctx = CommandContext(tab="axe", axe_item=LumberjackItem(name="hooks"))
    bgcmd_running = CommandContext(
        tab="axe",
        axe_item=BgCmdItem(slot=1),
        selected_axe_slot_done=False,
    )
    bgcmd_done = CommandContext(
        tab="axe",
        axe_item=BgCmdItem(slot=1),
        selected_axe_slot_done=True,
    )
    assert not is_command_available(spec, lumberjack_ctx)
    assert not is_command_available(spec, bgcmd_running)
    assert is_command_available(spec, bgcmd_done)


def test_axe_config_edit_and_output_edit_have_distinct_availability() -> None:
    catalog = _catalog_by_id()
    config_edit = catalog["app.edit_spec"]
    output_edit = catalog["app.edit_panel"]
    lumberjack_ctx = CommandContext(tab="axe", axe_item=LumberjackItem(name="hooks"))
    bgcmd_ctx = CommandContext(tab="axe", axe_item=BgCmdItem(slot=1))
    chop_without_runs = CommandContext(
        tab="axe",
        axe_item=ChopItem(lumberjack_name="hooks", chop_name="fast"),
        selected_axe_chop_run_total=0,
    )
    chop_with_runs = CommandContext(
        tab="axe",
        axe_item=ChopItem(lumberjack_name="hooks", chop_name="fast"),
        selected_axe_chop_run_total=1,
    )
    assert is_command_available(config_edit, lumberjack_ctx)
    assert not is_command_available(config_edit, bgcmd_ctx)
    assert is_command_available(config_edit, chop_without_runs)
    assert is_command_available(config_edit, chop_with_runs)
    assert not is_command_available(output_edit, lumberjack_ctx)
    assert not is_command_available(output_edit, bgcmd_ctx)
    assert not is_command_available(output_edit, chop_without_runs)
    assert is_command_available(output_edit, chop_with_runs)


def test_axe_run_workflow_excludes_disabled_and_running_chops() -> None:
    spec = _catalog_by_id()["app.run_workflow"]
    chop = ChopItem(lumberjack_name="hooks", chop_name="fast")
    assert is_command_available(
        spec,
        CommandContext(
            tab="axe",
            axe_item=chop,
            selected_axe_chop_enabled=True,
            selected_axe_chop_running=False,
        ),
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="axe", axe_item=chop, selected_axe_chop_enabled=False),
    )
    assert not is_command_available(
        spec,
        CommandContext(tab="axe", axe_item=chop, selected_axe_chop_running=True),
    )


def test_axe_kill_agent_always_meaningful() -> None:
    catalog = _catalog_by_id()
    spec = catalog["app.kill_agent"]
    no_item_ctx = CommandContext(tab="axe", axe_item=None)
    bgcmd_ctx = CommandContext(tab="axe", axe_item=BgCmdItem(slot=1))
    lumberjack_ctx = CommandContext(tab="axe", axe_item=LumberjackItem(name="hooks"))
    assert is_command_available(spec, no_item_ctx)
    assert is_command_available(spec, bgcmd_ctx)
    assert is_command_available(spec, lumberjack_ctx)


def test_copy_axe_visible_requires_focused_row() -> None:
    catalog = _catalog_by_id()
    spec = catalog["copy.axe.visible"]
    no_item = CommandContext(tab="axe", axe_item=None)
    with_item = CommandContext(tab="axe", axe_item=BgCmdItem(slot=1))
    assert not is_command_available(spec, no_item)
    assert is_command_available(spec, with_item)
