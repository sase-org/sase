"""PNG goldens for the Memory pane pinned time strip (phase `time-strip`).

The card head carries the pager's pill on the path line above a reserved
two-row strip. History data is injected deterministically (no git/file
I/O): timeline summaries are pinned into the pane cache and the strip
renders through ``sase.pager.history_kit``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.memory_panel import MemoryPanel, MemoryPane
from tests.ace.tui.modals.memory_panel_test_helpers import (
    install_fixed_load,
    memory_note,
    scope_ref,
    scope_snapshot,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_NOW = 1790769600  # 2026-09-30 12:00 UTC, pinned for goldens
_V1_TIME = 1789905600  # 2026-09-20 12:00 UTC
_V2_TIME = 1790085780  # 2026-09-22 14:03 UTC


def _version(
    ordinal: int,
    class_name: str = "authored",
    volume: int = 10,
) -> dict:
    return {
        "ordinal": ordinal,
        "commit": f"{ordinal:040d}",
        "committer_time": _V1_TIME if ordinal == 1 else _V2_TIME,
        "class": class_name,
        "hidden": False,
        "summary": {
            "section_paths": ["Default Keymap Config"],
            "words_added": 31,
            "words_removed": 4,
            "frontmatter_phrase": None,
            "created_words": None,
            "volume": volume,
        },
        "provenance": {"agent": "athena", "bead": "sase-1au.5"},
        "cause": {},
        "path": "sase/memory/gotchas.md",
        "blob_oid": "b" * 40,
    }


def _timeline(state: str = "tracked", *, dirty: bool = False) -> dict:
    versions = [_version(1, "created", 412), _version(2, "authored", 35)]
    if state in ("untracked", "NO VCS"):
        return {
            "selector": "sase/memory/gotchas.md",
            "core_selector": "sase/memory/gotchas.md",
            "scope_key": "sase",
            "state": state,
            "tip": "",
            "now_epoch": _NOW,
            "versions": [],
            "total": 0,
            "dirty": False,
        }
    return {
        "selector": "sase/memory/gotchas.md",
        "core_selector": "sase/memory/gotchas.md",
        "scope_key": "sase",
        "state": state,
        "tip": "1a2b3c4",
        "now_epoch": _NOW,
        "versions": versions,
        "total": len(versions),
        "dirty": dirty,
    }


def _setup(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note(
            "gotchas",
            description="Code conventions and gotchas.",
            body="Code conventions and gotchas body text.",
        ),
        memory_note(
            "always_note", note_type="core", description="Always loaded context."
        ),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})


def _panel_pane(page: AcePage) -> MemoryPane | None:
    screen = page.app.screen
    if isinstance(screen, MemoryPanel):
        return screen.pane
    if isinstance(screen, MemoryPane):
        return screen
    return None


def _panel_ready(page: AcePage) -> bool:
    pane = _panel_pane(page)
    return pane is not None and not pane._loading


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_time_strip_now_clean_dark_120x40",
            "ACE memory pane - time strip now clean dark",
        ),
        (
            "textual-light",
            "memory_pane_time_strip_now_clean_light_120x40",
            "ACE memory pane - time strip now clean light",
        ),
    ],
)
async def test_memory_pane_time_strip_now_clean_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _setup(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(MemoryPanel(initial_note="sase/memory/gotchas.md"))
        await page.expect_modal("MemoryPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")

        pane = _panel_pane(page)
        assert pane is not None
        summary = _timeline()
        pane._history_latest[("sase", summary["selector"])] = summary
        pane._history_latest[("sase", "sase/memory/gotchas.md")] = summary
        pane._render_note_card()
        pane._update_footer()
        await page.pause()
        await wait_for_svg_contains(page, "NOW")
        await wait_for_svg_contains(page, "H history")
        await wait_for_svg_contains(page, "C changes")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
