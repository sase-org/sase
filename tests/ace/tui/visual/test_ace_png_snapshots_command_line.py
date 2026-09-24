"""sase's TUI PNG visual snapshots for the ``:`` Command Line panel shell.

Pins the base panel states with fixture data and frozen context: empty,
typed line with ghost text, running block, success block, error block, and
submit-failed. Grammar-driven states (popup, signature chips, diagnostics)
arrive with the completion-popup phase.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.ace.testing import AcePage, make_patch
from sase.ace.tui import AceApp
from sase.ace.tui.command_line.context import CommandLineContext
from sase.ace.tui.command_line.history import CommandLineHistory
from sase.ace.tui.command_line.input import CommandLineInput
from sase.ace.tui.command_line.screen import CommandLineScreen
from sase.ace.tui.command_line.session import command_line_session_for
from sase.feature_flags import override_flags
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_FROZEN_CONTEXT = CommandLineContext(cwd="/home/test/projects/sase", project="sase")


async def _open_panel(
    page: AcePage,
    monkeypatch: pytest.MonkeyPatch,
    *,
    history_file: object = None,
) -> CommandLineScreen:
    """Open the panel with frozen context/history and a stopped tail task."""
    monkeypatch.setattr(
        "sase.ace.tui.command_line.screen.resolve_working_context",
        lambda app, session: _FROZEN_CONTEXT,
    )
    if history_file is None:
        monkeypatch.setattr(CommandLineHistory, "refresh", lambda self: None)
    else:
        from sase.history import command_line as history_store

        monkeypatch.setattr(history_store, "_history_file_override", history_file)
    page.app.action_open_command_line()
    await wait_for_visual_idle(page)
    screen = page.app.screen
    assert isinstance(screen, CommandLineScreen)
    screen.transcript.stop_tail_task()
    await wait_for_visual_idle(page)
    return screen


def _seed_block(
    screen: CommandLineScreen,
    line: str,
    *,
    status: str,  # type: ignore[valid-type]
    tail_text: str = "",
    exit_code: int | None = None,
    elapsed: float | None = None,
    proc_id: str | None = None,
    error: str | None = None,
    expanded: bool = False,
    restored: bool = False,
    unseen: bool = False,
    selected: bool = False,
) -> None:
    session = command_line_session_for(screen.app)
    block = session.add_block(line)
    block.status = status  # type: ignore[assignment]
    block.tail_text = tail_text
    block.exit_code = exit_code
    block.elapsed = elapsed
    block.proc_id = proc_id
    block.error = error
    block.expanded = expanded
    block.restored = restored
    block.unseen = unseen
    if selected:
        session.select_block(block.block_id)
    screen.refresh_transcript()


async def _seeded_panel(
    page: AcePage, monkeypatch: pytest.MonkeyPatch
) -> CommandLineScreen:
    await wait_for_startup(page)
    return await _open_panel(page, monkeypatch)


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
        override_flags(ace_command_line=True),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            await _seeded_panel(page, monkeypatch)
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
    tmp_path,  # noqa: ANN001
) -> None:
    from sase.history import command_line as history_store

    seed = tmp_path / "command_line_history.json"
    history_store.set_command_line_history_file(seed)
    with history_store.locked_command_line_history():
        history_store.record_command_line(
            "bead list --status open", cwd="/home/test/projects/sase", project="sase"
        )
    history_store.set_command_line_history_file(None)
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
        override_flags(ace_command_line=True),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            await wait_for_startup(page)
            screen = await _open_panel(page, monkeypatch, history_file=seed)
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
        override_flags(ace_command_line=True),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
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
        override_flags(ace_command_line=True),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
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
        override_flags(ace_command_line=True),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
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
        override_flags(ace_command_line=True),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
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
        override_flags(ace_command_line=True),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
                screen,
                "bead list --status open",
                status="success",
                tail_text="sase-17x  epic  in_progress  Command Line\n",
                exit_code=0,
                elapsed=0.9,
                proc_id="470vtqab",
                unseen=True,
            )
            _seed_block(
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
        override_flags(ace_command_line=True),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
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
            assert_page_svg_contains(page, "line 0")
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
        override_flags(ace_command_line=True),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
                screen,
                "bead list --status open",
                status="success",
                tail_text="sase-17x  epic  in_progress  Command Line\n",
                exit_code=0,
                elapsed=0.9,
                proc_id="470vtqab",
            )
            _seed_block(
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
