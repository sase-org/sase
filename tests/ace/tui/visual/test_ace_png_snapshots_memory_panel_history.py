"""PNG goldens for the Memory panel History row (phase `memory-panel`).

A note card with the History row in dark and light themes at 120x40.
History data is injected deterministically (no git/file I/O): the
``memory_history`` beta is forced on, the timeline summary is pinned,
and the mini sparkline reuses the pager ``render_sparkline`` cells.
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


def _history_summary() -> dict:
    return {
        "selector": "sase/memory/agent_hood.md",
        "core_selector": "sase/memory/agent_hood.md",
        "scope_key": "sase",
        "state": "tracked",
        "tip": "1a2b3c4",
        "now_epoch": _NOW,
        "total": 9,
        "versions": [
            {
                "ordinal": 1,
                "commit": "1" * 40,
                "committer_time": _V1_TIME,
                "class": "created",
                "hidden": False,
                "summary": {"volume": 412},
                "provenance": {},
                "cause": {},
                "path": "sase/memory/agent_hood.md",
                "blob_oid": "a" * 40,
            },
            {
                "ordinal": 2,
                "commit": "2" * 40,
                "committer_time": _V2_TIME,
                "class": "authored",
                "hidden": False,
                "summary": {
                    "volume": 35,
                    "words_added": 31,
                    "words_removed": 4,
                },
                "provenance": {"agent": "athena", "bead": "sase-1bc.12"},
                "cause": {},
                "path": "sase/memory/agent_hood.md",
                "blob_oid": "b" * 40,
            },
        ],
    }


def _setup(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note(
            "agent_hood",
            description="An agent hood is a group of agents sharing a name prefix.",
            body="Agent hood body text describing the concept in more detail.",
        ),
        memory_note(
            "always_note", note_type="core", description="Always loaded context."
        ),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})
    # Force the beta on and keep history off the real git/service path:
    # the summary below is injected directly into the pane cache.
    monkeypatch.setattr(
        "sase.ace.tui.modals.memory_panel_history.history_enabled",
        lambda: True,
    )


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
            "memory_panel_history_dark_120x40",
            "ACE memory panel - history row dark theme",
        ),
        (
            "textual-light",
            "memory_panel_history_light_120x40",
            "ACE memory panel - history row light theme",
        ),
    ],
)
async def test_memory_panel_history_png_snapshot(
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
        page.app.push_screen(MemoryPanel(initial_note="sase/memory/agent_hood.md"))
        await page.expect_modal("MemoryPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")

        pane = _panel_pane(page)
        assert pane is not None
        summary = _history_summary()
        pane._history_latest[("sase", summary["selector"])] = summary
        # The selected note's selector is its relative path.
        pane._history_latest[("sase", "sase/memory/agent_hood.md")] = summary
        pane._render_note_card()
        pane._update_footer()
        await page.pause()
        await wait_for_svg_contains(page, "History")
        await wait_for_svg_contains(page, "H history")
        await wait_for_svg_contains(page, "C changes")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
