"""Widget-level tests for the Config Center Config tab (Phase 4).

These cover the parts the pure helpers cannot: the worker-backed inventory load
populating the tree, the loading→populated transition, the live filter input,
the modified-only toggle, and jump-to-path. The config backend is patched with a
deterministic fixture view so no real config files are read.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from textual.containers import VerticalScroll
from textual.widgets import Input, Tree

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git import (
    GitCommitPushResult,
)
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals.config_commit import ConfigCommitOffer
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.config_pane import ConfigPane
from sase.config.edit import AppliedResult
from sase.config.inventory import build_config_inventory, config_field_model
from tests.test_config_pane import _fixture_layers, _fixture_schema


def _fixture_view() -> cp.ConfigPaneView:
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=_fixture_layers(),
    ):
        inventory = build_config_inventory(schema=_fixture_schema())
    field_model = config_field_model(_fixture_schema())
    return cp.ConfigPaneView.build(field_model, inventory)


def _tall_detail_view() -> cp.ConfigPaneView:
    schema: dict[str, Any] = _fixture_schema()
    schema["properties"]["long_detail"] = {
        "type": "string",
        "default": "builtin",
        "description": "\n".join(
            f"Long detail line {index:02d} for config detail scrolling."
            for index in range(48)
        ),
    }
    layers = _fixture_layers()
    layers[0].data["long_detail"] = "builtin"
    layers[1].data["long_detail"] = "user"
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=layers,
    ):
        inventory = build_config_inventory(schema=schema)
    field_model = config_field_model(schema)
    return cp.ConfigPaneView.build(field_model, inventory)


def _patch_loaders(
    monkeypatch: pytest.MonkeyPatch, view: cp.ConfigPaneView | None = None
) -> cp.ConfigPaneView:
    view = view or _fixture_view()
    result = cp._LoadResult(view=view, error=None, token=("tok", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: result)
    monkeypatch.setattr(cp, "_build_config_commit_offer", lambda *_a, **_kw: None)
    # Keep the XPrompts pane cheap and deterministic.
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    # Keep the Projects pane cheap and deterministic.
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [],
    )
    return view


async def _open_config_pane(page: AcePage) -> ConfigPane:
    modal = ConfigCenterModal(initial_tab="config")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#config")))
    pane = modal.query_one("#config", ConfigPane)
    await page.wait_for(lambda _s: bool(pane._node_by_path))
    return pane


def _binding_action(key: str) -> str | None:
    """Action bound to *key* in ``ConfigPane.BINDINGS`` (tuple or Binding)."""
    for binding in ConfigPane.BINDINGS:
        if isinstance(binding, tuple):
            bind_key, action = binding[0], binding[1]
        else:
            bind_key, action = binding.key, binding.action
        if bind_key == key:
            return action
    return None


async def test_config_pane_loads_and_populates_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        # Sections and leaves are present.
        assert "axe" in pane._node_by_path
        assert "axe.max_hook_runners" in pane._node_by_path
        assert "timezone" in pane._node_by_path
        # A leaf is auto-selected so the detail pane has something to show.
        assert pane._selected_path is not None
        assert pane._view is not None
        # The status placeholder is hidden and the tree is visible.
        assert pane.query_one("#config-tree").display is True
        assert pane.query_one("#config-field-status").display is False


async def test_config_pane_filter_narrows_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("t", "i", "m", "e", "z", "o", "n", "e")
        await page.wait_for(lambda _s: set(pane._node_by_path) == {"timezone"})
        assert "axe.max_hook_runners" not in pane._node_by_path
        # Cancelling restores the full tree.
        pane.cancel_input()
        await page.wait_for(lambda _s: "axe.max_hook_runners" in pane._node_by_path)


async def test_config_pane_filter_updates_title_match_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("t", "i", "m", "e", "z", "o", "n", "e")
        await page.wait_for(lambda _s: set(pane._node_by_path) == {"timezone"})
        assert "matching 1 /" in pane._title_text()


async def test_config_filter_accepts_brackets_and_tab_switches_main_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        pane.action_focus_filter()
        filter_input = pane.query_one("#config-filter-input", Input)
        await page.wait_for(lambda _s: filter_input.has_focus)

        await page.press("left_square_bracket", "right_square_bracket")
        await page.wait_for(lambda _s: filter_input.value == "[]")
        assert modal._active_tab == "config"

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "logs")
        assert filter_input.value == "[]"
        assert page.app.current_tab == "changespecs"


async def test_config_pane_modified_only_toggle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    view = _patch_loaders(monkeypatch)
    modified = view.modified_paths()
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_toggle_modified()
        await page.pause()
        shown_leaves = {
            path for path in pane._node_by_path if view.fields_by_path[path].leaf
        }
        assert shown_leaves == modified
        assert "use_chezmoi" not in shown_leaves  # only built-in default
        # Toggling back restores every leaf.
        pane.action_toggle_modified()
        await page.pause()
        assert "use_chezmoi" in pane._node_by_path


async def test_config_pane_jump_selects_matching_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("chop")
        await page.wait_for(lambda _s: pane._selected_path == "axe.chop_script_dirs")
        assert "axe.chop_script_dirs" in pane._node_by_path


async def test_config_pane_edit_opens_edit_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.modals.config_edit_modal import ConfigEditModal

    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("timezone")
        await page.wait_for(lambda _s: pane._selected_path == "timezone")
        pane.action_edit_field()
        await page.expect_modal("ConfigEditModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigEditModal)
        assert modal._field is not None and modal._field.path == "timezone"


async def test_config_detail_ctrl_d_u_scrolls_without_stealing_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch, _tall_detail_view())
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("long_detail")
        await page.wait_for(lambda _s: pane._selected_path == "long_detail")
        tree = pane.query_one("#config-tree", Tree)
        tree.focus()
        await page.pause()

        scroll = pane.query_one("#config-detail-scroll", VerticalScroll)
        await page.wait_for(lambda _s: scroll.max_scroll_y > 0)
        selected_before = pane._selected_path
        assert page.app.focused is tree
        assert scroll.scroll_y == 0

        await page.press("ctrl+d")
        await page.pause()
        down_y = scroll.scroll_y
        assert down_y > 0
        assert page.app.focused is tree
        assert pane._selected_path == selected_before

        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0
        assert page.app.focused is tree
        assert pane._selected_path == selected_before


async def test_config_detail_ctrl_d_u_on_short_detail_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("use_chezmoi")
        await page.wait_for(lambda _s: pane._selected_path == "use_chezmoi")
        tree = pane.query_one("#config-tree", Tree)
        tree.focus()
        await page.pause()

        scroll = pane.query_one("#config-detail-scroll", VerticalScroll)
        assert scroll.max_scroll_y == 0
        await page.press("ctrl+d")
        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0
        assert page.app.focused is tree


async def test_config_pane_edit_sibling_repos_opens_normal_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.modals.config_edit_modal import ConfigEditModal

    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("sibling_repos")
        await page.wait_for(lambda _s: pane._selected_path == "sibling_repos")
        pane.action_edit_field()
        await page.expect_modal("ConfigEditModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigEditModal)
        assert modal._field is not None and modal._field.path == "sibling_repos"


def test_config_pane_binds_ctrl_d_and_ctrl_u_to_detail_scroll() -> None:
    assert _binding_action("ctrl+d") == "scroll_detail_down"
    assert _binding_action("ctrl+u") == "scroll_detail_up"
    assert _binding_action("g") == "scroll_to_top"
    assert _binding_action("G") == "scroll_to_bottom"
    assert _binding_action("h") == "collapse_tree"
    assert _binding_action("l") == "expand_tree"
    assert "ctrl+d/u: scroll" in ConfigPane(auto_load=False)._hints()
    assert "g/G: top/bottom" in ConfigPane(auto_load=False)._hints()
    assert "g: migrate" not in ConfigPane(auto_load=False)._hints()


def test_config_pane_splits_cycling_j_k_from_clamped_arrow_keys() -> None:
    assert _binding_action("j") == "cycle_cursor_down"
    assert _binding_action("k") == "cycle_cursor_up"
    assert _binding_action("down") == "cursor_down"
    assert _binding_action("up") == "cursor_up"


async def test_config_pane_j_k_wrap_visible_tree_and_arrows_clamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        tree = pane.query_one("#config-tree", Tree)
        tree.focus()

        pane.action_scroll_to_bottom()
        await page.wait_for(lambda _s: tree.cursor_line == tree.last_line)
        last_path = pane._selected_path
        await page.press("j")
        await page.wait_for(lambda _s: tree.cursor_line == 0)
        first_path = pane._selected_path
        assert tree.cursor_node is not None
        assert tree.cursor_node.data == first_path

        await page.press("k")
        await page.wait_for(lambda _s: tree.cursor_line == tree.last_line)
        assert pane._selected_path == last_path
        assert tree.cursor_node is not None
        assert tree.cursor_node.data == last_path

        await page.press("down")
        await page.pause()
        assert tree.cursor_line == tree.last_line
        assert pane._selected_path == last_path

        pane.action_scroll_to_top()
        await page.wait_for(lambda _s: tree.cursor_line == 0)
        assert pane._selected_path == first_path
        await page.press("up")
        await page.pause()
        assert tree.cursor_line == 0
        assert pane._selected_path == first_path


async def test_config_pane_j_k_cycle_single_visible_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("t", "i", "m", "e", "z", "o", "n", "e")
        await page.wait_for(lambda _s: set(pane._node_by_path) == {"timezone"})
        pane.focus_default()
        tree = pane.query_one("#config-tree", Tree)
        await page.wait_for(lambda _s: tree.cursor_line == tree.last_line == 0)

        await page.press("j", "k")
        await page.pause()

        assert tree.cursor_line == 0
        assert tree.cursor_node is not None
        assert tree.cursor_node.data == "timezone"
        assert pane._selected_path == "timezone"


async def test_config_pane_g_and_G_jump_tree_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane.action_scroll_to_bottom()
        await page.wait_for(lambda _s: pane._selected_path == "use_chezmoi")
        pane.action_scroll_to_top()
        await page.wait_for(lambda _s: pane._selected_path == "ace")


async def test_config_pane_h_l_collapse_expand_and_descend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._do_jump("axe.max_hook_runners")
        await page.wait_for(lambda _s: pane._selected_path == "axe.max_hook_runners")

        pane.action_collapse_tree()
        await page.wait_for(lambda _s: pane._selected_path == "axe")
        axe_node = pane._node_by_path["axe"]
        pane.action_collapse_tree()
        await page.pause()
        assert axe_node.is_collapsed

        pane.action_expand_tree()
        await page.pause()
        assert axe_node.is_expanded
        assert pane._selected_path == "axe"

        pane.action_expand_tree()
        await page.wait_for(lambda _s: pane._selected_path == "axe.chop_script_dirs")


async def test_config_pane_successful_write_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        events: list[str] = []
        monkeypatch.setattr(
            page.app, "notify", lambda message, **_kw: events.append(message)
        )
        monkeypatch.setattr(pane, "action_refresh", lambda: events.append("refresh"))

        def discover(*_args: Any, **_kwargs: Any) -> None:
            events.append("discover")
            return None

        monkeypatch.setattr(cp, "_build_config_commit_offer", discover)
        pane._on_edit_dismissed(
            AppliedResult(
                path="/tmp/sase.yml",
                op="set",
                key_path=("timezone",),
                created=False,
                used_chezmoi=True,
            )
        )

        assert events[:2] == [
            "wrote timezone → /tmp/sase.yml (chezmoi applied)",
            "refresh",
        ]
        await page.wait_for(lambda _s: "discover" in events)


def _config_applied(path: str = "/repo/sase.yml") -> AppliedResult:
    return AppliedResult(
        path=path,
        op="set",
        key_path=("timezone",),
        created=False,
        used_chezmoi=True,
    )


def _config_offer() -> ConfigCommitOffer:
    return ConfigCommitOffer(
        git_root="/repo",
        file_path="/repo/home/dot_config/sase/sase.yml",
        rel_path="home/dot_config/sase/sase.yml",
        message="chore: Update config timezone\n\nSASE_TYPE=config",
    )


async def test_config_pane_dirty_source_uses_canonical_commit_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    offer = _config_offer()
    monkeypatch.setattr(cp, "_build_config_commit_offer", lambda *_a, **_kw: offer)

    async with AcePage() as page:
        pane = await _open_config_pane(page)
        pane._on_edit_dismissed(_config_applied(offer.file_path))
        await page.expect_modal("ConfirmActionModal")

        modal = page.app.screen
        assert isinstance(modal, ConfirmActionModal)
        assert modal._title == "Commit & Push"
        assert modal._message == "Commit and push your config field change?"
        assert modal._subject == offer.rel_path
        assert modal._icon == "↑"
        assert modal._confirm_label == "Commit & push"
        assert modal._cancel_label == "Skip"
        assert modal._default == "confirm"


async def test_config_pane_declining_or_dismissing_commit_submits_no_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    offer = _config_offer()
    monkeypatch.setattr(cp, "_build_config_commit_offer", lambda *_a, **_kw: offer)

    async with AcePage() as page:
        pane = await _open_config_pane(page)
        submit = MagicMock()
        monkeypatch.setattr(page.app, "_submit_tracked_task", submit)

        for key in ("n", "escape"):
            pane._on_edit_dismissed(_config_applied(offer.file_path))
            await page.expect_modal("ConfirmActionModal")
            await page.press(key)
            await page.expect_modal("ConfigCenterModal")

        submit.assert_not_called()


async def test_config_pane_confirm_submits_actual_written_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    offer = _config_offer()
    monkeypatch.setattr(cp, "_build_config_commit_offer", lambda *_a, **_kw: offer)
    run = MagicMock(
        return_value=GitCommitPushResult(True, "Committed and pushed to remote")
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git.run_git_commit_push_sync",
        run,
    )

    async with AcePage() as page:
        pane = await _open_config_pane(page)
        submit = MagicMock()
        monkeypatch.setattr(page.app, "_submit_tracked_task", submit)
        pane._on_edit_dismissed(_config_applied(offer.file_path))
        await page.expect_modal("ConfirmActionModal")
        await page.press("y")
        await page.wait_for(lambda _s: submit.call_count == 1)

        args, kwargs = submit.call_args
        assert args[:3] == ("config-commit", offer.rel_path, offer.git_root)
        assert kwargs["display_name"] == f"commit config {offer.rel_path}"
        assert kwargs["dedup_key"] == (
            f"config-commit:{offer.git_root}:{offer.rel_path}"
        )
        assert kwargs["reload_on_complete"] is False
        assert kwargs["notify_on_complete"] is False

        task_result = args[3]()
        assert task_result.success is True
        run.assert_called_once_with(
            git_root=offer.git_root,
            file_path=offer.file_path,
            commit_message=offer.message,
        )


async def test_config_pane_cancelled_failed_clean_and_non_git_skip_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)

        # Both cancellation and a write/apply failure dismiss the editor with None.
        pane._on_edit_dismissed(None)
        pane._on_edit_dismissed(_config_applied("/tmp/clean-or-non-git.yml"))
        await page.pause()

        assert isinstance(page.app.screen, ConfigCenterModal)


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (
            GitCommitPushResult(True, "Committed and pushed to remote"),
            [("Committed and pushed to remote", "information")],
        ),
        (
            GitCommitPushResult(False, "Push failed: rejected"),
            [("Push failed: rejected", "error")],
        ),
        (
            GitCommitPushResult(
                True,
                "Committed and pushed to remote",
                index_lock_removed=True,
            ),
            [
                ("Committed and pushed to remote", "information"),
                (
                    "Removed a stale git index.lock in repo and retried the commit.",
                    "warning",
                ),
            ],
        ),
    ],
)
async def test_config_pane_commit_task_reports_established_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    result: GitCommitPushResult,
    expected: list[tuple[str, str]],
) -> None:
    _patch_loaders(monkeypatch)
    offer = _config_offer()
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git.run_git_commit_push_sync",
        lambda **_kw: result,
    )

    async with AcePage() as page:
        pane = await _open_config_pane(page)
        submit = MagicMock()
        notifications: list[tuple[str, str]] = []
        monkeypatch.setattr(page.app, "_submit_tracked_task", submit)
        monkeypatch.setattr(
            page.app,
            "notify",
            lambda message, *, severity="information", **_kw: notifications.append(
                (message, severity)
            ),
        )

        pane._submit_commit_task(offer)
        args, kwargs = submit.call_args
        task_result = args[3]()
        kwargs["on_complete"](
            SimpleNamespace(
                success=task_result.success,
                message=task_result.message,
                payload=task_result.payload,
            )
        )

        assert notifications == expected


async def test_config_pane_successful_write_toast_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        messages: list[str] = []
        monkeypatch.setattr(
            page.app, "notify", lambda message, **_kw: messages.append(message)
        )
        monkeypatch.setattr(pane, "action_refresh", lambda: None)
        pane._on_edit_dismissed(
            AppliedResult(
                path="/tmp/sase.yml",
                op="set",
                key_path=("timezone",),
                created=False,
                used_chezmoi=True,
            )
        )
        assert messages == ["wrote timezone → /tmp/sase.yml (chezmoi applied)"]


async def test_config_pane_runner_limit_write_requests_standard_agents_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage() as page:
        pane = await _open_config_pane(page)
        refresh_sources: list[str] = []
        monkeypatch.setattr(page.app, "notify", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(pane, "action_refresh", lambda: None)
        monkeypatch.setattr(
            page.app,
            "request_agents_refresh",
            lambda source: refresh_sources.append(source),
        )

        pane._on_edit_dismissed(
            AppliedResult(
                path="/tmp/sase.yml",
                op="set",
                key_path=("max_running_agents",),
                created=False,
                used_chezmoi=False,
            )
        )

        assert refresh_sources == ["config"]


async def test_config_pane_ctrl_d_and_ctrl_u_scroll_detail_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_loaders(monkeypatch)
    async with AcePage(size=(120, 30)) as page:
        pane = await _open_config_pane(page)
        pane._do_jump("ace.lumberjack")
        await page.wait_for(lambda _s: pane._selected_path == "ace.lumberjack")

        tree = pane.query_one("#config-tree", Tree)
        cursor_before = tree.cursor_node.data if tree.cursor_node is not None else None
        selected_before = pane._selected_path
        scroll = pane.query_one("#config-detail-scroll", VerticalScroll)
        await page.wait_for(lambda _s: scroll.max_scroll_y > 0)
        assert scroll.scroll_y == 0

        half_page = scroll.scrollable_content_region.height // 2
        assert half_page > 0

        await page.press("ctrl+d")
        await page.pause()
        expected_down = min(half_page, scroll.max_scroll_y)
        assert scroll.scroll_y == expected_down
        assert pane._selected_path == selected_before
        assert tree.cursor_node is not None and tree.cursor_node.data == cursor_before

        await page.press("ctrl+u")
        await page.pause()
        assert scroll.scroll_y == 0
        assert pane._selected_path == selected_before
        assert tree.cursor_node is not None and tree.cursor_node.data == cursor_before
