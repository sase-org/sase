"""Compact-label and click-range coverage for reusable panel tabs."""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult

from sase.ace.tui.widgets.panel_tab_strip import PanelTab, PanelTabStrip


async def test_compact_labels_preserve_active_treatment_and_click_ranges() -> None:
    tabs = (
        PanelTab("overview", "Overview", "#FF87D7", compact_label="Overview"),
        PanelTab(
            "plans_questions",
            "Plans & Questions",
            "#FF87D7",
            compact_label="Plans/Q",
        ),
    )

    class _TabStripApp(App[None]):
        selected: str | None = None

        def compose(self) -> ComposeResult:
            yield PanelTabStrip(
                tabs,
                "overview",
                uppercase_active=True,
                compact_below=70,
                id="tabs",
            )

        @on(PanelTabStrip.TabClicked)
        def _on_tab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
            self.selected = event.tab_id

    async with _TabStripApp().run_test(size=(60, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", PanelTabStrip)
        assert strip._compact is True
        assert strip._build_content().plain == "OVERVIEW │ Plans/Q"
        start, end = strip._tab_ranges["plans_questions"]
        assert strip._build_content().plain[start:end] == "Plans/Q"

        center_pad = max(0, (strip.size.width - strip._line_width) // 2)
        await pilot.click(strip, offset=(center_pad + start + 1, 0))
        await pilot.pause()

        assert pilot.app.selected == "plans_questions"
        strip.set_active_tab("plans_questions")
        assert strip._build_content().plain == "Overview │ PLANS/Q"


def test_full_labels_remain_canonical_until_compact_threshold() -> None:
    strip = PanelTabStrip(
        (
            PanelTab("runs", "Runs", "cyan", compact_label="Run"),
            PanelTab(
                "plans_questions",
                "Plans & Questions",
                "magenta",
                compact_label="Plans/Q",
            ),
        ),
        "runs",
        uppercase_active=True,
        compact_below=40,
    )

    assert strip._build_content().plain == " RUNS  │  Plans & Questions "
    assert strip._tab_ranges["runs"] == (0, 6)
    assert strip._tab_ranges["plans_questions"] == (9, 28)


def test_custom_compact_separator_preserves_width_and_click_ranges() -> None:
    strip = PanelTabStrip(
        (
            PanelTab("one", "One", "cyan"),
            PanelTab("two", "Two", "magenta"),
            PanelTab("three", "Three", "green"),
        ),
        "one",
        compact_below=100,
        compact_separator="│",
    )
    strip._compact = True

    assert strip._build_content().plain == "One│Two│Three"
    assert strip._line_width == 13
    assert strip._tab_ranges == {
        "one": (0, 3),
        "two": (4, 7),
        "three": (8, 13),
    }
