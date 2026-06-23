"""Tests for saved dismissed-agent group revival modal behavior."""

from __future__ import annotations

from typing import cast

from textual.widgets import OptionList, Static

from sase.ace.tui.modals.confirm_action_modal import ConfirmActionModal
from sase.ace.tui.modals.saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalModal,
    SavedAgentGroupRevivalResult,
)
from sase.core.agent_group_archive_wire import SavedAgentGroupPageWire

from .saved_agent_group_revival_modal_test_helpers import (
    _TestApp,
    _group,
    _option_plain,
    _recent_summary,
    _static_plain,
    _summary,
)


def test_initial_page_includes_load_more_before_custom_search() -> None:
    page = SavedAgentGroupPageWire(
        groups=tuple(_summary(idx) for idx in range(20)),
        next_cursor=20,
    )
    modal = SavedAgentGroupRevivalModal(page)

    option_ids = [option.id for option in modal._create_options()]

    assert option_ids[:5] == [
        "heading:saved",
        "group:group-00",
        "group:group-01",
        "group:group-02",
        "group:group-03",
    ]
    assert option_ids[21:] == [
        "load-more",
        "sep:1",
        "heading:recent",
        "empty:recent",
        "sep:2",
        "custom-search",
    ]
    assert len(option_ids) == 27


def test_empty_state_still_keeps_custom_search_final() -> None:
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(), next_cursor=None)
    )

    option_ids = [option.id for option in modal._create_options()]

    assert option_ids == [
        "heading:saved",
        "empty:saved",
        "sep:1",
        "heading:recent",
        "empty:recent",
        "sep:2",
        "custom-search",
    ]
    assert "0 saved loaded | 0 recent" in modal._hints_text()


async def test_load_more_appends_next_page_and_keeps_custom_final() -> None:
    def load_page(cursor: int | None) -> SavedAgentGroupPageWire:
        assert cursor == 20
        return SavedAgentGroupPageWire(groups=(_summary(20),), next_cursor=None)

    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=tuple(_summary(idx) for idx in range(20)),
            next_cursor=20,
        ),
        page_loader=load_page,
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_load_more()
        await pilot.pause()

        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_ids = [option.id for option in option_list.options]
        assert len(modal.groups) == 21
        assert "group:group-20" in option_ids
        assert option_ids[-1] == "custom-search"
        assert modal.next_cursor is None


async def test_preview_loads_full_group_details_for_highlighted_group() -> None:
    group = _group("group-00")
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(_summary(0),), next_cursor=None),
        group_loader=lambda group_id: group if group_id == "group-00" else None,
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        preview = modal.query_one("#saved-agent-group-preview", Static)
        plain = _static_plain(preview)
        assert "Included agents" in plain
        assert "worker-one" in plain


async def test_enter_on_custom_search_returns_custom_result() -> None:
    result: SavedAgentGroupRevivalResult | None = None
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(), next_cursor=None)
    )

    def on_dismiss(value: SavedAgentGroupRevivalResult | None) -> None:
        nonlocal result
        result = value

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_list.highlighted = 6
        await pilot.press("enter")
        await pilot.pause()

    assert result == SavedAgentGroupRevivalResult(action="custom_search")


async def test_enter_on_recent_group_returns_recent_location() -> None:
    result: SavedAgentGroupRevivalResult | None = None
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(), next_cursor=None),
        recent_page=SavedAgentGroupPageWire(
            groups=(_recent_summary(),), next_cursor=None
        ),
    )

    def on_dismiss(value: SavedAgentGroupRevivalResult | None) -> None:
        nonlocal result
        result = value

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_list.highlighted = 4
        await pilot.press("enter")
        await pilot.pause()

    assert result == SavedAgentGroupRevivalResult(
        action="revive_group",
        group_id="recent-00",
        location="recent",
    )


async def test_ctrl_d_on_saved_group_confirms_deletes_and_keeps_modal_open() -> None:
    deleted_group_ids: list[str] = []
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(
            groups=(_summary(0, name="Backend batch"), _summary(1)),
            next_cursor=None,
        ),
        delete_callback=lambda group_id: deleted_group_ids.append(group_id) is None,
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ConfirmActionModal)
        confirm = cast(ConfirmActionModal, pilot.app.screen)
        assert confirm._title == "Delete Saved Agent Group"
        assert "Backend batch" in confirm._message
        assert "dismissed agents themselves are not deleted" in confirm._message
        assert "cannot be undone" in confirm._message

        await pilot.press("y")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert deleted_group_ids == ["group-00"]
        assert [group.group_id for group in modal.groups] == ["group-01"]
        assert modal._current_highlighted_option_id() == "group:group-01"

        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_ids = [option.id for option in option_list.options]
        assert "group:group-00" not in option_ids
        assert _option_plain(option_list.options[0]) == "Saved groups (1)"

        hints = modal.query_one("#saved-agent-group-hints", Static)
        assert "^d: delete" in _static_plain(hints)


async def test_ctrl_d_delete_cancel_keeps_saved_group() -> None:
    deleted_group_ids: list[str] = []
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(_summary(0),), next_cursor=None),
        delete_callback=lambda group_id: deleted_group_ids.append(group_id) is None,
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert deleted_group_ids == []
        assert [group.group_id for group in modal.groups] == ["group-00"]
        assert modal._current_highlighted_option_id() == "group:group-00"


async def test_ctrl_d_is_noop_on_recent_and_sentinel_rows() -> None:
    deleted_group_ids: list[str] = []
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(_summary(0),), next_cursor=None),
        recent_page=SavedAgentGroupPageWire(
            groups=(_recent_summary(),), next_cursor=None
        ),
        delete_callback=lambda group_id: deleted_group_ids.append(group_id) is None,
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        for option_id in ("recent:recent-00", "heading:saved", "custom-search"):
            option_list.highlighted = modal._row_for_option_id(option_list, option_id)
            await pilot.pause()

            await pilot.press("ctrl+d")
            await pilot.pause()

            assert pilot.app.screen is modal
            assert deleted_group_ids == []


async def test_delete_last_saved_group_falls_back_to_recent_and_updates_count() -> None:
    deleted_group_ids: list[str] = []
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(_summary(0),), next_cursor=None),
        recent_page=SavedAgentGroupPageWire(
            groups=(_recent_summary(),), next_cursor=None
        ),
        delete_callback=lambda group_id: deleted_group_ids.append(group_id) is None,
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert deleted_group_ids == ["group-00"]
        assert modal.groups == ()
        assert modal._current_highlighted_option_id() == "recent:recent-00"

        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        assert _option_plain(option_list.options[0]) == "Saved groups (0)"

        hints = modal.query_one("#saved-agent-group-hints", Static)
        assert "0 saved loaded | 1 recent" in _static_plain(hints)
        assert "^d: delete" not in _static_plain(hints)


async def test_delete_last_saved_group_falls_back_to_custom_search() -> None:
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(_summary(0),), next_cursor=None),
        delete_callback=lambda _group_id: True,
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("ctrl+d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert modal.groups == ()
        assert modal._current_highlighted_option_id() == "custom-search"


async def test_delete_hint_is_shown_only_for_saved_group_rows() -> None:
    modal = SavedAgentGroupRevivalModal(
        SavedAgentGroupPageWire(groups=(_summary(0),), next_cursor=None),
        recent_page=SavedAgentGroupPageWire(
            groups=(_recent_summary(),), next_cursor=None
        ),
    )

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        hints = modal.query_one("#saved-agent-group-hints", Static)
        assert "^d: delete" in _static_plain(hints)

        option_list = modal.query_one("#saved-agent-group-list", OptionList)
        option_list.highlighted = modal._row_for_option_id(
            option_list,
            "recent:recent-00",
        )
        await pilot.pause()

        assert "^d: delete" not in _static_plain(hints)
