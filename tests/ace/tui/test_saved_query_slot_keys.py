"""Behavioral coverage for the direct ``0``-prefixed saved-query slot keys.

Regression coverage for the ``0<digit>`` slot-loading path restored behind a
prefix so it can't collide with the numbered Artifacts sub-tab keys.
"""

from __future__ import annotations

from sase.ace.testing import AcePage


async def test_zero_then_digit_loads_slot_from_prs_subtab() -> None:
    """``0`` then a populated slot digit loads that slot from the PRs pane."""
    async with AcePage() as page:
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app._saved_queries = {"2": '"slot2"'}

        await page.press("0")
        await page.press("2")
        await page.pause()

        await page.expect_state("query", '"slot2"')
        assert page.app._saved_query_mode_active is False


async def test_zero_then_digit_from_commits_lands_on_prs() -> None:
    """The slot prefix works from a non-PRs Artifacts sub-tab and lands on PRs."""
    async with AcePage() as page:
        await page.expect_state("artifacts_subtab", "stitches")
        page.app._saved_queries = {"3": '"slot3"'}

        await page.press("0")
        await page.press("3")
        await page.pause()

        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("query", '"slot3"')


async def test_zero_then_zero_loads_slot_zero() -> None:
    """``00`` loads slot 0."""
    async with AcePage() as page:
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app._saved_queries = {"0": '"slot0"'}

        await page.press("0")
        await page.press("0")
        await page.pause()

        await page.expect_state("query", '"slot0"')


async def test_zero_then_empty_slot_leaves_query_unchanged() -> None:
    """A digit for an empty slot leaves the current query unchanged."""
    async with AcePage() as page:
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app._saved_queries = {}
        original_query = page.state["query"]

        await page.press("0")
        await page.press("5")
        await page.pause()

        assert page.state["query"] == original_query
        assert page.app._saved_query_mode_active is False


async def test_bare_digit_still_switches_subtab_without_prefix() -> None:
    """Without the ``0`` prefix, digits keep selecting Artifacts sub-tabs."""
    async with AcePage() as page:
        await page.expect_state("artifacts_subtab", "stitches")

        await page.press("3")
        await page.pause()

        await page.expect_state("artifacts_subtab", "beads")
        assert page.app._saved_query_mode_active is False


async def test_zero_then_escape_cancels() -> None:
    """``Esc`` after ``0`` cancels: mode flag cleared, query unchanged."""
    async with AcePage() as page:
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app._saved_queries = {"2": '"slot2"'}
        original_query = page.state["query"]

        await page.press("0")
        await page.press("escape")
        await page.pause()

        assert page.state["query"] == original_query
        assert page.app._saved_query_mode_active is False


async def test_zero_does_not_arm_mode_on_agents_tab() -> None:
    """On the Agents tab, ``0`` never arms saved-query mode.

    Member-jump digit handling owns ``0``-``9`` there instead.
    """
    async with AcePage(initial_tab="agents") as page:
        await page.press("0")
        await page.pause()

        assert page.app._saved_query_mode_active is False
