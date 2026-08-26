"""Behavioral coverage for the cached saved-PR-query chooser."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.query_history import QueryHistoryStacks
from sase.ace.query_record import QueryRecord, current_profile_digest
from sase.ace.testing import AcePage
from sase.ace.tui.modals import SavedQueryPickerModal
from sase.ace.tui.widgets.artifacts.patch_filter_bar import PatchFilterBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


async def _open_picker(
    page: AcePage,
    queries: dict[str, str],
) -> SavedQueryPickerModal:
    await page.press(page.artifacts_digit("patches"))
    await page.expect_state("artifacts_subtab", "patches")
    page.app._saved_queries = {
        "patches": {
            slot: QueryRecord(source=value, canonical=value)
            for slot, value in queries.items()
        }
    }
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
        original_load = page.app._load_patches

        def _tracked_load() -> None:
            nonlocal load_calls
            load_calls += 1
            original_load()

        monkeypatch.setattr(page.app, "_load_patches", _tracked_load)
        page.app._query_history = {"patches": QueryHistoryStacks(prev=[], next=[])}
        active_query = page.app.canonical_query_string
        active_record = QueryRecord(
            source=active_query,
            canonical=active_query,
            profile_digest=current_profile_digest("patches"),
        )
        await _open_picker(
            page,
            {"2": '"other"', "5": active_query},
        )

        await page.press("2")
        await page.expect_no_modal()
        assert page.app.canonical_query_string == '"other"'
        assert page.app._query_history["patches"].prev == [active_record]
        assert load_calls == 1

        before = list(page.app._query_history["patches"].prev)
        await _open_picker(page, {"2": '"other"', "5": active_query})
        await page.press("2")
        await page.expect_no_modal()
        assert page.app._query_history["patches"].prev == before
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


async def test_picker_follows_active_query_pane_and_digits_switch_artifacts() -> None:
    async with AcePage(query='"feature"') as page:
        page.app._saved_queries = {
            "patches": {"2": QueryRecord(source='"saved"', canonical='"saved"')},
            "stitches": {},
            "beads": {},
            "files": {},
        }

        await page.press(page.artifacts_digit("stitches"))
        await page.expect_state("artifacts_subtab", "stitches")
        assert page.app.canonical_query_string == '"feature" limit:100'

        for subtab in ("stitches", "beads", "files"):
            await page.press(page.artifacts_digit(subtab), "asterisk")
            await page.pause()
            await page.expect_modal("SavedQueryPickerModal")
            await page.press("q")
            await page.expect_no_modal()

        await page.press(page.artifacts_digit("patches"), "asterisk")
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
        assert page.app.canonical_query_string == '"feature" limit:100'
        assert notifications
        assert notifications[-1][0].startswith("Error loading query:")
        assert notifications[-1][1] == "error"


async def test_focused_patch_filter_bar_can_type_artifact_file_digits_and_star() -> (
    None
):
    async with AcePage(query='"feature"') as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.press("slash")
        bar = page.query_one_widget("#patch-filter-bar", PatchFilterBar)
        await page.wait_for(lambda _state: bar._editing)  # type: ignore[attr-defined]
        query_input = bar.query_one(
            "#patch-filter-input",
            SingleLineVimTextArea,
        )

        await page.press("1", "asterisk")
        await page.pause()
        assert query_input.text.endswith("1*")
        assert page.app.current_artifacts_subtab == "patches"
