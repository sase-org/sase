"""Behavioral coverage for the Agents grouping picker modal (o/O ladder)."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.modals.agent_grouping_modal import (
    AgentGroupingModal,
    AgentGroupingResult,
)
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panel_layout import AgentPanelLayout
from textual.widgets import Static


def _plain(modal: AgentGroupingModal, selector: str) -> str:
    return modal.query_one(selector, Static).render().plain


async def test_agent_grouping_modal_direct_keys_and_cancel() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage() as page:
        page.app.push_screen(AgentGroupingModal(GroupingMode.STANDARD), results.append)
        await page.expect_modal("AgentGroupingModal")

        await page.press("x")
        await page.pause()
        assert page.state["modal"] == "AgentGroupingModal"
        assert results == []

        await page.press("s")
        await page.expect_no_modal()
        assert results == [GroupingMode.BY_STATUS]

        page.app.push_screen(AgentGroupingModal(GroupingMode.BY_STATUS), results.append)
        await page.expect_modal("AgentGroupingModal")
        await page.press("escape")
        await page.expect_no_modal()
        assert results == [GroupingMode.BY_STATUS, None]


async def test_agent_grouping_modal_o_steps_forward_and_o_steps_back() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage() as page:
        page.app.push_screen(AgentGroupingModal(GroupingMode.STANDARD), results.append)
        await page.expect_modal("AgentGroupingModal")

        # ``o`` selects the next level (Split -> Merged) and dismisses.
        await page.press("o")
        await page.expect_no_modal()
        assert results == [AgentPanelLayout.MERGED]

        page.app.push_screen(
            AgentGroupingModal(
                GroupingMode.STANDARD, current_layout=AgentPanelLayout.MERGED
            ),
            results.append,
        )
        await page.expect_modal("AgentGroupingModal")

        # ``O`` selects the previous level (Merged -> Split) and dismisses.
        await page.press("O")
        await page.expect_no_modal()
        assert results == [AgentPanelLayout.MERGED, AgentPanelLayout.SPLIT]


async def test_agent_grouping_modal_o_wraps_in_two_segment_mode() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage() as page:
        page.app.push_screen(
            AgentGroupingModal(
                GroupingMode.STANDARD, current_layout=AgentPanelLayout.MERGED
            ),
            results.append,
        )
        await page.expect_modal("AgentGroupingModal")

        # With fewer than two tabs only Split/Merged are offered, so ``o``
        # from Merged wraps back to Split.
        await page.press("o")
        await page.expect_no_modal()
        assert results == [AgentPanelLayout.SPLIT]


async def test_agent_grouping_modal_three_segment_ladder() -> None:
    results: list[AgentGroupingResult] = []
    available = (
        AgentPanelLayout.SPLIT,
        AgentPanelLayout.MERGED,
        AgentPanelLayout.ALL_TABS,
    )
    async with AcePage() as page:
        modal = AgentGroupingModal(
            GroupingMode.STANDARD,
            current_layout=AgentPanelLayout.MERGED,
            available_layouts=available,
            active_tab_label="sase",
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(modal.query("#agent-panel-layout-row"))
        )

        row_text = _plain(modal, "#agent-panel-layout-row")
        assert "Split by tribe" in row_text
        assert "Merged" in row_text
        assert "All tabs" in row_text
        assert "One panel with every agent on sase." in row_text

        await page.press("o")
        await page.expect_no_modal()
        assert results == [AgentPanelLayout.ALL_TABS]


async def test_agent_grouping_modal_layout_labels_and_description() -> None:
    async with AcePage() as page:
        split_modal = AgentGroupingModal(
            GroupingMode.STANDARD,
            current_panel_grouped=False,
        )
        page.app.push_screen(split_modal, lambda _result: None)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(split_modal.query("#agent-panel-layout-row"))
        )

        split_text = _plain(split_modal, "#agent-panel-layout-row")
        assert "Split by tribe" in split_text
        assert "Merged" in split_text
        assert "All tabs" not in split_text
        assert "One panel per tribe, showing this tab only." in split_text

        heading = _plain(split_modal, "#agent-panel-layout-heading")
        assert "Panel layout" in heading
        assert "o next" in heading

        await page.press("escape")
        await page.expect_no_modal()

        merged_modal = AgentGroupingModal(
            GroupingMode.BY_STATUS,
            current_panel_grouped=True,
        )
        page.app.push_screen(merged_modal, lambda _result: None)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(merged_modal.query("#agent-panel-layout-row"))
        )

        merged_text = _plain(merged_modal, "#agent-panel-layout-row")
        assert "One panel with every agent on this tab." in merged_text
        assert merged_modal.query_one("#agent-grouping-row-2").has_class("current")

        await page.press("escape")
        await page.expect_no_modal()


async def test_agent_grouping_modal_segment_highlight_enter_and_hl() -> None:
    results: list[AgentGroupingResult] = []
    available = (
        AgentPanelLayout.SPLIT,
        AgentPanelLayout.MERGED,
        AgentPanelLayout.ALL_TABS,
    )
    async with AcePage() as page:
        modal = AgentGroupingModal(
            GroupingMode.STANDARD,
            current_layout=AgentPanelLayout.SPLIT,
            available_layouts=available,
            active_tab_label="sase",
        )
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentGroupingModal")

        # Move the cursor onto the layout row, then move the segment
        # highlight with ``l`` and select it with Enter.
        await page.press("j", "j", "j", "j")
        await page.wait_for(
            lambda _screen: modal.query_one("#agent-panel-layout-row").has_class(
                "focused"
            )
        )
        assert modal.highlighted_layout is AgentPanelLayout.SPLIT
        await page.press("l")
        assert modal.highlighted_layout is AgentPanelLayout.MERGED
        await page.press("l")
        assert modal.highlighted_layout is AgentPanelLayout.ALL_TABS
        await page.press("h")
        assert modal.highlighted_layout is AgentPanelLayout.MERGED
        await page.press("enter")
        await page.expect_no_modal()
        assert results == [AgentPanelLayout.MERGED]


async def test_agent_grouping_modal_navigation_enter_and_current_badge() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage() as page:
        modal = AgentGroupingModal(GroupingMode.BY_DATE)
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentGroupingModal")

        def row_focused(_screen: object) -> bool:
            rows = list(modal.query("#agent-grouping-row-1"))
            return bool(rows) and rows[0].has_class("focused")

        await page.wait_for(row_focused)

        assert modal.query_one("#agent-grouping-row-1").has_class("focused")
        assert modal.query_one("#agent-grouping-row-1").has_class("current")

        await page.press("j", "j")
        assert modal.query_one("#agent-grouping-row-3").has_class("focused")
        assert modal.query_one("#agent-grouping-row-1").has_class("current")

        await page.press("enter")
        await page.expect_no_modal()
        assert results == [GroupingMode.BY_MACHINE]


async def test_agent_grouping_modal_layout_navigation_enter_and_click() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage(size=(50, 10)) as page:
        modal = AgentGroupingModal(GroupingMode.STANDARD)
        page.app.push_screen(modal, results.append)
        await page.expect_modal("AgentGroupingModal")

        await page.press("j", "j", "j", "j")
        await page.wait_for(
            lambda _screen: modal.query_one("#agent-panel-layout-row").has_class(
                "focused"
            )
        )
        await page.press("enter")
        await page.expect_no_modal()
        assert results == [AgentPanelLayout.SPLIT]

    async with AcePage() as page:
        page.app.push_screen(AgentGroupingModal(GroupingMode.STANDARD), results.append)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(page.app.screen.query("#agent-panel-layout-row"))
        )
        await page.click("#agent-panel-layout-row")
        await page.expect_no_modal()
        assert isinstance(results[-1], AgentPanelLayout)

    assert results[0] is AgentPanelLayout.SPLIT


async def test_agent_grouping_modal_click_selects_segment_directly() -> None:
    """Clicking a segment dismisses with that segment's level."""

    class _StubEvent:
        def __init__(self, x: int, y: int) -> None:
            self._offset = (x, y)

        def get_content_offset(self, _widget: object) -> tuple[int, int]:
            class _Offset:
                def __init__(self, x: int, y: int) -> None:
                    self.x = x
                    self.y = y

            return _Offset(*self._offset)

    available = (
        AgentPanelLayout.SPLIT,
        AgentPanelLayout.MERGED,
        AgentPanelLayout.ALL_TABS,
    )
    async with AcePage() as page:
        dismissed: list[AgentGroupingResult] = []
        modal = AgentGroupingModal(
            GroupingMode.STANDARD,
            current_layout=AgentPanelLayout.SPLIT,
            available_layouts=available,
        )
        page.app.push_screen(modal, lambda _result: None)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(modal.query("#agent-panel-layout-row"))
        )
        row = modal.query_one("#agent-panel-layout-row", Static)
        modal.dismiss = dismissed.append  # type: ignore[method-assign]
        for start, end, level in modal._layout_spans:
            modal._dismissed = False
            modal._select_layout_at_click(
                _StubEvent(start + (end - start) // 2, 0),
                row,  # type: ignore[arg-type]
            )
            assert dismissed[-1] is level
        assert len(dismissed) == len(available)


async def test_agent_grouping_modal_click_selects_row() -> None:
    results: list[AgentGroupingResult] = []
    async with AcePage() as page:
        page.app.push_screen(AgentGroupingModal(GroupingMode.STANDARD), results.append)
        await page.expect_modal("AgentGroupingModal")
        await page.wait_for(
            lambda _screen: bool(page.app.screen.query("#agent-grouping-row-2"))
        )

        await page.click("#agent-grouping-row-2")
        await page.expect_no_modal()

    assert results == [GroupingMode.BY_STATUS]


def test_agent_grouping_modal_segment_spans_cover_every_level() -> None:
    """The click map partitions the segment line without gaps or overlap."""
    modal = AgentGroupingModal(
        GroupingMode.STANDARD,
        current_layout=AgentPanelLayout.SPLIT,
        available_layouts=(
            AgentPanelLayout.SPLIT,
            AgentPanelLayout.MERGED,
            AgentPanelLayout.ALL_TABS,
        ),
    )
    modal._layout_row_text(focused=True)
    spans = modal._layout_spans
    assert [level for _, _, level in spans] == [
        AgentPanelLayout.SPLIT,
        AgentPanelLayout.MERGED,
        AgentPanelLayout.ALL_TABS,
    ]
    for (start, end, _), (next_start, _, _) in zip(spans, spans[1:], strict=False):
        assert start < end <= next_start
