"""Tests for the ace TUI app initialization, navigation, and modals."""

from sase.ace.patch.models import DeltaEntry, DeltaLineStats
from sase.ace.testing import (
    AcePage,
    make_changespec as make_patch,  # legacy ACE test helper name
)
from textual.widgets import Static

from sase.ace.tui.widgets.artifacts.patch_filter_bar import PatchFilterBar
from sase.ace.tui.widgets.patch_detail import PatchDetail


def _detail_plain(page: AcePage) -> str:
    detail = page.query_one_widget("#detail-panel", PatchDetail)
    content = detail.content
    renderable = getattr(content, "renderable", content)
    return getattr(renderable, "plain", str(renderable))


async def _open_patch_filter_bar(page: AcePage) -> PatchFilterBar:
    await page.press("slash")
    bar = page.query_one_widget("#patch-filter-bar", PatchFilterBar)
    await page.wait_for(lambda _state: bar._editing)  # type: ignore[attr-defined]
    return bar


# --- Navigation Tests ---


async def test_navigation_next_key() -> None:
    """Test 'j' key navigates to next patch."""
    async with AcePage() as page:
        assert page.state["idx"] == 0
        await page.press("2")

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
        await page.press("2")
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
        await page.press("2")

        # Press 'k' at start should cycle to last item
        await page.press("k")
        assert page.state["idx"] == 1


# --- Patch Inline Filter Tests ---


async def test_patch_inline_filter_cancel() -> None:
    """Escape restores the previous Patch query."""
    patches = [make_patch()]
    async with AcePage(query='"original"', patches=patches) as page:
        original_query = page.state["query"]
        await page.press("2")

        bar = await _open_patch_filter_bar(page)

        await page.press("escape")

        await page.wait_for(lambda _state: not bar._editing)  # type: ignore[attr-defined]
        assert page.state["query"] == original_query


async def test_patch_inline_filter_apply() -> None:
    """Submitting a new Patch query updates query_string."""
    patches = [
        make_patch(name="feature_a"),
        make_patch(name="other_b"),
    ]
    async with AcePage(query='"feature"', patches=patches) as page:
        assert page.state["query"] == '"feature" limit:100'
        await page.press("2")

        bar = await _open_patch_filter_bar(page)
        bar.set_query('"other"')
        bar.post_message(PatchFilterBar.Submitted('"other"'))
        await page.wait_for(lambda _state: page.state["query"] == '"other"')

        assert page.state["query"] == '"other"'


async def test_patch_inline_filter_invalid_query() -> None:
    """Invalid submitted Patch query leaves query_string unchanged and shows error."""
    patches = [make_patch()]
    async with AcePage(query='"valid"', patches=patches) as page:
        original_query = page.state["query"]
        await page.press("2")

        bar = await _open_patch_filter_bar(page)
        bar.set_query('"unclosed')
        bar.post_message(PatchFilterBar.Submitted('"unclosed'))
        await page.pause()

        status = bar.query_one("#patch-filter-status", Static)
        assert status.has_class("error")
        assert status.content.plain

        assert page.state["query"] == original_query


# --- Marking Auto-Navigation Tests ---


async def test_unmark_navigates_to_next_spec() -> None:
    """Test un-marking a spec navigates to the next spec."""
    async with AcePage() as page:
        await page.press("2")
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
        await page.press("2")

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
        await page.press("2")
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
