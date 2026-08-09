"""ACE TUI PNG visual snapshots for Config Center edit modal states."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _build_view,
    _config_layers,
    _config_schema,
    _open_config_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_xprompt_sources,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def _open_edit_modal(page: AcePage, path: str) -> ConfigEditModal:
    """Open the Config edit modal for the leaf at *path*."""
    _, pane = await _open_config_modal(page)
    pane._do_jump(path)
    await wait_for_state(
        page,
        lambda: pane._selected_path == path,
        description=f"Config Center selection {path!r}",
    )
    pane.action_edit_field()
    await page.expect_modal("ConfigEditModal")
    modal = page.app.screen
    assert isinstance(modal, ConfigEditModal)
    await wait_for_state(
        page,
        lambda: (
            modal._stage == "edit"
            and bool(modal.query("#config-edit-scope"))
            and (modal._editor_kind in ("bool", "enum") or modal.focused is not None)
        ),
        description=f"Config edit controls and focus for {path!r}",
    )
    return modal


async def test_config_center_edit_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The edit stage: scope selector + typed editor for a string field."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr("sase.config.edit.get_use_chezmoi", lambda: False)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await _open_edit_modal(page, "timezone")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_edit_modal_120x40",
            title="ACE SASE Admin Center — edit field (scope + editor)",
        )


async def test_config_center_edit_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The preview stage: target file, effective merge, validation, and diff."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr("sase.config.edit.get_use_chezmoi", lambda: False)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        modal = await _open_edit_modal(page, "timezone")
        modal.query_one("#config-edit-input", SingleLineVimTextArea).text = "UTC"
        modal.action_confirm()  # plan -> preview
        await wait_for_state(
            page,
            lambda: modal._plan is not None and modal._stage == "preview",
            description="Config edit preview plan",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_edit_preview_120x40",
            title="ACE SASE Admin Center — edit preview (diff + validation)",
        )


async def test_config_center_edit_normal_mode_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The string editor after Escape: the ``[NORMAL]`` border + vim cursor."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr("sase.config.edit.get_use_chezmoi", lambda: False)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        modal = await _open_edit_modal(page, "timezone")
        editor = modal.query_one("#config-edit-input", SingleLineVimTextArea)
        editor.focus()
        await page.press("escape")  # INSERT -> NORMAL
        await wait_for_state(
            page,
            lambda: editor._vim_mode == "normal" and editor.has_focus,
            description="Config edit NORMAL-mode focus",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_edit_normal_mode_120x40",
            title="ACE SASE Admin Center — edit field (vim NORMAL mode)",
        )


async def test_config_center_edit_enum_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The edit stage for a key-driven enum option list."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr("sase.config.edit.get_use_chezmoi", lambda: False)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await _open_edit_modal(page, "mode")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_edit_enum_120x40",
            title="ACE SASE Admin Center — edit field (enum option list)",
        )


async def test_config_center_edit_object_value_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Large object values show a capped current block plus the YAML editor."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr("sase.config.edit.get_use_chezmoi", lambda: False)
    _patch_config_view(
        monkeypatch,
        _build_view(
            _config_schema(object_value=True), _config_layers(object_value=True)
        ),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await _open_edit_modal(page, "ace.lumberjack")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_edit_object_value_120x40",
            title="ACE SASE Admin Center — edit object value (capped current block)",
        )
