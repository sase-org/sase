"""PNG snapshots for the shared save-location picker modal."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.save_location_choices import (
    EXISTING_CHOICE_ID,
    SaveLocationChoice,
)
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
    display_path: str | None = None,
) -> SaveLocationChoice:
    return SaveLocationChoice(
        choice_id=choice_id,
        hotkey=hotkey,
        section=section,
        kind=kind,  # type: ignore[arg-type]
        label=label,
        display_path=choice_id if display_path is None else display_path,
        badges=badges,
        disabled_reason=disabled_reason,
        preview=preview,
        is_default=is_default,
        collapsed_group=collapsed_group,
    )


def _macro_choices() -> tuple[SaveLocationChoice, ...]:
    return (
        _choice(
            "./sase/macros/",
            "p",
            "Project · sase",
            kind="directory",
            label="Project macros",
            badges=("★ last used",),
            preview=(
                "→ ./sase/macros/<name>.md · called as #sase/<name> · 24 macros here"
            ),
            is_default=True,
        ),
        _choice(
            "./sase/sase.yml",
            "P",
            "Project · sase",
            label="Project config",
            preview="→ ./sase/sase.yml · macros.<name>",
        ),
        _choice(
            "~/sase/macros/sase/",
            "1",
            "Project · sase",
            kind="directory",
            label="Project, personal",
            badges=("new",),
            preview=(
                "→ ~/sase/macros/sase/<name>.md · called as #<name> · 0 macros here"
            ),
        ),
        _choice(
            "~/sase/macros/",
            "h",
            "Home",
            kind="directory",
            label="Home macros",
            badges=("chezmoi",),
            preview=("→ ~/sase/macros/<name>.md · called as #<name> · 3 macros here"),
        ),
        _choice(
            "~/.config/sase/sase.yml",
            "H",
            "Home",
            label="User config",
            badges=("chezmoi",),
            preview="→ ~/.config/sase/sase.yml · macros.<name>",
        ),
        _choice(
            "~/.config/sase/sase_work.yml",
            "2",
            "Home",
            label="sase_work.yml",
            preview="→ ~/.config/sase/sase_work.yml · macros.<name>",
        ),
        _choice(
            "/pkg/macros",
            None,
            "Plugins & built-in",
            kind="directory",
            label="Built-in macros/",
            preview="→ /pkg/macros/<name>.md · 2 macros here",
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


async def test_save_location_picker_macro_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = SaveLocationPickerModal(
        "macro",
        "New mini-macro · where should it live?",
        _macro_choices(),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(modal)
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "Project macros")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "save_location_picker_macro_120x40",
            title="ACE save location picker — mini-macro destinations",
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
        "macro", "New mini-macro · where should it live?", None
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


def _existing_row(*, kind: str, count: int) -> SaveLocationChoice:
    singular = "macro" if kind == "macro" else "snippet"
    noun = "macros" if kind == "macro" else "snippets"
    return _choice(
        EXISTING_CHOICE_ID,
        "e",
        "Existing",
        kind="existing",
        label=f"Edit existing {singular}…",
        badges=(f"{count} {noun}",),
        preview=(
            f"→ fuzzy-find {count} {noun} across 9 files "
            "· edit in place or override read-only ones"
        ),
        display_path="",
    )


def _macro_choices_with_existing() -> tuple[SaveLocationChoice, ...]:
    return (_existing_row(kind="macro", count=148), *_macro_choices())


def _snippet_choices_with_existing() -> tuple[SaveLocationChoice, ...]:
    return (_existing_row(kind="snippet", count=36), *_snippet_choices())


def _override_choices() -> tuple[SaveLocationChoice, ...]:
    return (
        _choice(
            "./sase/macros/",
            "p",
            "Project · sase",
            kind="directory",
            label="Project macros",
            disabled_reason="saves as #sase/review — can't override #review",
            preview="→ ./sase/macros/review.md · called as #sase/review · 24 macros here",
        ),
        _choice(
            "./sase/sase.yml",
            "P",
            "Project · sase",
            label="Project config",
            badges=("⚠ shadowed by ~/sase/macros/review.md",),
            preview="→ ./sase/sase.yml · macros.review",
        ),
        _choice(
            "~/sase/macros/",
            "h",
            "Home",
            kind="directory",
            label="Home macros",
            badges=("★ override", "chezmoi"),
            preview="→ ~/sase/macros/review.md · called as #review · 3 macros here",
            is_default=True,
        ),
        _choice(
            "~/.config/sase/sase.yml",
            "H",
            "Home",
            label="User config",
            badges=("chezmoi",),
            preview="→ ~/.config/sase/sase.yml · macros.review",
        ),
    )


async def test_save_location_picker_existing_macro_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = SaveLocationPickerModal(
        "macro",
        "New mini-macro · where should it live?",
        _macro_choices_with_existing(),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(modal)
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "Edit existing macro")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "save_location_picker_existing_macro_120x40",
            title="ACE save location picker — existing macro row",
        )


async def test_save_location_picker_existing_snippet_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = SaveLocationPickerModal(
        "snippet",
        "New snippet · where should it live?",
        _snippet_choices_with_existing(),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(modal)
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "Edit existing snippet")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "save_location_picker_existing_snippet_120x40",
            title="ACE save location picker — existing snippet row",
        )


async def test_save_location_picker_override_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    modal = SaveLocationPickerModal(
        "macro",
        "Override #review · where should your copy live?",
        _override_choices(),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(modal)
        await page.expect_modal("SaveLocationPickerModal")
        await wait_for_svg_contains(page, "saves as")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "save_location_picker_override_120x40",
            title="ACE save location picker — override mode",
        )
