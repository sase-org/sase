"""Behavioral coverage for the direct ``0``-prefixed saved-query slot keys.

Regression coverage for the ``0<digit>`` slot-loading path restored behind a
prefix so it can't collide with the numbered Artifacts sub-tab keys.
"""

from __future__ import annotations

from sase.ace.query_record import QueryRecord
from sase.ace.testing import AcePage


def _saved(canonical: str) -> dict[str, dict[str, QueryRecord]]:
    return {"patches": {"2": QueryRecord(source=canonical, canonical=canonical)}}


async def test_zero_then_digit_loads_slot_from_prs_subtab() -> None:
    """``0`` then a populated slot digit loads that slot from the PRs pane."""
    async with AcePage() as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app._saved_queries = {
            "patches": {"2": QueryRecord(source='"slot2"', canonical='"slot2"')}
        }

        await page.press("0")
        await page.press("2")
        await page.pause()

        await page.expect_state("query", '"slot2"')
        assert page.app._saved_query_mode_active is False


async def test_zero_then_digit_from_commits_stays_on_commits_pane() -> None:
    """Saved-query slots are namespaced per pane: no cross-pane borrowing.

    Pressing the slot prefix from a non-PRs Artifacts sub-tab no longer
    hard-switches to PRs; it looks up the active pane's own (currently
    empty) namespace and reports nothing saved there.
    """
    async with AcePage() as page:
        await page.expect_state("artifacts_subtab", "stitches")
        page.app._saved_queries = {
            "patches": {"3": QueryRecord(source='"slot3"', canonical='"slot3"')}
        }
        original_query = page.state["query"]

        await page.press("0")
        await page.press("3")
        await page.pause()

        await page.expect_state("artifacts_subtab", "stitches")
        assert page.state["query"] == original_query


async def test_zero_then_zero_loads_slot_zero() -> None:
    """``00`` loads slot 0."""
    async with AcePage() as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app._saved_queries = {
            "patches": {"0": QueryRecord(source='"slot0"', canonical='"slot0"')}
        }

        await page.press("0")
        await page.press("0")
        await page.pause()

        await page.expect_state("query", '"slot0"')


async def test_zero_then_empty_slot_leaves_query_unchanged() -> None:
    """A digit for an empty slot leaves the current query unchanged."""
    async with AcePage() as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app._saved_queries = {"patches": {}}
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

        await page.press(page.artifacts_digit("beads"))
        await page.pause()

        await page.expect_state("artifacts_subtab", "beads")
        assert page.app._saved_query_mode_active is False


async def test_zero_then_escape_cancels() -> None:
    """``Esc`` after ``0`` cancels: mode flag cleared, query unchanged."""
    async with AcePage() as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app._saved_queries = _saved('"slot2"')
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


async def test_stale_profile_digest_reports_error_without_applying_slot() -> None:
    """A slot saved under a stale profile digest is a visible, editable error.

    It is never silently reinterpreted or auto-applied.
    """
    async with AcePage() as page:
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app._saved_queries = {
            "patches": {
                "2": QueryRecord(
                    source='"slot2"',
                    canonical='"slot2"',
                    profile_digest="not-the-current-digest",
                )
            }
        }
        original_query = page.state["query"]
        notifications: list[tuple[str, str]] = []
        page.app.notify = lambda message, *, severity="information", **_kwargs: (
            notifications.append((message, severity))
        )

        await page.press("0")
        await page.press("2")
        await page.pause()

        assert page.state["query"] == original_query
        assert notifications
        assert notifications[-1][1] == "error"
        assert "slot2" in notifications[-1][0]
