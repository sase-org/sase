"""sase's TUI PNG visual snapshots for the ``:`` Command Line completion chrome.

Pins grammar-driven states with frozen context: completion popup with
signature chips and diagnostics, indexing indicator, empty-state recency,
doc peek, and history search.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import AceApp
from sase.ace.tui.command_line.input import CommandLineInput
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    assert_page_svg_styled_text_contains,
)
from tests.ace.tui.visual._ace_command_line_png_snapshot_shared import (
    open_command_line_panel,
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
            screen = await seeded_command_line_panel(page, monkeypatch)
            context = _completion_visual_context()
            widget = screen.query_one(CommandLineInput)
            widget.set_line("bead close --force")
            # Drain the TextArea change event before pinning this deliberately
            # hand-crafted resolver response; otherwise the ordinary refresh
            # can repaint over it one tick after the test state is installed.
            await wait_for_visual_idle(page)
            widget.set_resolve_context(context)  # type: ignore[arg-type]
            screen._resolve_context = context  # type: ignore[assignment]
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
            screen = await seeded_command_line_panel(page, monkeypatch)
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
            screen = await open_command_line_panel(page, monkeypatch, history_file=seed)
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
            screen = await seeded_command_line_panel(page, monkeypatch)
            monkeypatch.setattr(screen, "_help_lookup", _extras_help_lookup)
            screen._resolve_context = {"path": ["bead"]}  # type: ignore[assignment]
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
            screen = await open_command_line_panel(page, monkeypatch, history_file=seed)
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
