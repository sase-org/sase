"""ACE TUI PNG snapshots for the Memory panel in light and dark themes."""

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


def _populated_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref("sase", "sase")
    notes = (
        memory_note(
            "always_note", note_type="short", description="Always loaded context."
        ),
        memory_note(
            "agent_hood",
            description="An agent hood is a group of agents sharing a name prefix.",
            body="Agent hood body text describing the concept in more detail.",
        ),
        memory_note(
            "hub_child",
            parent="sase/memory/agent_hood.md",
            description="A child note nested under agent hood.",
            body="Hub child body text.",
        ),
        memory_note(
            "grandchild",
            parent="sase/memory/hub_child.md",
            description="A grandchild note nested under hub child.",
            body="Grandchild body text.",
        ),
    )
    install_fixed_load(monkeypatch, (ref,), {"sase": scope_snapshot(ref, notes)})


def _empty_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref(
        "gh_org__research",
        "Research",
        has_memory=False,
        memory_read_root=None,
    )
    install_fixed_load(
        monkeypatch, (ref,), {"gh_org__research": scope_snapshot(ref, ())}
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
            "memory_panel_populated_dark_120x40",
            "ACE memory panel - populated dark theme",
        ),
        (
            "textual-light",
            "memory_panel_populated_light_120x40",
            "ACE memory panel - populated light theme",
        ),
    ],
)
async def test_memory_panel_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _populated_setup(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(MemoryPanel(initial_note="sase/memory/agent_hood.md"))
        await page.expect_modal("MemoryPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")
        await page.press(".", "1")
        await wait_for_state(
            page,
            lambda: (
                (pane := _panel_pane(page)) is not None
                and pane._current_note == "sase/memory/hub_child.md"
                and pane._trail == ["sase/memory/agent_hood.md"]
            ),
            description="followed CHILDREN chip to hub_child",
        )
        await wait_for_svg_contains(page, "TRAIL")
        await wait_for_svg_contains(page, "PARENT")
        await wait_for_svg_contains(page, "CHILDREN")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_panel_empty_dark_120x40",
            "ACE memory panel - empty dark theme",
        ),
        (
            "textual-light",
            "memory_panel_empty_light_120x40",
            "ACE memory panel - empty light theme",
        ),
    ],
)
async def test_memory_panel_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    _empty_setup(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        page.app.push_screen(MemoryPanel())
        await page.expect_modal("MemoryPanel")
        await wait_for_state(page, lambda: _panel_ready(page), description="panel load")
        await wait_for_svg_contains(page, "No memory root for")
        await wait_for_svg_contains(page, "Research")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
