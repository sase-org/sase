"""Patch query persistence must stay inert while hidden Artifacts panes are active."""

from __future__ import annotations

from sase.ace.query_history import QueryHistoryStacks
from sase.ace.query_record import QueryRecord
from sase.ace.testing import AcePage


async def test_beads_pane_saved_and_history_keys_do_not_touch_patch_query() -> None:
    async with AcePage(query='"feature"', initial_tab="patches") as page:
        await page.press(page.artifacts_digit("beads"))
        await page.expect_state("artifacts_subtab", "beads")

        page.app._saved_queries = {
            "patches": {"2": QueryRecord(source='"slot2"', canonical='"slot2"')}
        }
        page.app._query_history = {
            "patches": QueryHistoryStacks(
                prev=[QueryRecord(source='"prev"', canonical='"prev"')],
                next=[QueryRecord(source='"next"', canonical='"next"')],
            )
        }
        page.app._query_selections = {
            "patches": {'"feature"': "patches:sase:feature_a"}
        }
        original_query = page.app.query_string
        original_history = page.app._query_history["patches"]
        original_selections = dict(page.app._query_selections["patches"])

        await page.press("0")
        await page.press("2")
        await page.press("circumflex_accent")
        await page.press("underscore")
        await page.press("asterisk")
        await page.pause()

        await page.expect_state("artifacts_subtab", "beads")
        await page.expect_modal("SavedQueryPickerModal")
        await page.press("q")
        await page.expect_no_modal()
        assert page.app.query_string == original_query
        assert page.app._query_history["patches"] == original_history
        assert page.app._query_selections["patches"] == original_selections
