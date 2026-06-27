from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from textual.app import App, ComposeResult
from textual.widgets import Input, Label, OptionList

from sase.ace.tui.modals.snippet_config_location_modal import (
    SnippetConfigLocation,
    SnippetConfigLocationModal,
    load_snippet_config_locations,
)
from sase.ace.tui.modals.snippet_name_modal import SnippetNameModal


class _NameApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, modal: SnippetNameModal) -> None:
        super().__init__()
        self._modal = modal
        self.result: str | None = None
        self.dismissed = False

    def compose(self) -> ComposeResult:
        yield OptionList(id="placeholder")

    def on_mount(self) -> None:
        self.push_screen(self._modal, self._on_result)

    def _on_result(self, result: str | None) -> None:
        self.result = result
        self.dismissed = True


async def test_invalid_trigger_is_rejected_and_does_not_dismiss() -> None:
    app = _NameApp(SnippetNameModal(config_path="/tmp/sase.yml"))

    async with app.run_test(size=(80, 24)) as pilot:
        modal = app.screen
        assert isinstance(modal, SnippetNameModal)
        modal.query_one("#snippet-name-input", Input).value = "bad name!"
        await pilot.pause()
        modal.on_input_submitted(
            Input.Submitted(modal.query_one("#snippet-name-input", Input), "bad name!")
        )
        await pilot.pause()

        assert app.dismissed is False
        error = modal.query_one("#snippet-name-error", Label)
        assert "letters" in str(error.content)


async def test_valid_trigger_dismisses_with_value() -> None:
    app = _NameApp(SnippetNameModal(config_path="/tmp/sase.yml"))

    async with app.run_test(size=(80, 24)) as pilot:
        modal = app.screen
        assert isinstance(modal, SnippetNameModal)
        inp = modal.query_one("#snippet-name-input", Input)
        inp.value = "my_snippet"
        await pilot.pause()
        modal.on_input_submitted(Input.Submitted(inp, "my_snippet"))
        await pilot.pause()

    assert app.result == "my_snippet"


async def test_existing_name_shows_warning_but_allows_submit() -> None:
    app = _NameApp(
        SnippetNameModal(
            config_path="/tmp/sase.yml",
            existing_names={"foo"},
        )
    )

    async with app.run_test(size=(80, 24)) as pilot:
        modal = app.screen
        assert isinstance(modal, SnippetNameModal)
        inp = modal.query_one("#snippet-name-input", Input)
        inp.value = "foo"
        await pilot.pause()
        note = modal.query_one("#snippet-name-note", Label)
        assert "overwrite" in str(note.content)
        modal.on_input_submitted(Input.Submitted(inp, "foo"))
        await pilot.pause()

    assert app.result == "foo"


class _LocationApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, modal: SnippetConfigLocationModal) -> None:
        super().__init__()
        self._modal = modal
        self.result: SnippetConfigLocation | None = None

    def compose(self) -> ComposeResult:
        yield OptionList(id="placeholder")

    def on_mount(self) -> None:
        self.push_screen(self._modal, self._on_result)

    def _on_result(self, result: SnippetConfigLocation | None) -> None:
        self.result = result


async def test_location_modal_skips_disabled_and_selects_writable() -> None:
    disabled = SnippetConfigLocation(
        label="User sase.yml",
        path="/ro/sase.yml",
        display_path="~/ro/sase.yml",
        disabled_reason="read-only",
    )
    writable = SnippetConfigLocation(
        label="Local sase.yml",
        path="/rw/sase.yml",
        display_path="./sase.yml",
    )
    app = _LocationApp(SnippetConfigLocationModal([disabled, writable]))

    async with app.run_test(size=(90, 24)) as pilot:
        modal = app.screen
        assert isinstance(modal, SnippetConfigLocationModal)
        option_list = modal.query_one("#snippet-config-list", OptionList)
        # First selectable row is the writable one, not the read-only one.
        assert option_list.highlighted == 1
        await pilot.press("enter")
        await pilot.pause()

    assert app.result == writable


def test_load_locations_always_offers_user_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    with (
        patch(
            "sase.ace.tui.modals.snippet_config_location_modal.get_use_chezmoi",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.modals.snippet_config_location_modal.CONFIG_DIR",
            config_dir,
        ),
    ):
        locations = load_snippet_config_locations()

    user = next(loc for loc in locations if loc.label == "User sase.yml")
    # Does not exist yet, but the parent dir is writable -> selectable.
    assert user.disabled_reason is None
    assert user.path == str(config_dir / "sase.yml")


def test_load_locations_flags_invalid_yaml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sase.yml").write_text("ace:\n  - : :\n  bad", encoding="utf-8")

    with (
        patch(
            "sase.ace.tui.modals.snippet_config_location_modal.get_use_chezmoi",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.modals.snippet_config_location_modal.CONFIG_DIR",
            config_dir,
        ),
    ):
        locations = load_snippet_config_locations()

    user = next(loc for loc in locations if loc.label == "User sase.yml")
    assert user.disabled_reason == "invalid YAML"


def test_load_locations_includes_existing_overlays(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "sase_work.yml").write_text("ace: {}\n", encoding="utf-8")

    with (
        patch(
            "sase.ace.tui.modals.snippet_config_location_modal.get_use_chezmoi",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.modals.snippet_config_location_modal.CONFIG_DIR",
            config_dir,
        ),
    ):
        labels = [loc.label for loc in load_snippet_config_locations()]

    assert "User sase_work.yml" in labels
