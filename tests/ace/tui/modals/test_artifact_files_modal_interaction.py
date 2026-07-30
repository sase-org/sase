"""Interaction tests for the artifact-file selection modal."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.tui.modals.artifact_files_modal import (
    ArtifactFileSelectionModal,
    ArtifactFileSelectionResult,
    _artifact_file_option_text,
    _artifact_file_selector_keys,
)
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.copy_as_modal import CopyAsModal
from tests.ace.tui.modals.artifact_files_modal_test_helpers import (
    _TestApp,
    _artifact,
)


async def test_artifact_file_modal_single_key_selection_supports_more_than_nine() -> (
    None
):
    artifacts = [_artifact(index) for index in range(12)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("0")
        await pilot.pause()

    assert result is artifacts[9]


async def test_artifact_file_modal_letter_selector_skips_navigation_and_quit_keys() -> (
    None
):
    artifacts = [_artifact(index) for index in range(16)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("f")
        await pilot.pause()

    assert "j" not in _artifact_file_selector_keys(16)
    assert "k" not in _artifact_file_selector_keys(16)
    assert "m" not in _artifact_file_selector_keys(25)
    assert "q" not in _artifact_file_selector_keys(16)
    assert "y" not in _artifact_file_selector_keys(35)
    assert "Y" not in _artifact_file_selector_keys(35)
    assert "z" not in _artifact_file_selector_keys(35)
    assert result is artifacts[15]


async def test_artifact_file_modal_escape_and_q_cancel() -> None:
    for key in ("escape", "q"):
        result: object | None = "sentinel"
        async with _TestApp().run_test() as pilot:

            def on_dismiss(value: object | None) -> None:
                nonlocal result
                result = value

            modal = ArtifactFileSelectionModal([_artifact(1)])
            pilot.app.push_screen(modal, callback=on_dismiss)
            await pilot.pause()

            await pilot.press(key)
            await pilot.pause()

        assert result is None


async def test_artifact_file_modal_enter_opens_highlighted_unkeyed_artifact() -> None:
    artifacts = [_artifact(index) for index in range(36)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#agent-artifact-files-list", OptionList)
        option_list.highlighted = 35
        await pilot.press("enter")
        await pilot.pause()

    assert result is artifacts[35]


async def test_artifact_file_modal_marks_return_in_list_order() -> None:
    artifacts = [_artifact(index) for index in range(4)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#agent-artifact-files-list", OptionList)
        option_list.highlighted = 2
        await pilot.press("m")
        option_list.highlighted = 0
        await pilot.press("m")
        await pilot.press("enter")
        await pilot.pause()

    assert result == [artifacts[0], artifacts[2]]


async def test_artifact_file_modal_zoom_open_returns_highlighted_artifact() -> None:
    artifacts = [_artifact(index) for index in range(4)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#agent-artifact-files-list", OptionList)
        option_list.highlighted = 2
        await pilot.press("z")
        await pilot.pause()

    assert result == ArtifactFileSelectionResult([artifacts[2]], zoom=True)


async def test_artifact_file_modal_zoom_open_returns_marks_in_list_order() -> None:
    artifacts = [_artifact(index) for index in range(4)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#agent-artifact-files-list", OptionList)
        option_list.highlighted = 2
        await pilot.press("m")
        option_list.highlighted = 0
        await pilot.press("m")
        await pilot.press("z")
        await pilot.pause()

    assert result == ArtifactFileSelectionResult(
        [artifacts[0], artifacts[2]],
        zoom=True,
    )


async def test_artifact_file_modal_open_all_returns_all_artifact_files_in_list_order() -> (
    None
):
    artifacts = [_artifact(index) for index in range(4)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("A")
        await pilot.pause()

    assert result == artifacts
    assert result is not artifacts


async def test_artifact_file_modal_open_all_ignores_existing_marks() -> None:
    artifacts = [_artifact(index) for index in range(4)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#agent-artifact-files-list", OptionList)
        option_list.highlighted = 2
        await pilot.press("m")
        option_list.highlighted = 0
        await pilot.press("m")
        await pilot.press("A")
        await pilot.pause()

    assert result == artifacts


async def test_artifact_file_modal_mark_advances_highlight() -> None:
    artifacts = [_artifact(index) for index in range(3)]

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#agent-artifact-files-list", OptionList)
        option_list.highlighted = 0
        await pilot.press("m")
        await pilot.pause()

        assert option_list.highlighted == 1


async def test_artifact_file_modal_mark_wraps_highlight_to_first_row() -> None:
    artifacts = [_artifact(index) for index in range(3)]

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#agent-artifact-files-list", OptionList)
        option_list.highlighted = 2
        await pilot.press("m")
        await pilot.pause()

        assert option_list.highlighted == 0


async def test_artifact_file_modal_hint_includes_open_all_and_mark_count() -> None:
    artifacts = [_artifact(index) for index in range(3)]

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert "A: open all" in modal._hint_text()
        assert "z: zoom open" in modal._hint_text()
        assert "y: copy" in modal._hint_text()
        assert "Y: path" in modal._hint_text()
        assert "marked:" not in modal._hint_text()

        option_list = modal.query_one("#agent-artifact-files-list", OptionList)
        option_list.highlighted = 1
        await pilot.press("m")
        await pilot.pause()

        assert "A: open all" in modal._hint_text()
        assert "z: zoom open" in modal._hint_text()
        assert "y: copy" in modal._hint_text()
        assert "Y: path" in modal._hint_text()
        assert modal._hint_text().endswith("marked: 1")


async def test_artifact_file_modal_uses_configured_copy_prefix() -> None:
    async with _TestApp().run_test() as pilot:
        pilot.app._keymap_registry = load_keymap_registry(
            {
                "keymaps": {
                    "modes": {
                        "copy_mode": {
                            "prefix": ";",
                        }
                    }
                }
            }
        )
        modal = ArtifactFileSelectionModal([_artifact(1)])
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert ";: Copy as…" in modal._hint_text()
        await pilot.press(";")

        assert isinstance(pilot.app.screen, CopyAsModal)


async def test_artifact_file_modal_title_shows_agent_count_when_multiple() -> None:
    artifacts = [_artifact(index) for index in range(3)]
    labels: list[str | None] = ["foo", "foo", "bar"]

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal(
            artifacts,
            agent_labels=labels,
            agent_count=2,
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        assert modal._title_text() == "Artifact Files  [3 from 2 agents]"


async def test_artifact_file_modal_rejects_misaligned_agent_labels() -> None:
    with pytest.raises(ValueError):
        ArtifactFileSelectionModal(
            [_artifact(1), _artifact(2)],
            agent_labels=["only-one"],
            agent_count=2,
        )


def test_artifact_file_modal_labels_video_suffix_as_video() -> None:
    artifact = _artifact(1, path="/tmp/render.mp4", kind="file")

    text = _artifact_file_option_text("1", artifact)

    assert "[video]" in text.plain
    assert "[file]" not in text.plain
