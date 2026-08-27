"""Tests for the app-owned artifact links panel."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.modals.artifact_links_panel_modal import (
    ArtifactLinksPanelModal,
    ArtifactLinksPanelResult,
    _artifact_link_option_text,
    _artifact_links_panel_selector_keys,
)
from sase.ace.tui.relations.link_index import LinkChip
from sase.core.artifact_entry_target import ArtifactEntryTarget


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


_DEFAULT_TARGET = ArtifactEntryTarget(
    "beads",
    ("demo", "task", "sase-ug.9"),
)


def _chip(
    index: int = 0,
    *,
    why: str = "full reason that should not be truncated in the panel",
    origin: str = "manual",
    created_by: str = "tester",
    created_at: str = "2026-08-26T00:00:00Z",
    writable: bool = True,
    neighbor_target: ArtifactEntryTarget | None = _DEFAULT_TARGET,
) -> LinkChip:
    return LinkChip(
        relation="implements",
        label="implemented-by",
        directed=True,
        this_is_source=True,
        neighbor_ref=f"bead:sase-ug.{index}",
        neighbor_target=neighbor_target,
        accent="#00D7AF",
        icon="◈",
        why=why,
        origin=origin,
        uses=index + 1,
        created_by=created_by,
        created_at=created_at,
        writable=writable,
    )


def test_selector_keys_use_full_alphabet() -> None:
    keys = _artifact_links_panel_selector_keys(30)

    assert len(keys) == 26
    assert keys[:3] == ["a", "b", "c"]
    assert keys[-1] == "z"
    assert {"j", "k", "q"} <= set(keys)


def test_option_text_renders_full_why_and_provenance() -> None:
    chip = _chip(
        3,
        origin="projected",
        created_by="projection:stitch-bead",
        writable=False,
        neighbor_target=None,
    )

    plain = _artifact_link_option_text("d", chip).plain

    assert "d  → implemented-by" in plain
    assert "sase-ug.3 (missing)" in plain
    assert "origin projected" in plain
    assert "uses 4" in plain
    assert "created 2026-08-26T00:00:00Z" in plain
    assert "by projection:stitch-bead" in plain
    assert "rule stitch-bead" in plain
    assert "projected:stitch-bead" in plain
    assert "rm disabled" in plain
    assert "why: full reason that should not be truncated in the panel" in plain


async def test_letter_key_selects_rows_reserved_by_neighbor_modal() -> None:
    result: object | None = None
    chips = tuple(_chip(index) for index in range(12))

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactLinksPanelModal(subject_ref="file:origin.txt", chips=chips)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("k")
        await pilot.pause()

    assert result == ArtifactLinksPanelResult(action="follow", chip=chips[10])


async def test_enter_selects_highlighted_row() -> None:
    result: object | None = None
    chips = tuple(_chip(index) for index in range(3))

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactLinksPanelModal(subject_ref="file:origin.txt", chips=chips)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#artifact-links-panel-list", OptionList)
        option_list.highlighted = 2
        await pilot.press("enter")
        await pilot.pause()

    assert result == ArtifactLinksPanelResult(action="follow", chip=chips[2])


async def test_remove_highlighted_requires_writable_chip() -> None:
    result: object | None = "sentinel"
    chips = (_chip(writable=False),)

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactLinksPanelModal(subject_ref="file:origin.txt", chips=chips)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.action_remove_highlighted()
        await pilot.pause()

    assert result == "sentinel"


async def test_remove_highlighted_returns_writable_chip() -> None:
    result: object | None = None
    chip = _chip()

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactLinksPanelModal(subject_ref="file:origin.txt", chips=(chip,))
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.action_remove_highlighted()
        await pilot.pause()

    assert result == ArtifactLinksPanelResult(action="remove", chip=chip)
