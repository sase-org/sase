"""Snippet-pane workflows for prompt-bar saves."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import yaml  # type: ignore[import-untyped]
from textual.pilot import Pilot
from textual.widgets import Static

from sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane import (
    PromptBarSnippetPaneMixin,
)
from sase.ace.tui.modals import ConfirmActionModal
from sase.ace.tui.modals.snippet_name_modal import (
    SnippetNameModal,
    SnippetNameResult,
)
from sase.ace.tui.modals.snippet_save_confirm_modal import SnippetSaveConfirmModal
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_stack import SourceFingerprint
from sase.xprompt.snippet_targets import SnippetConfigLocation, SnippetSaveTarget

from ._prompt_save_xprompt_helpers import _SaveFlowApp, _wait_save_tasks


class _SnippetFlowApp(PromptBarSnippetPaneMixin, _SaveFlowApp):
    """Save-flow app with the snippet target-name handler enabled."""


class _SubmitCaptureApp(_SaveFlowApp):
    """Save-flow app that records prompt launches."""

    def __init__(self, initial_value: str) -> None:
        super().__init__(initial_value)
        self.submitted: list[PromptInputBar.Submitted] = []

    def on_prompt_input_bar_submitted(self, event: PromptInputBar.Submitted) -> None:
        self.submitted.append(event)


async def _wait_snippet_tasks(harness: object) -> None:
    tasks = list(getattr(harness, "_snippet_pane_async_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)


def _write_snippet_config(path: Path, snippets: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump({"ace": {"snippets": snippets}}),
        encoding="utf-8",
    )


def _pane_target(path: Path) -> SnippetSaveTarget:
    return SnippetSaveTarget(
        read_path=path,
        write_path=path,
        apply_target=None,
        via_chezmoi=False,
        display_path=str(path),
        source="configured",
        fallback_reason=None,
    )


async def _open_snippet_pane(
    pilot: Pilot[None],
    bar: PromptInputBar,
    path: Path,
    *,
    trigger: str = "todo",
    existing_body: str | None = None,
    body: str,
) -> None:
    result = SnippetNameResult(
        trigger=trigger,
        target=_pane_target(path),
        exists=existing_body is not None,
        existing_body=existing_body,
        derived_from=None,
    )
    fingerprint = SourceFingerprint.from_path(path)
    assert bar.open_snippet_target_pane(
        result,
        origin_pane_id=bar.active_text_area().id or "",
        destination_exists=existing_body is not None,
        loaded_fingerprint=fingerprint,
    )
    await pilot.pause()
    bar.active_text_area().text = body
    bar._sync_state_from_widgets()


async def test_gt_new_snippet_loop_writes_publishes_expands_and_restores_cursor(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    app = _SnippetFlowApp("agent prompt")
    target = _pane_target(config)

    with (
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane._resolve_snippet_target",
            return_value=target,
        ),
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane._load_snippet_locations",
            return_value=[
                SnippetConfigLocation(
                    "User sase.yml",
                    str(config),
                    str(config),
                )
            ],
        ),
        patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_snippet_pane._load_derived_snippet_catalog",
            return_value=({}, {}),
        ),
        patch("sase.xprompt.save_state.save_last_used_location", return_value=True),
    ):
        async with app.run_test(size=(110, 34)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await pilot.press("escape")
            origin = bar.active_text_area()
            origin.cursor_location = (0, 6)
            original_mode = origin._vim_mode
            original_cursor = origin.cursor_location

            await pilot.press("g", "t")
            await pilot.pause(0.3)
            assert isinstance(app.screen, SnippetNameModal)

            await pilot.press("t", "o", "d", "o")
            await pilot.pause(0.3)
            modal = app.screen
            assert isinstance(modal, SnippetNameModal)
            assert (
                "Create ⇥ todo"
                in modal.query_one("#snippet-name-verdict", Static).render().plain
            )
            assert (
                str(config)
                in modal.query_one("#snippet-name-destination", Static).render().plain
            )

            await pilot.press("enter")
            await _wait_snippet_tasks(app)
            await pilot.pause()
            assert bar._stack.has_snippet_pane
            assert bar.active_text() == ""

            bar.active_text_area().text = "TODO($1): $0"
            bar._sync_state_from_widgets()
            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()
            assert isinstance(app.screen, SnippetSaveConfirmModal)
            preview = app.screen.query_one("#snippet-save-confirm-preview", Static)
            preview_renderable = getattr(preview, "_Static__content", preview.render())
            preview_text = getattr(
                preview_renderable,
                "code",
                getattr(preview_renderable, "plain", str(preview_renderable)),
            )
            assert "    todo: |-" in preview_text

            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()
            assert not bar._stack.has_snippet_pane
            assert bar.active_text_area()._vim_mode == original_mode
            assert bar.active_text_area().cursor_location == original_cursor

            payload = yaml.safe_load(config.read_text(encoding="utf-8"))
            assert payload["ace"]["snippets"] == {"todo": "TODO($1): $0"}
            assert app._pending_snippet_saves == {"todo": "TODO($1): $0"}
            assert app._snippets_cache is not None
            assert app._snippets_cache["todo"] == "TODO($1): $0"

            text_area = bar.active_text_area()
            text_area._enter_insert_mode()
            text_area.load_text("todo")
            text_area.cursor_location = (0, len("todo"))
            with patch.object(
                type(text_area),
                "_ace_app",
                new_callable=lambda: property(lambda _self: app),
            ):
                assert text_area._try_expand_snippet() is True
            assert text_area.text == "TODO(): "


async def test_dirty_snippet_cancel_confirms_and_restores_origin_cursor(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    app = _SaveFlowApp("agent prompt")

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        origin = bar.active_text_area()
        origin.cursor_location = (0, 5)
        original_cursor = origin.cursor_location
        await _open_snippet_pane(
            pilot,
            bar,
            config,
            existing_body=None,
            body="draft body",
        )

        await pilot.press("ctrl+c")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmActionModal)
        assert bar._stack.has_snippet_pane

        await pilot.press("y")
        await pilot.pause()
        assert not bar._stack.has_snippet_pane
        assert bar.active_text_area().cursor_location == original_cursor


async def test_launch_with_dirty_snippet_confirms_and_excludes_snippet_payload(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    app = _SubmitCaptureApp("launch me")

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet_pane(
            pilot,
            bar,
            config,
            existing_body=None,
            body="snippet draft must not launch",
        )
        assert bar._stack.has_snippet_pane
        bar.focus_item(0)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmActionModal)
        assert app.submitted == []

        await pilot.press("y")
        await pilot.pause()
        assert [event.value for event in app.submitted] == ["launch me"]
        assert app.submitted[0].whole_stack is False


async def test_snippet_pane_confirmation_save_writes_publishes_and_closes(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    app = _SaveFlowApp("agent prompt")

    with patch("sase.xprompt.save_state.save_last_used_location", return_value=True):
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await _open_snippet_pane(
                pilot,
                bar,
                config,
                existing_body=None,
                body="TODO($1): $0",
            )

            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()
            assert isinstance(app.screen, SnippetSaveConfirmModal)

            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()

            payload = yaml.safe_load(config.read_text(encoding="utf-8"))
            assert payload["ace"]["snippets"] == {"todo": "TODO($1): $0"}
            assert app._pending_snippet_saves == {"todo": "TODO($1): $0"}
            assert app._snippets_cache is not None
            assert app._snippets_cache["todo"] == "TODO($1): $0"
            assert not bar._stack.has_snippet_pane


async def test_snippet_pane_failed_write_keeps_draft(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {})
    app = _SaveFlowApp("agent prompt")

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet_pane(
            pilot,
            bar,
            config,
            existing_body=None,
            body="draft body",
        )

        await pilot.press("enter")
        await _wait_save_tasks(app)
        await pilot.pause()
        with patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_snippets.write_snippet_sync",
            side_effect=RuntimeError("boom"),
        ):
            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()

        assert bar._stack.has_snippet_pane
        assert bar.active_text() == "draft body"
        assert ("Failed to save snippet: boom", "error") in app.notifications


async def test_snippet_pane_no_change_closes_without_write(tmp_path: Path) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "same body"})
    app = _SaveFlowApp("agent prompt")

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet_pane(
            pilot,
            bar,
            config,
            existing_body="same body",
            body="same body",
        )

        await pilot.press("enter")
        await _wait_save_tasks(app)
        await pilot.pause()
        with patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_snippets.write_snippet_sync"
        ) as write_sync:
            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()

        write_sync.assert_not_called()
        assert not bar._stack.has_snippet_pane


async def test_snippet_pane_changed_on_disk_reload_updates_draft(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    _write_snippet_config(config, {"todo": "old body"})
    app = _SaveFlowApp("agent prompt")

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_snippet_pane(
            pilot,
            bar,
            config,
            existing_body="old body",
            body="draft body",
        )
        _write_snippet_config(config, {"todo": "disk body changed"})

        await pilot.press("enter")
        await _wait_save_tasks(app)
        await pilot.pause()
        assert isinstance(app.screen, SnippetSaveConfirmModal)

        await pilot.press("r")
        await pilot.pause()

        assert bar._stack.has_snippet_pane
        assert bar.active_text() == "disk body changed"
        snippet = bar._stack.snippet_item
        assert snippet is not None
        assert snippet.snippet_target is not None
        assert snippet.snippet_target.loaded_body == "disk body changed"
