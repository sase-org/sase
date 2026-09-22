"""ACE PNG snapshots for the keyboard-first Update panel modal."""

from __future__ import annotations

import pytest
from rich.text import Text
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals import UpdatePanel
from sase.ace.tui.update_panel_state import (
    UpdateOptionChip,
    UpdateOptionChipKind,
    UpdateOptionRow,
    UpdateOptionScope,
    UpdatePanelState,
)
from sase.ace.tui.widgets.update_accents import (
    AGENT_CLI_ACCENT,
    UPDATE_GLYPH,
    UPDATES_ACCENT,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_COPY: dict[UpdateOptionScope, tuple[str, str, str]] = {
    "everything": (
        "e",
        "Everything",
        "SASE, core, plugins, and providers in one tracked update.",
    ),
    "sase": (
        "s",
        "SASE, core & plugins",
        "Upgrade the sase host package, sase-core, and every installed plugin.",
    ),
    "providers": (
        "p",
        "Providers",
        "Update every installed LLM / agent CLI provider.",
    ),
}


def _row(
    scope: UpdateOptionScope,
    *,
    kind: UpdateOptionChipKind = "unknown",
    text: str = "· not checked yet",
    count: int = 0,
    details: tuple[str, ...] = (),
    accent: str = UPDATES_ACCENT,
    core_rebuild: bool = False,
) -> UpdateOptionRow:
    key, title, description = _COPY[scope]
    return UpdateOptionRow(
        scope=scope,
        key=key,
        title=title,
        description=description,
        chip=UpdateOptionChip(
            kind=kind, text=text, count=count, core_rebuild=core_rebuild
        ),
        accent=accent,
        details=details,
    )


def _pending_state() -> UpdatePanelState:
    """Every row populated: core rebuild and manual providers."""
    return UpdatePanelState(
        rows=(
            _row(
                "everything",
                kind="available",
                text=f"{UPDATE_GLYPH} 5 available",
                count=5,
                details=(
                    "sase 1 · sase-core 1 · core rebuild · providers 3 (1 manual)",
                ),
                accent="$primary",
                core_rebuild=True,
            ),
            _row(
                "sase",
                kind="available",
                text=f"{UPDATE_GLYPH} 2 available",
                count=2,
                details=("sase 1 · sase-core 1 · core rebuild",),
                accent=UPDATES_ACCENT,
                core_rebuild=True,
            ),
            _row(
                "providers",
                kind="available",
                text=f"{UPDATE_GLYPH} 3 available",
                count=3,
                details=(
                    "• Claude Code  2.1.0 → 2.2.0",
                    "• Codex CLI    0.9.1 → 1.0.0 · manual steps",
                    "• Gemini CLI   unknown → 1.4.0",
                ),
                accent=AGENT_CLI_ACCENT,
            ),
        ),
        freshness_label="4m ago",
        stale=False,
        rechecking=False,
    )


def _unchecked_state() -> UpdatePanelState:
    """No snapshots: three unknown rows and the never-checked subtitle."""
    return UpdatePanelState(
        rows=(
            _row("everything", accent="$primary"),
            _row("sase", accent=UPDATES_ACCENT),
            _row("providers", accent=AGENT_CLI_ACCENT),
        ),
        freshness_label="never checked — press r",
        stale=True,
        rechecking=False,
    )


def _option_plain(option_list: OptionList, index: int) -> str:
    prompt = option_list.get_option_at_index(index).prompt
    if isinstance(prompt, Text):
        return prompt.plain
    return str(prompt)


async def _push_update_panel(page: AcePage, state: UpdatePanelState) -> OptionList:
    modal = UpdatePanel(state)
    page.app.push_screen(modal)
    await page.expect_modal("UpdatePanel")
    await page.wait_for(lambda _s: len(modal.query("#update-panel-list")) > 0)
    return modal.query_one("#update-panel-list", OptionList)


async def test_update_panel_pending_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Populated rows: core rebuild and manual-steps providers."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")

        option_list = await _push_update_panel(page, _pending_state())
        await wait_for_state(
            page,
            lambda: (
                option_list.option_count == 3
                and "e/E" in _option_plain(option_list, 0)
                and "providers 3 (1 manual)" in _option_plain(option_list, 0)
                and "core rebuild" in _option_plain(option_list, 1)
                and "0.9.1 → 1.0.0 · manual steps" in _option_plain(option_list, 2)
            ),
            description="pending Update panel rows",
        )
        await wait_for_svg_contains(page, "manual steps")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "update_panel_pending_120x40",
            title="ACE Update panel (pending)",
        )


async def test_update_panel_unchecked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never-checked evidence still renders three selectable unknown rows."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")

        option_list = await _push_update_panel(page, _unchecked_state())
        await wait_for_state(
            page,
            lambda: (
                option_list.option_count == 3
                and "e/E" in _option_plain(option_list, 0)
                and all(
                    "· not checked yet" in _option_plain(option_list, index)
                    for index in range(3)
                )
            ),
            description="never-checked Update panel rows",
        )
        await wait_for_svg_contains(page, "never checked")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "update_panel_unchecked_120x40",
            title="ACE Update panel (never checked)",
        )
