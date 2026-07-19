"""Tests for saved dismissed-agent group revival jump mode."""

from __future__ import annotations

from textual.widgets import OptionList, Static

from sase.ace.tui.modals.saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalModal,
    SavedAgentGroupRevivalResult,
)
from sase.core.agent_group_archive_wire import SavedAgentGroupPageWire

from .saved_agent_group_revival_modal_test_helpers import (
    _FakeKeyEvent,
    _TestApp,
    _group,
    _option_plain,
    _recent_summary,
    _static_plain,
    _summary,
)


async def test_apostrophe_enters_jump_mode_with_hints_on_enabled_rows_only() -> None:
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=(_summary(0), _summary(1)),
            next_cursor=None,
        )
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("apostrophe")
        await pilot.pause()

        assert modal._entry_jump_mode_active is True
        assert set(modal._entry_jump_option_id_to_hint) == {
            "group:group-00",
            "group:group-01",
            "custom-search",
        }

        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        labels = {option.id: _option_plain(option) for option in option_list.options}
        assert labels["group:group-00"].startswith("[0] ")
        assert labels["custom-search"].startswith("[")
        assert not labels["heading:saved"].startswith("[")
        assert not labels["sep:1"].startswith("[")
        assert not labels["empty:recent"].startswith("[")

        hints = modal.query_one("#saved-agent-group-hints", Static)
        assert "JUMP" in _static_plain(hints)


async def test_jump_hint_moves_to_saved_group_and_refreshes_preview() -> None:
    result: list[SavedAgentGroupRevivalResult | None] = []
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=(_summary(0), _summary(1), _summary(2)),
            next_cursor=None,
        ),
        group_loader=lambda group_id: (
            _group("group-01") if group_id == "group-01" else None
        ),
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=result.append)
        await pilot.pause()
        await pilot.press("apostrophe")
        await pilot.pause()
        await pilot.press(modal._entry_jump_option_id_to_hint["group:group-01"])
        await pilot.pause()

        assert pilot.app.screen is modal
        assert result == []
        assert modal._entry_jump_mode_active is False
        assert modal._current_highlighted_option_id() == "group:group-01"

        preview = modal.query_one("#saved-agent-group-preview", Static)
        assert "worker-one" in _static_plain(preview)


async def test_jump_hint_moves_to_recent_dismissal_row() -> None:
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(_summary(0),), next_cursor=None),
        recent_page=SavedAgentGroupPageWire(
            groups=(_recent_summary(),), next_cursor=None
        ),
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("apostrophe")
        await pilot.pause()
        await pilot.press(modal._entry_jump_option_id_to_hint["recent:recent-00"])
        await pilot.pause()

        assert pilot.app.screen is modal
        assert modal._entry_jump_mode_active is False
        assert modal._current_highlighted_option_id() == "recent:recent-00"


async def test_jump_hint_moves_to_load_more_without_invoking_loader() -> None:
    loaded_cursors: list[int | None] = []

    def load_page(cursor: int | None) -> SavedAgentGroupPageWire:
        loaded_cursors.append(cursor)
        return SavedAgentGroupPageWire(groups=(_summary(20),), next_cursor=None)

    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=tuple(_summary(idx) for idx in range(3)),
            next_cursor=3,
        ),
        page_loader=load_page,
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.press("apostrophe")
        await pilot.pause()
        await pilot.press(modal._entry_jump_option_id_to_hint["load-more"])
        await pilot.pause()

        assert modal._current_highlighted_option_id() == "load-more"
        assert loaded_cursors == []

        preview = modal.query_one("#saved-agent-group-preview", Static)
        assert "Load more saved groups" in _static_plain(preview)

        await pilot.press("enter")
        await pilot.pause()
        assert loaded_cursors == [3]


async def test_jump_hint_moves_to_custom_search_without_dismissing() -> None:
    result: list[SavedAgentGroupRevivalResult | None] = []
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(_summary(0),), next_cursor=None)
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=result.append)
        await pilot.pause()
        await pilot.press("apostrophe")
        await pilot.pause()
        await pilot.press(modal._entry_jump_option_id_to_hint["custom-search"])
        await pilot.pause()

        assert pilot.app.screen is modal
        assert result == []
        assert modal._current_highlighted_option_id() == "custom-search"

        preview = modal.query_one("#saved-agent-group-preview", Static)
        assert "Custom revival search" in _static_plain(preview)

        await pilot.press("enter")
        await pilot.pause()

    assert result == [SavedAgentGroupRevivalResult(action="custom_search")]


async def test_escape_cancels_jump_mode_without_dismissing() -> None:
    result: list[SavedAgentGroupRevivalResult | None] = []
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=(_summary(0), _summary(1)),
            next_cursor=None,
        )
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=result.append)
        await pilot.pause()
        await pilot.press("apostrophe")
        await pilot.pause()
        assert modal._entry_jump_mode_active is True

        await pilot.press("escape")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert result == []
        assert modal._entry_jump_mode_active is False

        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        labels = {option.id: _option_plain(option) for option in option_list.options}
        assert not labels["group:group-00"].startswith("[")


async def test_invalid_jump_key_cancels_and_keeps_highlight() -> None:
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=(_summary(0), _summary(1), _summary(2)),
            next_cursor=None,
        )
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_list.highlighted = modal._row_for_option_id(
            option_list, "group:group-01"
        )
        await pilot.pause()

        await pilot.press("apostrophe")
        await pilot.pause()
        # "z" is a valid hint character but is not allocated for four rows.
        await pilot.press("z")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert modal._entry_jump_mode_active is False
        assert modal._current_highlighted_option_id() == "group:group-01"


async def test_apostrophe_in_jump_mode_without_history_jumps_to_first() -> None:
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=(_summary(0), _summary(1), _summary(2)),
            next_cursor=None,
        )
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_list.highlighted = modal._row_for_option_id(
            option_list, "group:group-02"
        )
        await pilot.pause()

        await pilot.press("apostrophe")
        await pilot.pause()
        assert modal._entry_jump_last_option_id is None

        await pilot.press("apostrophe")
        await pilot.pause()

        assert modal._current_highlighted_option_id() == "group:group-00"


async def test_apostrophe_in_jump_mode_returns_to_previous_row() -> None:
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=(_summary(0), _summary(1), _summary(2)),
            next_cursor=None,
        )
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_list.highlighted = modal._row_for_option_id(
            option_list, "group:group-00"
        )
        await pilot.pause()

        await pilot.press("apostrophe")
        await pilot.pause()
        await pilot.press(modal._entry_jump_option_id_to_hint["group:group-02"])
        await pilot.pause()
        assert modal._current_highlighted_option_id() == "group:group-02"
        assert modal._entry_jump_last_option_id == "group:group-00"

        await pilot.press("apostrophe")
        await pilot.pause()
        await pilot.press("apostrophe")
        await pilot.pause()

        assert modal._current_highlighted_option_id() == "group:group-00"


async def test_uppercase_hint_dispatches_through_on_key_normalization() -> None:
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=tuple(_summary(idx) for idx in range(36)),
            next_cursor=None,
        )
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal.action_jump_to_entry()
        await pilot.pause()

        assert modal._entry_jump_hint_to_option_id["A"] == "custom-search"

        event = _FakeKeyEvent(key="a", character="A")
        modal.on_key(event)  # type: ignore[arg-type]
        await pilot.pause()

        assert event.prevented is True
        assert event.stopped is True
        assert pilot.app.screen is modal
        assert modal._current_highlighted_option_id() == "custom-search"


async def test_jump_then_enter_revives_highlighted_group() -> None:
    result: list[SavedAgentGroupRevivalResult | None] = []
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=(_summary(0), _summary(1), _summary(2)),
            next_cursor=None,
        )
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=result.append)
        await pilot.pause()
        await pilot.press("apostrophe")
        await pilot.pause()
        await pilot.press(modal._entry_jump_option_id_to_hint["group:group-02"])
        await pilot.pause()
        assert modal._current_highlighted_option_id() == "group:group-02"

        await pilot.press("enter")
        await pilot.pause()

    assert result == [
        SavedAgentGroupRevivalResult(
            action="revive_group",
            group_id="group-02",
            location="saved",
        )
    ]
