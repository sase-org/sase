"""Widget tests for mini-xprompt target pane lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui.modals.mini_xprompt_name_modal import MiniXPromptNameResult
from sase.ace.tui.modals.mini_xprompt_target_catalog import (
    MiniXPromptDestinationTarget,
)
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.naming import SaveResolution
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
from sase.xprompt.save import SaveTargetFormat
from tests.ace.tui.widgets.prompt_stack_submit_cancel_test_support import CaptureApp


def _destination(tmp_path: Path, name: str = "review") -> MiniXPromptDestinationTarget:
    path = tmp_path / f"{name}.md"
    return MiniXPromptDestinationTarget(
        name=name,
        location_path=str(tmp_path),
        path=str(path),
        display_path=f"~/sase/xprompts/{name}.md",
        target_format=SaveTargetFormat.MARKDOWN,
        entry_name=None,
        storage_name=name,
        read_path=str(path),
        write_path=str(path),
        apply_target=None,
        via_chezmoi=False,
        exists_here=path.exists(),
        resolution=SaveResolution(),
    )


def _name_result(
    tmp_path: Path,
    *,
    name: str = "review",
    action: str = "create",
) -> MiniXPromptNameResult:
    return MiniXPromptNameResult(
        name=name,
        action=action,  # type: ignore[arg-type]
        destination=_destination(tmp_path, name),
        definition=None,
        existing_definition=None,
    )


async def _open_mini(
    pilot: Any,
    bar: PromptInputBar,
    result: MiniXPromptNameResult,
    *,
    origin_pane_id: str | None = None,
    body: str = "mini body",
    frontmatter: str = "",
    destination_exists: bool = False,
) -> None:
    if origin_pane_id is None:
        origin_pane_id = bar.active_text_area().id or ""
    assert bar.open_mini_xprompt_target_pane(
        result,
        origin_pane_id=origin_pane_id,
        body=body,
        frontmatter=frontmatter,
        loaded_markdown=None,
        loaded_fingerprint=None,
        destination_exists=destination_exists,
    )
    await pilot.pause()
    await pilot.pause()


async def test_request_mini_xprompt_target_posts_origin(tmp_path: Path) -> None:
    del tmp_path
    app = CaptureApp("draft")

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        bar.request_mini_xprompt_target_pane()
        await pilot.pause()

        assert len(app.mini_xprompt_target_requested) == 1
        event = app.mini_xprompt_target_requested[0]
        assert event.origin_bar is bar
        assert event.origin_pane_id == bar.active_text_area().id
        assert event.initial_name == ""


async def test_open_mini_pane_prefills_body_and_excludes_agent_payload(
    tmp_path: Path,
) -> None:
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(90, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)

        await _open_mini(pilot, bar, _name_result(tmp_path), body="copied body")

        assert bar._stack.mini_xprompt_index == 1
        assert bar._stack.selected_item.is_mini_xprompt_pane
        assert bar.all_prompt_texts() == ["agent prompt"]
        assert bar.current_prompt_text() == "agent prompt"
        assert bar.active_text() == "copied body"
        assert bar.active_text_area()._vim_mode == "insert"


async def test_enter_in_mini_pane_requests_save_without_launch(tmp_path: Path) -> None:
    app = CaptureApp("first\n---\nsecond")

    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_mini(pilot, bar, _name_result(tmp_path), body="body")

        await pilot.press("enter")
        await pilot.pause()

        assert app.submitted == []
        assert len(app.mini_xprompt_pane_save_requested) == 1
        assert app.mini_xprompt_pane_save_requested[0].origin_bar is bar


async def test_mark_mini_changed_on_disk_renders_stale_marker(tmp_path: Path) -> None:
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(100, 28)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_mini(
            pilot,
            bar,
            _name_result(tmp_path, action="edit"),
            body="loaded body",
            destination_exists=True,
        )
        mini = bar._stack.mini_xprompt_item
        assert mini is not None

        assert bar.mark_mini_xprompt_changed_on_disk(
            item_id=mini.item_id,
            changed=True,
        )
        await pilot.pause()

        separator = bar.query_one(f"#{bar._sep_id(mini)}")
        assert "⚠ changed on disk" in separator.render().plain
        assert bar.has_class("mini-xprompt-dirty")

        assert bar.mark_mini_xprompt_changed_on_disk(
            item_id=mini.item_id,
            changed=False,
        )
        await pilot.pause()

        assert "✓" in separator.render().plain
        assert not bar.has_class("mini-xprompt-dirty")


async def test_mini_pane_blocks_agent_editor_history_and_search(
    tmp_path: Path,
) -> None:
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(90, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_mini(pilot, bar, _name_result(tmp_path), body="mini needle")

        mini_area = bar.active_text_area()
        mini_area.action_open_editor()
        mini_area.action_open_prompt_history()
        await pilot.pause()

        assert app.editor_requested == []
        assert app.all_editor_requested == []
        assert app.history_requested == []
        snapshot = bar._prompt_search_pane_snapshot("needle")
        assert all(pane.text_area is not mini_area for pane in snapshot)
        assert all(pane.spans == () for pane in snapshot)


async def test_close_mini_restores_exact_cursor_and_mode_with_clamp(
    tmp_path: Path,
) -> None:
    app = CaptureApp("alpha\nbeta")

    async with app.run_test(size=(90, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        origin = bar.active_text_area()
        origin.cursor_location = (1, 2)
        origin._enter_normal_mode()
        origin_id = origin.id or ""

        await _open_mini(
            pilot,
            bar,
            _name_result(tmp_path),
            origin_pane_id=origin_id,
            body="mini body",
        )

        agent_area = app.query_one(
            f"#{bar._pane_id(bar._stack.items[0])}", PromptTextArea
        )
        agent_area.text = "a"
        bar._sync_state_from_widgets()

        assert bar.close_mini_xprompt_target("discarded")
        await pilot.pause()
        await pilot.pause()

        restored = bar.active_text_area()
        assert restored is app.query_one(f"#{bar._pane_id(bar._stack.items[0])}")
        assert restored.text == "a"
        assert restored.cursor_location == (0, 1)
        assert restored._vim_mode == "normal"
        assert restored.has_focus


async def test_mini_retarget_preserves_body_and_frontmatter(tmp_path: Path) -> None:
    frontmatter = "---\ndescription: draft\n---"
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(90, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        await _open_mini(
            pilot,
            bar,
            _name_result(tmp_path, name="old"),
            body="loaded",
            frontmatter=frontmatter,
        )
        bar.active_text_area().text = "user draft"
        bar._sync_state_from_widgets()

        assert bar.open_mini_xprompt_target_pane(
            _name_result(tmp_path, name="new"),
            origin_pane_id=bar.active_text_area().id or "",
            body="new loaded",
            frontmatter="---\ndescription: new\n---",
            loaded_markdown=None,
            loaded_fingerprint=None,
            destination_exists=False,
        )

        assert bar.active_text() == "user draft"
        target = bar._stack.mini_xprompt_item.mini_xprompt_target
        assert target is not None
        assert target.name == "new"
        assert target.frontmatter == frontmatter


async def test_mini_frontmatter_scope_isolated_from_agent_stack(
    tmp_path: Path,
) -> None:
    agent_frontmatter = "---\nxprompts:\n  _agent: agent helper\n---"
    mini_frontmatter = "---\nxprompts:\n  _mini: mini helper\n---"
    app = CaptureApp("agent prompt")

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        bar = app.query_one(PromptInputBar)
        bar._stack.frontmatter = agent_frontmatter
        await _open_mini(
            pilot,
            bar,
            _name_result(tmp_path),
            body="mini body",
            frontmatter=mini_frontmatter,
        )
        agent_area = app.query_one(
            f"#{bar._pane_id(bar._stack.items[0])}",
            PromptTextArea,
        )
        mini_area = bar.active_text_area()

        assert [
            entry.name for entry in bar.local_xprompt_assist_entries(agent_area)
        ] == ["_agent"]
        assert [
            entry.name for entry in bar.local_xprompt_assist_entries(mini_area)
        ] == ["_mini"]

        bar.focus_frontmatter_panel()
        await pilot.pause()
        panel = app.query_one(FrontmatterPanel)
        assert "#review" in str(panel.border_title)
        assert "_mini" in panel.model.xprompts

        model = PromptFrontmatter.parse(mini_frontmatter)
        model.description = "mini only"
        bar.on_frontmatter_panel_changed(FrontmatterPanel.Changed(model))

        target = bar._stack.mini_xprompt_item.mini_xprompt_target
        assert target is not None
        assert PromptFrontmatter.parse(target.frontmatter).description == "mini only"
        assert bar._stack.frontmatter == agent_frontmatter
