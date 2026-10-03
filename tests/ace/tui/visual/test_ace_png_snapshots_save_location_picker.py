"""PNG snapshots for the shared save-location picker modal."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.save_location_choices import SaveLocationChoice
from sase.ace.tui.modals.save_location_picker_modal import SaveLocationPickerModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

import pytest

pytestmark = pytest.mark.visual


def _choice(
    choice_id: str,
    hotkey: str | None,
    section: str,
    *,
    kind: str = "config",
    label: str = "User config",
    badges: tuple[str, ...] = (),
    disabled_reason: str | None = None,
    preview: str = "preview",
    is_default: bool = False,
    collapsed_group: bool = False,
) -> SaveLocationChoice:
    return SaveLocationChoice(
        choice_id=choice_id,
        hotkey=hotkey,
        section=section,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        display_path=choice_id,
        badges=badges,
        disabled_reason=disabled_reason,
        preview=preview,
        is_default=is_default,
        collapsed_group=collapsed_group,
    )


def _xprompt_choices() -> tuple[SaveLocationChoice, ...]:
    return (
        _choice(
            "./sase/macros/",
            "p",
            "Project · sase",
            kind="directory",
            label="Project xprompts",
            badges=("★ last used",),
            preview=(
                "→ ./sase/xprompts/<name>.md · called as #sase/<name> "
                "· 24 xprompts here"
            ),
            is_default=True,
        ),
        _choice(
            "./sase/sase.yml",
            "P",
            "Project · sase",
            label="Project config",
            preview="→ ./sase/sase.yml · xprompts.<name>",
        ),
        _choice(
            "~/sase/xprompts/sase/",
            "1",
            "Project · sase",
            kind="directory",
            label="Project, personal",
            badges=("new",),
            preview=(
                "→ ~/sase/xprompts/sase/<name>.md · called as #<name> · 0 xprompts here"
            ),
        ),
        _choice(
            "~/sase/xprompts/",
            "h",
            "Home",
            kind="directory",
            label="Home xprompts",
            badges=("chezmoi",),
            preview=(
                "→ ~/sase/xprompts/<name>.md · called as #<name> · 3 xprompts here"
            ),
        ),
        _choice(
            "~/.config/sase/sase.yml",
            "H",
            "Home",
            label="User config",
            badges=("chezmoi",),
            preview="→ ~/.config/sase/sase.yml · xprompts.<name>",
        ),
        _choice(
            "~/.config/sase/sase_work.yml",
            "2",
            "Home",
            label="sase_work.yml",
            preview="→ ~/.config/sase/sase_work.yml · xprompts.<name>",
        ),
        _choice(
            "/pkg/xprompts",
            None,
            "Plugins & built-in",
            kind="directory",
            label="Built-in xprompts/",
            preview="→ /pkg/xprompts/<name>.md · 2 xprompts here",
            collapsed_group=True,
        ),
    )


def _snippet_choices() -> tuple[SaveLocationChoice, ...]:
    return (
        _choice(
            "/custom/snippets.yml",
            "c",
            "Configured",
            label="Configured snippet config",
            preview="→ /custom/snippets.yml · ace.snippets.<trigger> · 4 snippets here",
        ),
        _choice(
            "./sase/sase.yml",
            "p",
            "Project · sase",
            label="Project config",
            badges=("has ⇥ todo",),
            preview="→ ./sase/sase.yml · ace.snippets.todo · 1 snippets here",
        ),
        _choice(
            "~/.config/sase/sase.yml",
            "h",
            "Home",
            label="User config",
            badges=("★ default",),
            preview="→ ~/.config/sase/sase.yml · ace.snippets.todo · 12 snippets here",
            is_default=True,
        ),
    )


async def test_save_location_picker_xprompt_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = SaveLocationPickerModal(
        "xprompt",
        "New mini-xprompt · where should it live?",
        _xprompt_choices(),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(modal)
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "Project xprompts")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "save_location_picker_xprompt_120x40",
            title="ACE save location picker — mini-xprompt destinations",
        )


async def test_save_location_picker_snippet_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = SaveLocationPickerModal(
        "snippet",
        "New snippet · where should it live?",
        _snippet_choices(),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(modal)
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "Configured snippet config")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "save_location_picker_snippet_120x40",
            title="ACE save location picker — snippet destinations",
        )


async def test_save_location_picker_loading_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = SaveLocationPickerModal(
        "xprompt", "New mini-xprompt · where should it live?", None
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(modal)
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "Finding destinations")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "save_location_picker_loading_120x40",
            title="ACE save location picker — loading",
        )
