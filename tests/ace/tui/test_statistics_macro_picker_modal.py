"""Filter and selection coverage for the Statistics macro focus picker."""

from __future__ import annotations

from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals.statistics_macro_picker_modal import (
    StatisticsMacroPickerModal,
    MacroFocusChoice,
)
from sase.stats.ranges import resolve_preset
from sase.stats.views import build_statistics_views

from tests.ace.tui._statistics_pane_helpers import (
    _activity_payload,
    _result,
    _run_payload,
)


async def test_picker_filters_cached_rows_highlights_focus_and_selects() -> None:
    result = _result("macros", resolve_preset("7d"))
    choices: list[MacroFocusChoice | None] = []

    async with AcePage() as page:
        modal = StatisticsMacroPickerModal(
            result.views.macros.rows,
            current_focus="gh",
        )
        page.app.push_screen(modal, choices.append)
        await page.expect_modal("StatisticsMacroPickerModal")
        await page.wait_for(
            lambda _state: bool(modal.query("#statistics-macro-picker-list"))
        )

        option_list = modal.query_one("#statistics-macro-picker-list", OptionList)
        assert option_list.highlighted == 2

        await page.press("s", "p", "l", "i", "t")
        assert [row.name for row in modal._filtered_rows] == ["split_file"]
        assert option_list.highlighted == 0

        await page.press("down", "enter")
        await page.wait_for(lambda _state: bool(choices))

    assert choices == [MacroFocusChoice("split_file")]


async def test_picker_cancel_is_distinct_from_all_macros() -> None:
    result = _result("macros", resolve_preset("7d"))
    choices: list[MacroFocusChoice | None] = []

    async with AcePage() as page:
        page.app.push_screen(
            StatisticsMacroPickerModal(result.views.macros.rows),
            choices.append,
        )
        await page.expect_modal("StatisticsMacroPickerModal")
        await page.wait_for(
            lambda _state: bool(page.app.screen.query("#statistics-macro-picker-list"))
        )
        await page.press("q")
        await page.wait_for(lambda _state: bool(choices))

    assert choices == [None]


def test_picker_rows_share_the_statistics_kind_labels() -> None:
    selected_range = resolve_preset("7d")
    payload = _run_payload(selected_range, "tribe")
    payload["macros"]["rows"][0].update(
        {"name": "research_swarm", "kind": "swarm", "tags": []}
    )
    rows = build_statistics_views(payload, _activity_payload()).macros.rows

    labels = [StatisticsMacroPickerModal._row_label(row).plain for row in rows]

    assert any(label.startswith("#research_swarm") for label in labels)
    swarm_label = next(label for label in labels if label.startswith("#research_swarm"))
    assert "swarm" in swarm_label
