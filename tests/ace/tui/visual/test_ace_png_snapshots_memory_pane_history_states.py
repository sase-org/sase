"""PNG goldens for the Memory pane history states (epic ``sase-1ev``).

Covers the card and rail states of plan ``202610/memory_history_tui.md``
§4.2-§4.6 at 120x40 in dark and light themes:

- ``past_read``: the card pinned to a past version (violet frame,
  ``⟲ PAST`` pill, the historical body).
- ``past_diff``: the same pin after ``=`` (word diff with inserts,
  deletes, a removal marker, and an ``H to expand`` fold).
- ``timeline_lens``: the ``@`` Timeline lens with a hidden version and
  a ``b`` compare base.
- ``rail_glance_deleted``: the recency glance column plus the ``D``
  DELETED group with the tombstone card selected.
- ``instructions_group``: the expanded INSTRUCTIONS group with one
  instruction file card.

History data is injected deterministically through a fake app-scoped
history service: no git, no core, no wall-clock reads. The visual lane
pins ``TZ=UTC``; the few wall-clock reads the pane makes for ages are
pinned to ``NOW`` in the shared fixture module.

This module keeps the original import path. Shared fixtures live in
``_ace_memory_pane_history_png_snapshot_wires`` and
``_ace_memory_pane_history_png_snapshot_shared``.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.memory_panel import MemoryPane
from tests.ace.tui.visual._ace_memory_pane_history_png_snapshot_shared import (
    GOTCHAS as _GOTCHAS,
    OLD_TIPS as _OLD_TIPS,
    ROOT_AGENTS as _ROOT_AGENTS,
    SCOPE_KEY as _SCOPE_KEY,
    capture as _capture,
    install_history as _install_history,
    open_memory_pane as _open_memory_pane,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    wait_for_state,
    wait_for_svg_contains,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _applied_ordinal(pane: MemoryPane) -> int:
    return int(pane._time_applied_ordinal(pane._selected_row()))


def _selected_identity(pane: MemoryPane) -> str:
    node = pane._selected_row()
    return str(getattr(node, "identity", "") or "")


async def _step_to_v2(page: AcePage, pane: MemoryPane) -> None:
    """Press ``(`` twice: now → v4, then v2 (the hidden v3 reflow is skipped)."""
    await page.press("(")
    await wait_for_state(page, lambda: _applied_ordinal(pane) == 4, description="v4")
    await page.press("(")
    await wait_for_state(page, lambda: _applied_ordinal(pane) == 2, description="v2")
    await wait_for_svg_contains(page, "PAST")


def _lens_row_index(pane: MemoryPane, label: str) -> int:
    for index, row in enumerate(pane._timeline_listed):
        if str(row.get("label", "")) == label and not row.get("pseudo", False):
            return index
    raise AssertionError(f"no Timeline lens row labelled {label!r}")


async def _press_lens_cursor(page: AcePage, pane: MemoryPane, key: str) -> None:
    expected = pane._timeline_cursor + (1 if key == "j" else -1)
    await page.press(key)
    await wait_for_state(
        page,
        lambda: pane._timeline_cursor == expected,
        description=f"lens cursor row {expected}",
    )


async def _move_lens_cursor(page: AcePage, pane: MemoryPane, ordinal: int) -> None:
    """Walk the lens cursor to ``v<ordinal>`` and wait for its card preview.

    Rows are located by label so the walk does not depend on the lens
    row order.
    """
    target = _lens_row_index(pane, f"v{ordinal}")
    while pane._timeline_cursor != target:
        await _press_lens_cursor(
            page, pane, "j" if pane._timeline_cursor < target else "k"
        )
    await wait_for_state(
        page,
        lambda: _applied_ordinal(pane) == ordinal,
        description=f"lens preview v{ordinal}",
    )


# --- goldens -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_past_read_dark_120x40",
            "ACE memory pane - past version read dark",
        ),
        (
            "textual-light",
            "memory_pane_past_read_light_120x40",
            "ACE memory pane - past version read light",
        ),
    ],
)
async def test_memory_pane_past_read_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    _install_history(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_memory_pane(page, theme)
        await _step_to_v2(page, pane)
        await wait_for_svg_contains(page, "or leader keys.")
        await _capture(page, ace_png_visual, snapshot_name, title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_past_diff_dark_120x40",
            "ACE memory pane - past version word diff dark",
        ),
        (
            "textual-light",
            "memory_pane_past_diff_light_120x40",
            "ACE memory pane - past version word diff light",
        ),
    ],
)
async def test_memory_pane_past_diff_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    _install_history(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_memory_pane(page, theme)
        await _step_to_v2(page, pane)
        await page.press("=")
        await wait_for_state(
            page,
            lambda: pane._diff_text_for_node(pane._selected_row()) is not None,
            description="v1 → v2 comparison",
        )
        await wait_for_svg_contains(page, "H to expand")
        await wait_for_svg_contains(page, "1 line removed")
        await _capture(page, ace_png_visual, snapshot_name, title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_timeline_lens_dark_120x40",
            "ACE memory pane - Timeline lens with compare base dark",
        ),
        (
            "textual-light",
            "memory_pane_timeline_lens_light_120x40",
            "ACE memory pane - Timeline lens with compare base light",
        ),
    ],
)
async def test_memory_pane_timeline_lens_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    _install_history(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_memory_pane(page, theme)
        # The lens repaints its row markers only when a preview has to
        # load, so pin the outcome: the now-card prefetch (v2, v4) lands
        # before the cursor moves.
        await wait_for_state(
            page,
            lambda: all(
                (_SCOPE_KEY, _GOTCHAS, ordinal) in pane._time_bodies
                for ordinal in (2, 4)
            ),
            description="now-card prefetch of v2 and v4",
        )
        await page.press("@")
        await wait_for_state(
            page, lambda: pane._lens == "timeline", description="Timeline lens"
        )
        await wait_for_svg_contains(page, "1 hidden")
        await _move_lens_cursor(page, pane, 4)
        await page.press("b")
        await wait_for_state(
            page, lambda: pane._timeline_base == 4, description="compare base v4"
        )
        await _move_lens_cursor(page, pane, 2)
        await wait_for_svg_contains(page, "Compare v2 → v4")
        await _capture(page, ace_png_visual, snapshot_name, title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_rail_glance_deleted_dark_120x40",
            "ACE memory pane - rail glance and DELETED tombstone dark",
        ),
        (
            "textual-light",
            "memory_pane_rail_glance_deleted_light_120x40",
            "ACE memory pane - rail glance and DELETED tombstone light",
        ),
    ],
)
async def test_memory_pane_rail_glance_deleted_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    _install_history(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_memory_pane(page, theme)
        await page.press("D")
        await wait_for_state(
            page, lambda: pane._show_deleted, description="DELETED group"
        )
        await page.press("G")
        await wait_for_state(
            page,
            lambda: _selected_identity(pane) == _OLD_TIPS,
            description="tombstone row selected",
        )
        await wait_for_state(
            page, lambda: _applied_ordinal(pane) == 3, description="tombstone pin"
        )
        await wait_for_svg_contains(page, "1 deleted")
        await wait_for_svg_contains(page, "Press F5")
        await _capture(page, ace_png_visual, snapshot_name, title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "memory_pane_instructions_group_dark_120x40",
            "ACE memory pane - INSTRUCTIONS group and card dark",
        ),
        (
            "textual-light",
            "memory_pane_instructions_group_light_120x40",
            "ACE memory pane - INSTRUCTIONS group and card light",
        ),
    ],
)
async def test_memory_pane_instructions_group_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    _install_history(monkeypatch, include_instructions=True)

    async with AcePage(query='"visual"', patches=patches()) as page:
        pane = await _open_memory_pane(page, theme)
        await wait_for_state(
            page,
            lambda: len(pane._instruction_order) == 2,
            description="instruction subjects",
        )
        await wait_for_svg_contains(page, "INSTRUCTIONS · 2")
        await page.press("G")
        await wait_for_state(
            page,
            lambda: _selected_identity(pane) == "INSTRUCTIONS",
            description="INSTRUCTIONS group row",
        )
        await page.press("space")
        await wait_for_state(
            page,
            lambda: pane._expanded_instructions,
            description="INSTRUCTIONS expanded",
        )
        await page.press("j")
        await wait_for_state(
            page,
            lambda: _selected_identity(pane) == _ROOT_AGENTS,
            description="root AGENTS.md row",
        )
        body_key = (_SCOPE_KEY, _ROOT_AGENTS)
        await wait_for_state(
            page,
            lambda: body_key in pane._instruction_bodies,
            description="rendered AGENTS.md body",
        )
        await wait_for_state(
            page,
            lambda: body_key in pane._history_latest,
            description="AGENTS.md timeline",
        )
        await wait_for_svg_contains(page, "Core Memory")
        await wait_for_svg_contains(page, "MANAGED")
        await _capture(page, ace_png_visual, snapshot_name, title)
