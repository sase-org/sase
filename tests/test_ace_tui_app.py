"""Tests for the ace TUI app initialization, navigation, and modals."""

from sase.ace.patch.models import DeltaEntry, DeltaLineStats
from sase.ace.testing import (
    AcePage,
    make_changespec as make_patch,  # legacy ACE test helper name
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.patch_detail import PatchDetail


def _detail_plain(page: AcePage) -> str:
    detail = page.query_one_widget("#detail-panel", PatchDetail)
    content = detail.content
    renderable = getattr(content, "renderable", content)
    return getattr(renderable, "plain", str(renderable))


# --- Navigation Tests ---


async def test_navigation_next_key() -> None:
    """Test 'j' key navigates to next patch."""
    async with AcePage() as page:
        assert page.state["idx"] == 0
        await page.press("4")

        await page.press("j")
        await page.expect_state("idx", 1)

        await page.press("j")
        await page.expect_state("idx", 2)


async def test_navigation_next_at_end() -> None:
    """Test 'j' key at last item cycles to first item."""
    patches = [
        make_patch(name="feature_a"),
        make_patch(name="feature_b"),
    ]
    async with AcePage(patches=patches) as page:
        await page.press("4")
        await page.press("j")
        assert page.state["idx"] == 1

        # Press 'j' at end should cycle to first item
        await page.press("j")
        assert page.state["idx"] == 0


async def test_navigation_prev_at_start() -> None:
    """Test 'k' key at first item cycles to last item."""
    patches = [
        make_patch(name="feature_a"),
        make_patch(name="feature_b"),
    ]
    async with AcePage(patches=patches) as page:
        assert page.state["idx"] == 0
        await page.press("4")

        # Press 'k' at start should cycle to last item
        await page.press("k")
        assert page.state["idx"] == 1


# --- Query Edit Modal Tests ---


async def test_query_edit_modal_cancel() -> None:
    """Test pressing Escape cancels query edit modal."""
    patches = [make_patch()]
    async with AcePage(query='"original"', patches=patches) as page:
        original_query = page.state["query"]
        await page.press("4")

        # Open modal
        await page.press("slash")
        await page.expect_modal("QueryEditModal")

        # Press Escape twice: INSERT -> NORMAL, then modal cancel.
        await page.press("escape", "escape")

        # Modal should be closed and query unchanged
        await page.expect_no_modal()
        assert page.state["query"] == original_query


async def test_query_edit_modal_apply() -> None:
    """Test applying a new query updates query_string."""
    patches = [
        make_patch(name="feature_a"),
        make_patch(name="other_b"),
    ]
    async with AcePage(query='"feature"', patches=patches) as page:
        assert page.state["query"] == '"feature"'
        await page.press("4")

        # Open modal
        await page.press("slash")
        await page.expect_modal("QueryEditModal")

        # Get the input widget and set new query value
        modal = page.app.screen_stack[-1]
        input_widget = modal.query_one("#query-input", SingleLineVimTextArea)
        input_widget.text = '"other"'

        # Click Apply button
        await page.click("#apply")

        # Query should be updated
        assert page.state["query"] == '"other"'


async def test_query_edit_modal_invalid_query() -> None:
    """Test invalid query shows error notification."""
    patches = [make_patch()]
    async with AcePage(query='"valid"', patches=patches) as page:
        original_query = page.state["query"]
        await page.press("4")

        # Open modal
        await page.press("slash")
        await page.expect_modal("QueryEditModal")

        # Set invalid query (unclosed quote)
        modal = page.app.screen_stack[-1]
        input_widget = modal.query_one("#query-input", SingleLineVimTextArea)
        input_widget.text = '"unclosed'

        # Click Apply
        await page.click("#apply")

        # Query should remain unchanged
        assert page.state["query"] == original_query


# --- Marking Auto-Navigation Tests ---


async def test_unmark_navigates_to_next_spec() -> None:
    """Test un-marking a spec navigates to the next spec."""
    async with AcePage() as page:
        await page.press("4")
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
    patches = [make_patch(name="only_spec")]
    async with AcePage(query='"only"', patches=patches) as page:
        assert page.state["idx"] == 0
        await page.press("4")

        # Mark the only spec - should stay on it
        await page.press("m")
        assert 0 in page.state["marked"]
        assert page.state["idx"] == 0


# --- Fold Mode Tests ---


async def test_deltas_fold_mode_cycles_summary_files_lines() -> None:
    """Test zd cycles DELTAS through summary, file list, and line details."""
    patches = [
        make_patch(
            name="feature_deltas",
            deltas=[
                DeltaEntry(
                    path="src/feature.py",
                    change_type="M",
                    line_stats=DeltaLineStats(added=2, modified=3, removed=1),
                )
            ],
        )
    ]
    async with AcePage(query='"feature_deltas"', patches=patches) as page:
        await page.press("4")
        assert "DELTAS:  +0 ~1 (+2 ~3 -1) -0 (1 file)" in _detail_plain(page)
        assert "src/feature.py" not in _detail_plain(page)

        await page.press("z", "d")
        await page.expect_state("deltas_collapsed", "expanded")
        assert "~ src/feature.py" in _detail_plain(page)
        assert "+2 ~3 -1" not in _detail_plain(page)

        await page.press("z", "d")
        await page.expect_state("deltas_collapsed", "fully_expanded")
        assert "~ src/feature.py  +2 ~3 -1" in _detail_plain(page)

        await page.press("z", "d")
        await page.expect_state("deltas_collapsed", "collapsed")
        assert "DELTAS:  +0 ~1 (+2 ~3 -1) -0 (1 file)" in _detail_plain(page)
        assert "src/feature.py" not in _detail_plain(page)
