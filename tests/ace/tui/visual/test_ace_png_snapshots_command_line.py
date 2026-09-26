"""sase's TUI PNG visual snapshots for the ``:`` Command Line panel shell.

Pins the base panel states with fixture data and frozen context: empty,
typed line with ghost text, running block, success block, error block, and
submit-failed. Grammar-driven states (popup, signature chips, diagnostics)
arrive with the completion-popup phase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.testing import AcePage, make_patch
from sase.ace.tui import AceApp
from sase.ace.tui.command_line.context import CommandLineContext
from sase.ace.tui.command_line.input import CommandLineInput
from sase.ace.tui.command_line.screen import CommandLineScreen
from sase.ace.tui.command_line.session import command_line_session_for
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    assert_page_svg_styled_text_contains,
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
    # These snapshots either supply a frozen resolver response or explicitly
    # model the pre-grammar indexing state. Starting the real grammar builder
    # here would leave its host-dependent ``_load`` worker in flight and make
    # render convergence depend on a subprocess that the snapshot cannot show.
    monkeypatch.setattr(
        "sase.ace.tui.command_line.screen.ensure_command_line_grammar_loaded",
        lambda app, *, on_ready=None: False,
    )
    if history_file is not None:
        from sase.history import command_line as history_store

        monkeypatch.setattr(history_store, "_history_file_override", history_file)
    # Treat the one-time palette tip as already shown. The real marker read
    # lands from an off-thread worker, so whether the tip or a later hint
    # owns the hint row at capture time would otherwise depend on host load.
    command_line_session_for(page.app).palette_tip_show = False
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
    declined: bool = False,
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
    block.declined = declined
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


def _seed_history_file(tmp_path: Path, *lines: str) -> Path:
    """Record *lines* into an isolated history file and return its path."""
    from sase.history import command_line as history_store

    seed = tmp_path / "command_line_history.json"
    with (
        patch.object(history_store, "_history_file_override", seed),
        history_store.locked_command_line_history(),
    ):
        for line in lines:
            history_store.record_command_line(
                line, cwd="/home/test/projects/sase", project="sase"
            )
    return seed


def _extras_help_lookup(path: list[str]) -> dict[str, Any] | None:
    """Tiny fake help tree for extras goldens (no grammar handle needed)."""
    bead_id = {
        "metavar": "ID",
        "dest": "id",
        "required": True,
        "value_kind": "bead",
        "choices": None,
    }
    tree: dict[tuple[str, ...], dict[str, Any]] = {
        (): {"children": [{"name": "bead"}], "positionals": [], "options": []},
        ("bead",): {
            "children": [{"name": "close"}],
            "positionals": [],
            "options": [],
        },
        ("bead", "close"): {
            "usage": "sase bead close ‹ID…› [-n NOTE]",
            "summary": "Close a bead",
            "positionals": [bead_id],
            "options": [],
            "children": [],
        },
    }
    return tree.get(tuple(path))


def _completion_visual_context() -> dict[str, Any]:
    """Return a frozen resolver result covering popup completion chrome."""
    return {
        "path": ["bead", "close"],
        "tokens": [
            {"text": "bead", "start": 0, "end": 4, "role": "command"},
            {"text": "close", "start": 5, "end": 10, "role": "subcommand"},
            {"text": "--force", "start": 11, "end": 18, "role": "option"},
        ],
        "diagnostics": [
            {
                "start": 11,
                "end": 18,
                "severity": "warning",
                "code": "missing-value",
                "message": "requires a resolution",
            }
        ],
        "slot": {"replace_start": 11, "replace_end": 18, "value_kind": ""},
        "signature": {
            "segments": [
                {"text": "bead", "role": "command", "active": False, "required": True},
                {"text": "close", "role": "command", "active": False, "required": True},
                {
                    "text": "‹ID…›",
                    "role": "positional",
                    "active": True,
                    "required": True,
                },
            ],
            "summary": "Close a bead",
        },
        "run_policy": {"policy": "proc", "note": None},
        "writes": True,
        "confirms": True,
        "confirm_flag_present": False,
        "stdin": False,
    }


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((160, 40), "command_line_completion_popup_160x40")],
)
async def test_command_line_completion_popup_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the visible popup, active signature, writes chip, and diagnostic."""
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await _seeded_panel(page, monkeypatch)
            context = _completion_visual_context()
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead close --force")
            # Drain the TextArea change event before pinning this deliberately
            # hand-crafted resolver response; otherwise the ordinary refresh
            # can repaint over it one tick after the test state is installed.
            await wait_for_visual_idle(page)
            widget.set_resolve_context(context)
            screen._resolve_context = context
            screen._resolved_line = widget.text
            screen._last_completion_kind = "option_name"
            items = [
                {
                    "insert_text": "--force ",
                    "display": "--force",
                    "description": "Close matching beads without descendants",
                    "badge": "FLAG",
                    "source": "spec",
                    "match_runs": [[0, 6]],
                    "selected": False,
                },
                {
                    "insert_text": "--resolution ",
                    "display": "--resolution",
                    "description": "Record why this bead is closing",
                    "badge": "RESOLUTION",
                    "source": "spec",
                    "match_runs": [],
                    "selected": False,
                },
            ]
            screen._popup_state.reset(
                items,
                typed_text=widget.text,
                replace_start=11,
                replace_end=18,
            )
            screen._render_popup({"items": items, "kind": "option", "total": 2})
            screen._render_signature()
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "--resolution")
            assert_page_svg_contains(page, "writes")
            assert_page_svg_contains(page, "requires a resolution")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_indexing_120x40")],
)
async def test_command_line_indexing_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the grammar-loading state shown while the user keeps typing."""
    import sase.ace.tui.command_line.screen_completion as screen_module

    monkeypatch.setattr(
        screen_module, "is_command_line_grammar_pending", lambda app: True
    )
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            screen = await _seeded_panel(page, monkeypatch)
            screen.query_one(CommandLineInput).set_line("bead show ")
            await wait_for_visual_idle(page)
            screen._show_indexing(True)
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "indexing commands")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_empty_state_120x40")],
)
async def test_command_line_empty_state_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # The empty state renders from the completion mixin, so patch it there.
    import sase.ace.tui.command_line.screen_completion as screen_module

    seed = _seed_history_file(tmp_path, "bead list --status open", "bead show sase-17x")

    def _fake_kind(app: object) -> str | None:
        return "bead"

    def _fake_values(app: object) -> list[str]:
        return ["sase-17x"]

    monkeypatch.setattr(screen_module, "selected_entity_kind", _fake_kind)
    monkeypatch.setattr(screen_module, "selected_entity_values", _fake_values)
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            await wait_for_startup(page)
            screen = await _open_panel(page, monkeypatch, history_file=seed)
            monkeypatch.setattr(screen, "_help_lookup", _extras_help_lookup)
            # Freeze relative ages to hour/day buckets so the RECENT
            # descriptions ("2h ago", "1d ago") cannot tick between
            # capture and verify samples. Stamp in the configured zone the
            # ages render in, and re-sort: both seeded lines usually share
            # one ``last_used`` second, so the loaded order is a tie.
            from datetime import datetime as _dt
            from datetime import timedelta as _td

            from sase.core.time import get_timezone

            _now = _dt.now(get_timezone())
            for _entry in screen._history.entries:
                if _entry.line == "bead show sase-17x":
                    _entry.last_used = (_now - _td(hours=2)).strftime("%y%m%d_%H%M%S")
                elif _entry.line == "bead list --status open":
                    _entry.last_used = (_now - _td(days=1)).strftime("%y%m%d_%H%M%S")
            screen._history.entries.sort(key=lambda e: e.last_used, reverse=True)
            screen._refresh_completion()
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "bead list --status open")
            assert_page_svg_contains(page, "bead close sase-17x")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((160, 40), "command_line_doc_peek_160x40")],
)
async def test_command_line_doc_peek_png_snapshot(
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
            screen = await _seeded_panel(page, monkeypatch)
            monkeypatch.setattr(screen, "_help_lookup", _extras_help_lookup)
            screen._resolve_context = {"path": ["bead"]}
            screen._last_completion_kind = "subcommand"
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead cl")
            # Let the programmatic line update deliver its Changed message
            # before installing the deliberately frozen completion state.
            await wait_for_visual_idle(page)
            items = [
                {
                    "insert_text": "close ",
                    "display": "close",
                    "description": "Close a bead",
                    "badge": "cmd",
                    "source": "spec",
                    "match_runs": [[0, 2]],
                    "selected": False,
                }
            ]
            screen._popup_state.reset(
                items,
                typed_text="bead cl",
                replace_start=5,
                replace_end=7,
            )
            screen._render_popup(
                {
                    "items": items,
                    "kind": "subcommand",
                    "total": 1,
                }
            )
            screen._popup_state.menu_active = True
            screen._render_doc_peek()
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "Close a bead")
            ace_png_visual.assert_page_png(page, snapshot_name)


@pytest.mark.parametrize(
    ("size", "snapshot_name"),
    [((120, 40), "command_line_history_search_120x40")],
)
async def test_command_line_history_search_png_snapshot(
    size: tuple[int, int],
    snapshot_name: str,
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seed = _seed_history_file(
        tmp_path, "bead list --status open", "bead close sase-17x"
    )
    with (
        patch.object(AceApp, "_load_agents"),
        patch.object(AceApp, "_load_axe_status"),
    ):
        patch_startup_loaders(monkeypatch)
        async with AcePage(query='"visual"', patches=patches(), size=size) as page:
            await wait_for_startup(page)
            screen = await _open_panel(page, monkeypatch, history_file=seed)
            screen.toggle_history_search()
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead cl")
            # Refresh synchronously: programmatic set_line posts its
            # Changed message asynchronously, so converge on the filtered
            # rank explicitly before sampling the frame.
            screen._refresh_completion()
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "history search")
            # The fuzzy match bold-splits the row across SVG text nodes,
            # so compare the space-collapsed styled stream.
            assert_page_svg_styled_text_contains(page, "bead close sase-17x")
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
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
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
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
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
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
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
            screen = await _seeded_panel(page, monkeypatch)
            _seed_block(
                screen,
                "help bead close",
                status="builtin",
                tail_text="bead close ‹ID…› [-n NOTE]\nClose beads.\n",
            )
            await wait_for_visual_idle(page)
            assert_page_svg_contains(page, "built-in")
            ace_png_visual.assert_page_png(page, snapshot_name)
