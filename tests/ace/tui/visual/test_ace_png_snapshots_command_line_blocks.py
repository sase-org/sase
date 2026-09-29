"""sase's TUI PNG visual snapshots for the ``:`` Command Line transcript blocks.

Pins the base panel states with fixture data and frozen context: empty,
typed line with ghost text, running block, success block, error block, and
submit-failed, plus block selection, expansion, earlier divider, declined,
denied, foreground, and help states.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.command_line.input import CommandLineInput
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_command_line_png_snapshot_shared import (
    open_command_line_panel,
    seed_command_line_block,
    seeded_command_line_panel,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_empty_120x40")],
)
async def test_command_line_empty_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            await seeded_command_line_panel(page, monkeypatch)
            assert_page_svg_contains(page, "Command Line")
            assert_page_svg_contains(page, "❯ sase")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_typed_ghost_120x40")],
)
async def test_command_line_typed_ghost_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.history import command_line as history_store

    seed = tmp_path / "command_line_history.json"
    with (
        patch.object(history_store, "_history_file_override", seed),
        history_store.locked_command_line_history(),
    ):
        history_store.record_command_line(
            "bead list --status open", cwd="/home/test/projects/sase", project="sase"
        )
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            await wait_for_startup(page)
            screen = await open_command_line_panel(page, monkeypatch, history_file=seed)
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead ")
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "bead")
            assert widget.suggestion == " list --status open"
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_running_120x40")],
)
async def test_command_line_running_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "agent wait research.2h --timeout 10m",
                status="running",
                tail_text="waiting for 3 agents (research.2h.mus, …) …\n",
                elapsed=42.0,
                proc_id="3aacsa99",
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "running 42s")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_success_120x40")],
)
async def test_command_line_success_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "bead list --status open",
                status="success",
                tail_text="sase-17x  epic  in_progress  Command Line\n",
                exit_code=0,
                elapsed=0.9,
                proc_id="470vtqab",
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "exit 0")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_error_120x40")],
)
async def test_command_line_error_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "bead close sase-zz",
                status="error",
                tail_text="error: no such bead: sase-zz\n",
                exit_code=2,
                elapsed=0.7,
                proc_id="9911ab02",
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "exit 2")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_submit_failed_120x40")],
)
async def test_command_line_submit_failed_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "bead list",
                status="submit_failed",
                error="supervisor unreachable",
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "submit failed")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_block_selected_120x40")],
)
async def test_command_line_block_selected_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "bead list --status open",
                status="success",
                tail_text="sase-17x  epic  in_progress  Command Line\n",
                exit_code=0,
                elapsed=0.9,
                proc_id="470vtqab",
                unseen=True,
            )
            seed_command_line_block(
                screen,
                "bead close sase-zz",
                status="error",
                tail_text="error: no such bead: sase-zz\n",
                exit_code=2,
                elapsed=0.7,
                proc_id="9911ab02",
                selected=True,
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "o expand")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_block_expanded_120x40")],
)
async def test_command_line_block_expanded_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "bead list --status open",
                status="success",
                tail_text="\n".join(f"line {index}" for index in range(14)) + "\n",
                exit_code=0,
                elapsed=0.9,
                proc_id="470vtqab",
                expanded=True,
                selected=True,
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "line 13")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_earlier_divider_120x40")],
)
async def test_command_line_earlier_divider_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "bead list --status open",
                status="success",
                tail_text="sase-17x  epic  in_progress  Command Line\n",
                exit_code=0,
                elapsed=0.9,
                proc_id="470vtqab",
            )
            seed_command_line_block(
                screen,
                "agent wait research.2h --timeout 10m",
                status="success",
                tail_text="done\n",
                exit_code=0,
                elapsed=61.2,
                proc_id="3aacsa99",
                restored=True,
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "earlier")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_declined_120x40")],
)
async def test_command_line_declined_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "agent restart research.2h.cld",
                status="error",
                tail_text="Restart would stop 1 agent and wipe 3 related agents.\n",
                exit_code=2,
                elapsed=0.4,
                proc_id="d3c11ned",
                declined=True,
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "declined")
            assert_page_svg_contains(page, "R rerun with -y")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_denied_120x40")],
)
async def test_command_line_denied_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "tui",
                status="denied",
                tail_text="You're already in the TUI\n",
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "not run")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_foreground_120x40")],
)
async def test_command_line_foreground_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "prompt edit",
                status="foreground",
                exit_code=0,
                elapsed=12.3,
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "ran in terminal")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_help_120x40")],
)
async def test_command_line_help_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await seeded_command_line_panel(page, monkeypatch)
            seed_command_line_block(
                screen,
                "help bead close",
                status="builtin",
                tail_text="bead close ‹ID…› [-n NOTE]\nClose beads.\n",
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "built-in")
            ace_png_visual.assert_page_png(page, snapshot_name)
