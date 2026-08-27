"""ACE TUI PNG visual snapshot for the ``:`` command palette."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.commands import CommandExecutor, CommandSpec
from sase.ace.tui.modals.command_palette_modal import CommandPaletteModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _spec(
    spec_id: str,
    label: str,
    key_display: str,
    category: str,
    *,
    aliases: tuple[str, ...] = (),
) -> CommandSpec:
    return CommandSpec(
        id=spec_id,
        label=label,
        key_sequence=(key_display.lower(),),
        key_display=key_display,
        category=category,  # type: ignore[arg-type]
        tabs=("agents",),
        executor=CommandExecutor(kind="app_action", action="refresh"),
        aliases=aliases,
    )


def _palette_specs() -> list[CommandSpec]:
    return [
        _spec("app.next_agent", "Next agent", "j", "Navigation"),
        _spec("app.prev_agent", "Previous agent", "k", "Navigation"),
        _spec("app.new_agent", "New agent", "%n", "Agents"),
        _spec("app.retry_agent", "Retry selected agent", "%r", "Agents"),
        _spec("app.open_workspace", "Open agent workspace", ",w", "Workspace"),
        _spec("app.copy_name", "Copy agent name", "y n", "Copy"),
        _spec("app.toggle_files", "Toggle file panel", "F", "Display"),
        _spec("leader.agent_run_log", "Agent run log", ",A", "Leader"),
    ]


async def test_command_palette_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(CommandPaletteModal(specs=_palette_specs(), tab="agents"))
        await page.expect_modal("CommandPaletteModal")
        await page.press("down", "down", "down", "down")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "command_palette_default_120x40",
            title="ACE : command palette pop-up",
        )
