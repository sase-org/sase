"""Behavioral coverage for the cached saved-PR-query chooser."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.query_history import QueryHistoryStacks
from sase.ace.testing import AcePage
from sase.ace.tui.modals import SavedQueryPickerModal
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


async def _open_picker(
    page: AcePage,
    queries: dict[str, str],
) -> SavedQueryPickerModal:
    await page.press("4")
    await page.expect_state("artifacts_subtab", "prs")
    page.app._saved_queries = dict(queries)
    await page.press("asterisk")
    await page.expect_modal("SavedQueryPickerModal")
    modal = page.app.screen
    assert isinstance(modal, SavedQueryPickerModal)
    return modal


async def test_picker_uses_immutable_cached_snapshot_and_active_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(query='"active"') as page:
        monkeypatch.setattr(
            "sase.ace.saved_queries.load_saved_queries",
            lambda: pytest.fail("picker must not read saved queries from disk"),
        )
        source = {
            "0": 'PROJECT="zero"',
            "9": 'STATUS="Ready" AND "a very long saved query that must truncate without losing Rich spans"',
            "2": '"active"',
            "invalid": '"ignored"',
        }
        modal = await _open_picker(page, source)

        source["1"] = '"mutated after open"'
        assert modal.slots == ("2", "9", "0")
        assert "1" not in modal.queries
        with pytest.raises(TypeError):
            modal.queries["1"] = "nope"  # type: ignore[index]

        option_list = modal.query_one("#saved-query-picker-list", OptionList)
        assert option_list.highlighted == 0
        active = modal._build_option("2")
        assert "active" in active.plain
        long_row = modal._build_option("9")
        assert "…" in long_row.plain
        assert all(span.end <= len(long_row) for span in long_row.spans)


async def test_picker_digit_loads_query_and_preserves_history_semantics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(query='"feature"') as page:
        monkeypatch.setattr(
            "sase.ace.saved_queries.load_saved_queries",
            lambda: pytest.fail("loading a chosen cached slot must not read disk"),
        )
        load_calls = 0
        original_load = page.app._load_changespecs

        def _tracked_load() -> None:
            nonlocal load_calls
            load_calls += 1
            original_load()

        monkeypatch.setattr(page.app, "_load_changespecs", _tracked_load)
        page.app._query_history = QueryHistoryStacks(prev=[], next=[])
        active_query = page.app.canonical_query_string
        await _open_picker(
            page,
            {"2": '"other"', "5": active_query},
        )

        await page.press("2")
        await page.expect_no_modal()
        assert page.app.canonical_query_string == '"other"'
        assert page.app._query_history.prev == [active_query]
        assert load_calls == 1

        before = list(page.app._query_history.prev)
        await _open_picker(page, {"2": '"other"', "5": active_query})
        await page.press("2")
        await page.expect_no_modal()
        assert page.app._query_history.prev == before
        assert load_calls == 2


async def test_picker_navigation_enter_cancel_and_empty_slot_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(query='"feature"') as page:
        modal = await _open_picker(
            page,
            {"1": '"one"', "3": '"three"', "0": '"zero"'},
        )
        warnings: list[tuple[str, str]] = []
        monkeypatch.setattr(
            modal,
            "notify",
            lambda message, *, severity="information", **_kwargs: warnings.append(
                (message, severity)
            ),
        )

        await page.press("2")
        await page.pause()
        assert page.state["modal"] == "SavedQueryPickerModal"
        assert warnings == [("No query saved in slot 2", "warning")]

        await page.press("j", "enter")
        await page.expect_no_modal()
        assert page.app.canonical_query_string == '"three"'

        await _open_picker(page, {"1": '"one"'})
        await page.press("q")
        await page.expect_no_modal()
        assert page.app.canonical_query_string == '"three"'

        await _open_picker(page, {"1": '"one"'})
        await page.press("escape")
        await page.expect_no_modal()
        assert page.app.canonical_query_string == '"three"'


async def test_picker_mouse_selection_and_empty_state() -> None:
    async with AcePage(query='"feature"') as page:
        modal = await _open_picker(page, {"1": '"one"', "2": '"two"'})
        option_list = modal.query_one("#saved-query-picker-list", OptionList)
        await page._pilot.click(option_list, offset=(8, 2))
        await page.expect_no_modal()
        assert page.app.canonical_query_string in {'"one"', '"two"'}

        modal = await _open_picker(page, {})
        assert "No saved PR queries yet" in modal._build_empty_state().plain
        assert "q/Esc close" in modal._build_footer().plain
        await page.press("0")
        await page.pause()
        assert page.state["modal"] == "SavedQueryPickerModal"
        await page.press("q")


async def test_picker_is_pr_only_and_bare_digits_only_switch_artifacts() -> None:
    async with AcePage(query='"feature"') as page:
        page.app._saved_queries = {"2": '"saved"'}

        await page.press("1")
        await page.expect_state("artifacts_subtab", "commits")
        assert page.app.canonical_query_string == '"feature"'

        for subtab_key in ("1", "2", "3", "5"):
            await page.press(subtab_key, "asterisk")
            await page.pause()
            assert page.state["modal"] is None

        await page.press("4", "asterisk")
        await page.expect_modal("SavedQueryPickerModal")


async def test_malformed_cached_query_reports_error_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(query='"feature"') as page:
        notifications: list[tuple[str, str]] = []
        monkeypatch.setattr(
            page.app,
            "notify",
            lambda message, *, severity="information", **_kwargs: notifications.append(
                (message, severity)
            ),
        )
        await _open_picker(page, {"3": "("})

        await page.press("3")
        await page.expect_no_modal()
        assert page.app.canonical_query_string == '"feature"'
        assert notifications
        assert notifications[-1][0].startswith("Error loading query:")
        assert notifications[-1][1] == "error"


async def test_focused_query_input_can_type_artifact_file_digits_and_star() -> None:
    async with AcePage(query='"feature"') as page:
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.press("slash")
        await page.expect_modal("QueryEditModal")
        query_input = page.app.screen.query_one(
            "#query-input",
            SingleLineVimTextArea,
        )

        await page.press("1", "asterisk")
        await page.pause()
        assert query_input.text.endswith("1*")
        assert page.app.current_artifacts_subtab == "prs"
