"""Tests for Launch Control (Models panel) apostrophe entry-jump navigation."""

from textual.widgets import OptionList, Static

from sase.ace.tui.modals.models_panel import ModelsPanel
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_alias_view,
    make_bucketed_views,
    make_worker_bucket_views,
    patch_alias_views,
)


def _highlighted_id(option_list: OptionList) -> str | None:
    highlighted = option_list.highlighted
    if highlighted is None:
        return None
    option = option_list.get_option_at_index(highlighted)
    return str(option.id) if option.id is not None else None


def _many_custom_aliases(count: int) -> list:
    return [
        make_alias_view(
            f"custom_{index:03d}",
            "user",
            configured=True,
            configured_source="custom",
        )
        for index in range(count)
    ]


async def _mounted_panel(monkeypatch, pilot, views) -> ModelsPanel:
    patch_alias_views(monkeypatch, views)
    panel = ModelsPanel()
    pilot.app.push_screen(panel)
    await pilot.pause()
    await pilot.pause()
    return panel


async def test_top_level_jump_hints_follow_visual_order_and_skip_furniture(
    monkeypatch,
) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_bucketed_views())

        panel.action_jump_to_entry()
        assert panel.jump_mode_active is True

        target_ids = panel._jump_target_keys()
        assert target_ids[:2] == ["launch:default_model", "launch:epic_lander_model"]
        assert "setting:default_effort" in target_ids
        assert "setting:runner_limit" in target_ids
        assert "bucket:research" in target_ids
        assert "plain" in target_ids
        assert not any(
            row_id.startswith("__models-section__:") for row_id in target_ids
        )
        assert not any(row_id.startswith("__models-spacer__:") for row_id in target_ids)
        assert not any(row_id.startswith("__models-hint__:") for row_id in target_ids)

        hints = panel.jump_hints_by_key()
        option_list = panel.query_one("#models-panel-list", OptionList)
        for row_id in target_ids:
            option = option_list.get_option_at_index(
                option_list.get_option_index(row_id)
            )
            assert str(option.prompt).startswith(f"[{hints[row_id]}]")


async def test_disabled_furniture_gets_blank_gutter_not_a_hint(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_bucketed_views())

        panel.action_jump_to_entry()
        option_list = panel.query_one("#models-panel-list", OptionList)

        header_index = option_list.get_option_index("__models-section__:launch")
        header = option_list.get_option_at_index(header_index)
        assert str(header.prompt)[0] == " "
        assert "[" not in str(header.prompt).split("──", 1)[0]


async def test_bucket_jump_hints_scope_to_members(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_bucketed_views())
        option_list = panel.query_one("#models-panel-list", OptionList)
        panel._set_highlighted_index(
            option_list, option_list.get_option_index("bucket:research")
        )
        panel.action_enter_bucket()
        await pilot.pause()

        panel.action_jump_to_entry()
        target_ids = set(panel._jump_target_keys())

        assert target_ids == {"research_a", "research_b"}


async def test_jump_selects_without_activating_bucket(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_bucketed_views())

        panel.action_jump_to_entry()
        hint = panel.jump_hints_by_key()["bucket:research"]
        handled = panel.handle_jump_key(hint)
        await pilot.pause()

        assert handled is True
        assert panel._active_bucket is None
        assert pilot.app.screen is panel
        option_list = panel.query_one("#models-panel-list", OptionList)
        assert _highlighted_id(option_list) == "bucket:research"
        assert panel.jump_mode_active is False


async def test_jump_selects_without_activating_setting_row(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_worker_bucket_views())

        panel.action_jump_to_entry()
        hint = panel.jump_hints_by_key()["setting:default_effort"]
        handled = panel.handle_jump_key(hint)
        await pilot.pause()

        assert handled is True
        assert pilot.app.screen is panel
        option_list = panel.query_one("#models-panel-list", OptionList)
        assert _highlighted_id(option_list) == "setting:default_effort"
        description = panel.query_one("#models-panel-description", Static).content.plain
        assert "reasoning effort" in description


async def test_apostrophe_without_history_moves_to_first(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_worker_bucket_views())
        option_list = panel.query_one("#models-panel-list", OptionList)
        target_ids = panel._jump_target_keys()
        panel._set_highlighted_index(
            option_list, option_list.get_option_index(target_ids[-1])
        )
        panel._update_context()

        panel.action_jump_to_entry()
        handled = panel.handle_jump_key("apostrophe")

        assert handled is True
        assert _highlighted_id(option_list) == target_ids[0]
        assert panel.jump_mode_active is False


async def test_apostrophe_back_returns_to_origin(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_worker_bucket_views())
        option_list = panel.query_one("#models-panel-list", OptionList)
        target_ids = panel._jump_target_keys()
        origin = target_ids[2]
        panel._set_highlighted_index(option_list, option_list.get_option_index(origin))
        panel._update_context()

        panel.action_jump_to_entry()
        destination_hint = panel.jump_hints_by_key()[target_ids[-1]]
        assert panel.handle_jump_key(destination_hint) is True
        assert _highlighted_id(option_list) == target_ids[-1]

        panel.action_jump_to_entry()
        assert panel.jump_back_stack
        handled = panel.handle_jump_key("apostrophe")

        assert handled is True
        assert _highlighted_id(option_list) == origin
        assert panel.jump_back_stack == []


async def test_escape_cancels_without_moving_or_closing(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_worker_bucket_views())
        option_list = panel.query_one("#models-panel-list", OptionList)
        panel._set_highlighted_index(
            option_list, option_list.get_option_index("setting:runner_limit")
        )
        panel._update_context()

        panel.action_jump_to_entry()
        handled = panel.handle_jump_key("escape")

        assert handled is True
        assert panel.jump_mode_active is False
        assert pilot.app.screen is panel
        assert _highlighted_id(option_list) == "setting:runner_limit"


async def test_invalid_hint_cancels_without_moving(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_worker_bucket_views())
        option_list = panel.query_one("#models-panel-list", OptionList)
        panel._set_highlighted_index(
            option_list, option_list.get_option_index("setting:runner_limit")
        )
        panel._update_context()

        panel.action_jump_to_entry()
        # "!" is never part of the adaptive alphabet, so it can never prefix a
        # real hint.
        handled = panel.handle_jump_key("!")

        assert handled is True
        assert panel.jump_mode_active is False
        assert _highlighted_id(option_list) == "setting:runner_limit"


async def test_uppercase_hint_dispatches_exact_target(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, _many_custom_aliases(40))

        panel.action_jump_to_entry()
        target_ids = panel._jump_target_keys()
        hints = panel.jump_hints_by_key()
        uppercase_target = next(
            row_id
            for row_id in target_ids
            if hints[row_id].isalpha() and hints[row_id].isupper()
        )
        handled = panel.handle_jump_key(hints[uppercase_target])

        assert handled is True
        option_list = panel.query_one("#models-panel-list", OptionList)
        assert _highlighted_id(option_list) == uppercase_target
        assert panel.jump_mode_active is False


async def test_two_character_hint_pending_prefix(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, _many_custom_aliases(70))

        panel.action_jump_to_entry()
        target_ids = panel._jump_target_keys()
        hints = panel.jump_hints_by_key()
        assert all(len(hint) == 2 for hint in hints.values())
        last_target = target_ids[-1]
        hint = hints[last_target]

        assert panel.handle_jump_key(hint[0]) is True
        assert panel.jump_mode_active is True
        assert panel._jump_state().pending_prefix == hint[0]

        assert panel.handle_jump_key(hint[1]) is True
        assert panel.jump_mode_active is False
        assert panel._jump_state().pending_prefix == ""
        option_list = panel.query_one("#models-panel-list", OptionList)
        assert _highlighted_id(option_list) == last_target


async def test_footer_advertises_jump_in_normal_mode(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_worker_bucket_views())
        footer = str(panel.query_one("#models-panel-footer", Static).content)
        assert "'" in footer
        assert "Jump" in footer


async def test_footer_switches_to_jump_status_first(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_worker_bucket_views())
        panel.action_jump_to_entry()
        footer = str(panel.query_one("#models-panel-footer", Static).content)
        assert footer == "JUMP ' first  <esc> cancel"


async def test_footer_switches_to_jump_status_back(monkeypatch) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_worker_bucket_views())
        panel._jump_state().back_stack.append(0)
        panel.action_jump_to_entry()
        footer = str(panel.query_one("#models-panel-footer", Static).content)
        assert footer == "JUMP ' back  <esc> cancel"


async def test_value_only_refresh_retains_jump_state(monkeypatch) -> None:
    """A countdown-only repaint (unchanged row ids) must not disturb jump mode."""
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_worker_bucket_views())

        panel.action_jump_to_entry()
        assert panel.jump_mode_active is True
        hints_before = panel.jump_hints_by_key()
        back_stack_before = panel.jump_back_stack

        # ``_refresh_effort_clock`` rebuilds the rows to update the countdown
        # text but leaves the row-id set untouched.
        panel._refresh_effort_clock()

        assert panel.jump_mode_active is True
        assert panel.jump_hints_by_key() == hints_before
        assert panel.jump_back_stack == back_stack_before


async def test_two_character_prefix_does_not_survive_identity_change(
    monkeypatch,
) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, _many_custom_aliases(70))

        panel.action_jump_to_entry()
        target_ids = panel._jump_target_keys()
        hints = panel.jump_hints_by_key()
        hint = hints[target_ids[-1]]
        assert len(hint) == 2
        assert panel.handle_jump_key(hint[0]) is True
        assert panel._jump_state().pending_prefix == hint[0]

        # Simulate the row set changing under an open two-character prefix --
        # an async reload or an alias addition/removal/reorder.
        new_views = _many_custom_aliases(71)
        panel._views = new_views
        panel._top_rows = panel._load_models_panel_rows(new_views)
        panel._replace_display()

        assert panel.jump_mode_active is False
        assert panel._jump_state().pending_prefix == ""
        assert panel.jump_hints_by_key() == {}


async def test_bucket_entry_invalidates_jump_state_mid_prefix(monkeypatch) -> None:
    """Drilling into a bucket replaces the identity set and must drop hints."""
    async with ModelsPanelTestApp().run_test() as pilot:
        panel = await _mounted_panel(monkeypatch, pilot, make_bucketed_views())
        option_list = panel.query_one("#models-panel-list", OptionList)
        panel._set_highlighted_index(
            option_list, option_list.get_option_index("bucket:research")
        )
        panel._update_context()

        panel.action_jump_to_entry()
        assert panel.jump_mode_active is True

        panel.action_enter_bucket()

        assert panel.jump_mode_active is False
        assert panel._jump_state().pending_prefix == ""
        assert panel.jump_hints_by_key() == {}
        assert panel._active_bucket == "research"


async def test_initial_async_alias_load_does_not_manufacture_history(
    monkeypatch,
) -> None:
    """First composition must record identity without inventing back-stack entries."""
    async with ModelsPanelTestApp().run_test() as pilot:
        patch_alias_views(monkeypatch, make_worker_bucket_views())
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.pause()

        assert panel.jump_back_stack == []
        assert panel.jump_mode_active is False
