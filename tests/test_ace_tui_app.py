"""Tests for the ace TUI app initialization, navigation, and modals."""

from sase.ace.testing import AcePage, make_changespec
from textual.widgets import Input


# --- Navigation Tests ---


async def test_navigation_next_key() -> None:
    """Test 'j' key navigates to next changespec."""
    async with AcePage() as page:
        assert page.state["idx"] == 0

        await page.press("j")
        assert page.state["idx"] == 1

        await page.press("j")
        assert page.state["idx"] == 2


async def test_navigation_next_at_end() -> None:
    """Test 'j' key at last item cycles to first item."""
    changespecs = [
        make_changespec(name="feature_a"),
        make_changespec(name="feature_b"),
    ]
    async with AcePage(changespecs=changespecs) as page:
        await page.press("j")
        assert page.state["idx"] == 1

        # Press 'j' at end should cycle to first item
        await page.press("j")
        assert page.state["idx"] == 0


async def test_navigation_prev_at_start() -> None:
    """Test 'k' key at first item cycles to last item."""
    changespecs = [
        make_changespec(name="feature_a"),
        make_changespec(name="feature_b"),
    ]
    async with AcePage(changespecs=changespecs) as page:
        assert page.state["idx"] == 0

        # Press 'k' at start should cycle to last item
        await page.press("k")
        assert page.state["idx"] == 1


# --- Query Edit Modal Tests ---


async def test_query_edit_modal_cancel() -> None:
    """Test pressing Escape cancels query edit modal."""
    changespecs = [make_changespec()]
    async with AcePage(query='"original"', changespecs=changespecs) as page:
        original_query = page.state["query"]

        # Open modal
        await page.press("slash")
        await page.expect_modal("QueryEditModal")

        # Press Escape to cancel
        await page.press("escape")

        # Modal should be closed and query unchanged
        await page.expect_no_modal()
        assert page.state["query"] == original_query


async def test_query_edit_modal_apply() -> None:
    """Test applying a new query updates query_string."""
    changespecs = [
        make_changespec(name="feature_a"),
        make_changespec(name="other_b"),
    ]
    async with AcePage(query='"feature"', changespecs=changespecs) as page:
        assert page.state["query"] == '"feature"'

        # Open modal
        await page.press("slash")
        await page.expect_modal("QueryEditModal")

        # Get the input widget and set new query value
        modal = page.app.screen_stack[-1]
        input_widget = modal.query_one("#query-input", Input)
        input_widget.value = '"other"'

        # Click Apply button
        await page.click("#apply")

        # Query should be updated
        assert page.state["query"] == '"other"'


async def test_query_edit_modal_invalid_query() -> None:
    """Test invalid query shows error notification."""
    changespecs = [make_changespec()]
    async with AcePage(query='"valid"', changespecs=changespecs) as page:
        original_query = page.state["query"]

        # Open modal
        await page.press("slash")
        await page.expect_modal("QueryEditModal")

        # Set invalid query (unclosed quote)
        modal = page.app.screen_stack[-1]
        input_widget = modal.query_one("#query-input", Input)
        input_widget.value = '"unclosed'

        # Click Apply
        await page.click("#apply")

        # Query should remain unchanged
        assert page.state["query"] == original_query


# --- Marking Auto-Navigation Tests ---


async def test_unmark_navigates_to_next_spec() -> None:
    """Test un-marking a spec navigates to the next spec."""
    async with AcePage() as page:
        # Mark first spec (navigates to second)
        await page.press("m")
        assert page.state["idx"] == 1

        # Navigate back to first spec
        await page.press("k")
        assert page.state["idx"] == 0

        # Un-mark first spec - should navigate to next (index 1)
        await page.press("m")
        assert 0 not in page.state["marked"]
        assert page.state["idx"] == 1


async def test_mark_single_spec_stays() -> None:
    """Test marking the only spec stays on it."""
    changespecs = [make_changespec(name="only_spec")]
    async with AcePage(query='"only"', changespecs=changespecs) as page:
        assert page.state["idx"] == 0

        # Mark the only spec - should stay on it
        await page.press("m")
        assert 0 in page.state["marked"]
        assert page.state["idx"] == 0
