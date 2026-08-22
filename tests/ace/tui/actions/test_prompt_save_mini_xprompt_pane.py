"""Mini-xprompt-pane workflows for prompt-bar saves."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import threading
from unittest.mock import patch

import yaml  # type: ignore[import-untyped]
from textual.pilot import Pilot

from sase.ace.tui.actions.agent_workflow import (
    _prompt_bar_save_xprompt_mini as mini_xprompt_save_mod,
)
from sase.ace.tui.modals.mini_xprompt_name_modal import MiniXPromptNameResult
from sase.ace.tui.modals.mini_xprompt_save_confirm_modal import (
    MiniXPromptSaveConfirmModal,
)
from sase.ace.tui.modals.mini_xprompt_target_catalog import (
    MiniXPromptDestinationTarget,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_stack import SourceFingerprint, split_frontmatter
from sase.xprompt.naming import SaveResolution
from sase.xprompt.save import SaveTargetFormat

from ._prompt_save_xprompt_helpers import _SaveFlowApp, _wait_save_tasks


def _mini_destination(
    path: Path,
    *,
    name: str = "review",
    target_format: SaveTargetFormat = SaveTargetFormat.MARKDOWN,
) -> MiniXPromptDestinationTarget:
    entry_name = None if target_format is SaveTargetFormat.MARKDOWN else name
    location_path = str(
        path.parent if target_format is SaveTargetFormat.MARKDOWN else path
    )
    return MiniXPromptDestinationTarget(
        name=name,
        location_path=location_path,
        path=str(path),
        display_path=str(path),
        target_format=target_format,
        entry_name=entry_name,
        storage_name=name,
        read_path=str(path),
        write_path=str(path),
        apply_target=None,
        via_chezmoi=False,
        exists_here=path.exists(),
        resolution=SaveResolution(),
    )


async def _open_mini_xprompt_pane(
    pilot: Pilot[None],
    bar: PromptInputBar,
    path: Path,
    *,
    name: str = "review",
    body: str,
    frontmatter: str = "",
    loaded_markdown: str | None = None,
    target_format: SaveTargetFormat = SaveTargetFormat.MARKDOWN,
) -> None:
    result = MiniXPromptNameResult(
        name=name,
        action="edit" if loaded_markdown is not None else "create",
        destination=_mini_destination(path, name=name, target_format=target_format),
        definition=None,
        existing_definition=None,
    )
    fingerprint = SourceFingerprint.from_path(path) if path.exists() else None
    loaded_frontmatter = frontmatter
    loaded_body = body
    if loaded_markdown is not None:
        loaded_frontmatter, loaded_body = split_frontmatter(loaded_markdown)
    assert bar.open_mini_xprompt_target_pane(
        result,
        origin_pane_id=bar.active_text_area().id or "",
        body=loaded_body,
        frontmatter=loaded_frontmatter,
        loaded_markdown=loaded_markdown,
        loaded_fingerprint=fingerprint,
        destination_exists=loaded_markdown is not None,
    )
    await pilot.pause()
    mini = bar._stack.mini_xprompt_item
    if mini is not None and mini.mini_xprompt_target is not None:
        mini.mini_xprompt_target = replace(
            mini.mini_xprompt_target,
            frontmatter=frontmatter,
        )
    bar.active_text_area().text = body
    bar._sync_state_from_widgets()


async def test_mini_xprompt_pane_markdown_save_writes_and_closes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.md"
    app = _SaveFlowApp("agent prompt")

    with patch("sase.xprompt.save_state.save_last_used_location", return_value=True):
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await _open_mini_xprompt_pane(
                pilot,
                bar,
                path,
                body="Check this",
                frontmatter="---\ndescription: Review\n---",
            )

            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()
            assert isinstance(app.screen, MiniXPromptSaveConfirmModal)

            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()

            assert path.read_text(encoding="utf-8") == (
                "---\ndescription: Review\n---\n\nCheck this\n"
            )
            assert not bar._stack.has_mini_xprompt_pane
            assert ("Created mini-xprompt '#review'", None) in app.notifications


async def test_mini_xprompt_pane_config_save_writes_entry(
    tmp_path: Path,
) -> None:
    config = tmp_path / "sase.yml"
    config.write_text("theme: dark\n", encoding="utf-8")
    app = _SaveFlowApp("agent prompt")

    with patch("sase.xprompt.save_state.save_last_used_location", return_value=True):
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await _open_mini_xprompt_pane(
                pilot,
                bar,
                config,
                body="Check this",
                frontmatter="---\ndescription: Review\n---",
                target_format=SaveTargetFormat.CONFIG,
            )

            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()

            payload = yaml.safe_load(config.read_text(encoding="utf-8"))
            assert payload["xprompts"]["review"] == {
                "description": "Review",
                "content": "Check this",
            }
            assert not bar._stack.has_mini_xprompt_pane


async def test_mini_xprompt_save_review_loads_disk_state_off_event_loop(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.md"
    app = _SaveFlowApp("agent prompt")
    entered = threading.Event()
    release = threading.Event()
    worker_threads: list[int] = []
    loop_thread = threading.get_ident()
    original = mini_xprompt_save_mod.load_mini_xprompt_save_disk_state

    def _slow_disk_state(target: object) -> object:
        worker_threads.append(threading.get_ident())
        entered.set()
        release.wait(timeout=1.0)
        return original(target)  # type: ignore[arg-type]

    try:
        with patch.object(
            mini_xprompt_save_mod,
            "load_mini_xprompt_save_disk_state",
            side_effect=_slow_disk_state,
        ):
            async with app.run_test(size=(100, 30)) as pilot:
                await pilot.pause()
                bar = app.query_one(PromptInputBar)
                await _open_mini_xprompt_pane(
                    pilot,
                    bar,
                    path,
                    body="draft body",
                )

                await pilot.press("enter")
                await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=0.5)
                assert worker_threads
                assert worker_threads[0] != loop_thread

                heartbeat = asyncio.Event()
                asyncio.get_running_loop().call_soon(heartbeat.set)
                await asyncio.wait_for(heartbeat.wait(), timeout=0.05)
                assert bar._stack.has_mini_xprompt_pane

                release.set()
                await _wait_save_tasks(app)
    finally:
        release.set()


async def test_mini_xprompt_pane_failed_write_keeps_draft(tmp_path: Path) -> None:
    path = tmp_path / "review.md"
    app = _SaveFlowApp("agent prompt")

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_mini_xprompt_pane(
            pilot,
            bar,
            path,
            body="draft body",
        )

        await pilot.press("enter")
        await _wait_save_tasks(app)
        await pilot.pause()
        with patch(
            "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_mini.write_mini_xprompt_sync",
            side_effect=RuntimeError("boom"),
        ):
            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()

        assert bar._stack.has_mini_xprompt_pane
        assert bar.active_text() == "draft body"
        assert ("Failed to save mini-xprompt: boom", "error") in app.notifications


async def test_mini_xprompt_pane_changed_on_disk_requires_overwrite(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.md"
    loaded_markdown = "---\ndescription: Old\n---\n\nold body\n"
    path.write_text(loaded_markdown, encoding="utf-8")
    app = _SaveFlowApp("agent prompt")

    with patch("sase.xprompt.save_state.save_last_used_location", return_value=True):
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            bar = app.query_one(PromptInputBar)
            await _open_mini_xprompt_pane(
                pilot,
                bar,
                path,
                body="draft body",
                frontmatter="---\ndescription: Draft\n---",
                loaded_markdown=loaded_markdown,
            )
            path.write_text("disk body changed\n", encoding="utf-8")

            await pilot.press("enter")
            await _wait_save_tasks(app)
            await pilot.pause()
            assert isinstance(app.screen, MiniXPromptSaveConfirmModal)

            await pilot.press("enter")
            await pilot.pause()
            assert path.read_text(encoding="utf-8") == "disk body changed\n"
            assert isinstance(app.screen, MiniXPromptSaveConfirmModal)
            assert bar._stack.has_mini_xprompt_pane

            await pilot.press("o")
            await _wait_save_tasks(app)
            await pilot.pause()

            assert path.read_text(encoding="utf-8") == (
                "---\ndescription: Draft\n---\n\ndraft body\n"
            )
            assert not bar._stack.has_mini_xprompt_pane


async def test_mini_xprompt_pane_changed_on_disk_reload_updates_draft(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.md"
    loaded_markdown = "old body\n"
    path.write_text(loaded_markdown, encoding="utf-8")
    app = _SaveFlowApp("agent prompt")

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_mini_xprompt_pane(
            pilot,
            bar,
            path,
            body="draft body",
            loaded_markdown=loaded_markdown,
        )
        path.write_text(
            "---\ndescription: Disk\n---\n\ndisk body changed\n",
            encoding="utf-8",
        )

        await pilot.press("enter")
        await _wait_save_tasks(app)
        await pilot.pause()
        assert isinstance(app.screen, MiniXPromptSaveConfirmModal)

        await pilot.press("r")
        await pilot.pause()

        assert bar._stack.has_mini_xprompt_pane
        assert bar.active_text() == "disk body changed\n"
        mini = bar._stack.mini_xprompt_item
        assert mini is not None
        assert mini.mini_xprompt_target is not None
        assert mini.mini_xprompt_target.loaded_body == "disk body changed\n"
