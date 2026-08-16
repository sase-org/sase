"""Mounted Models panel key action tests (dismiss, override, clear, guards)."""

from unittest.mock import MagicMock

import pytest

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.model_picker_modal import ModelPickerModal
from sase.ace.tui.modals.models_panel import ModelsPanel, ModelsPanelResult
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    highlight_row,
    make_alias_view,
    make_bucketed_views,
    make_override,
    make_worker_bucket_views,
    patch_alias_views,
)


async def test_panel_escape_closes_unchanged(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    result: ModelsPanelResult | None = None

    async with ModelsPanelTestApp().run_test() as pilot:

        def on_dismiss(value: ModelsPanelResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(ModelsPanel(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert isinstance(result, ModelsPanelResult)
    assert result.changed is False


async def test_panel_o_opens_model_picker(monkeypatch) -> None:
    patch_alias_views(monkeypatch, make_worker_bucket_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelPickerModal)


async def test_panel_x_clears_active_override(monkeypatch) -> None:
    patch_alias_views(
        monkeypatch,
        [
            make_alias_view("xsmall", "role"),
            make_alias_view("small", "role", override=make_override()),
            make_alias_view("medium", "role"),
            make_alias_view("large", "role"),
        ],
    )
    clear_mock = MagicMock(return_value=True)
    monkeypatch.setattr(models_panel, "clear_alias_override", clear_mock)
    result: ModelsPanelResult | None = None

    async with ModelsPanelTestApp().run_test() as pilot:

        def on_dismiss(value: ModelsPanelResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(ModelsPanel(), callback=on_dismiss)
        await pilot.pause()
        panel = pilot.app.screen
        assert isinstance(panel, ModelsPanel)
        highlight_row(panel, "small")
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    clear_mock.assert_called_once_with("small")
    assert isinstance(result, ModelsPanelResult)
    assert result.changed is True


async def test_panel_x_without_override_does_not_clear(monkeypatch) -> None:
    patch_alias_views(monkeypatch, make_worker_bucket_views())
    clear_mock = MagicMock()
    monkeypatch.setattr(models_panel, "clear_alias_override", clear_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()
        clear_mock.assert_not_called()
        assert panel._changed is False


@pytest.mark.parametrize("member_steps", [[], ["j", "j"]])
async def test_panel_size_aliases_open_override_picker(
    monkeypatch, member_steps: list[str]
) -> None:
    patch_alias_views(monkeypatch, make_worker_bucket_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press(*member_steps, "o")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelPickerModal)


@pytest.mark.parametrize("key", ["o", "x", "e", "r"])
async def test_alias_actions_on_bucket_are_guarded(monkeypatch, key: str) -> None:
    patch_alias_views(monkeypatch, make_bucketed_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "bucket:research")
        await pilot.press(key)
        await pilot.pause()

        assert pilot.app.screen is panel
        panel.notify.assert_called_once_with("Press `l`/`enter` to open this bucket")
