"""Tests for the agent artifact selection modal."""

from __future__ import annotations

from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.modals.agent_artifacts_modal import (
    AgentArtifactSelectionModal,
    _artifact_option_text,
    _artifact_selector_keys,
)


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _artifact(index: int, *, label: str | None = None, path: str | None = None):
    return SimpleNamespace(
        label=label or f"Artifact {index}",
        kind="markdown",
        path=path or f"/tmp/artifact-{index}.md",
    )


async def test_artifact_modal_single_key_selection_supports_more_than_nine() -> None:
    artifacts = [_artifact(index) for index in range(12)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = AgentArtifactSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("0")
        await pilot.pause()

    assert result is artifacts[9]


async def test_artifact_modal_letter_selector_skips_navigation_and_quit_keys() -> None:
    artifacts = [_artifact(index) for index in range(16)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = AgentArtifactSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("f")
        await pilot.pause()

    assert "j" not in _artifact_selector_keys(16)
    assert "k" not in _artifact_selector_keys(16)
    assert "q" not in _artifact_selector_keys(16)
    assert result is artifacts[15]


async def test_artifact_modal_escape_and_q_cancel() -> None:
    for key in ("escape", "q"):
        result: object | None = "sentinel"
        async with _TestApp().run_test() as pilot:

            def on_dismiss(value: object | None) -> None:
                nonlocal result
                result = value

            modal = AgentArtifactSelectionModal([_artifact(1)])
            pilot.app.push_screen(modal, callback=on_dismiss)
            await pilot.pause()

            await pilot.press(key)
            await pilot.pause()

        assert result is None


async def test_artifact_modal_enter_opens_highlighted_unkeyed_artifact() -> None:
    artifacts = [_artifact(index) for index in range(36)]
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = AgentArtifactSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#agent-artifacts-list", OptionList)
        option_list.highlighted = 35
        await pilot.press("enter")
        await pilot.pause()

    assert result is artifacts[35]


def test_artifact_modal_option_text_truncates_long_label_and_path() -> None:
    artifact = _artifact(
        1,
        label="label-" + ("x" * 90),
        path="/tmp/" + "/".join(f"segment-{index:02d}" for index in range(20)),
    )

    plain = _artifact_option_text("1", artifact).plain

    assert "label-" + ("x" * 45) + "..." in plain
    assert "..." in plain
    assert "segment-19" in plain
    assert len(plain.splitlines()[0]) < 90
