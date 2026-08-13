"""Compact-label and click-range coverage for reusable panel tabs."""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult

from sase.ace.tui.widgets.panel_tab_strip import PanelTab, PanelTabStrip


async def test_icon_renders_between_number_and_label_and_empty_icon_is_noop() -> None:
    iconed = PanelTabStrip(
        (
            PanelTab("a", "Alpha", "cyan", shortcut="1"),
            PanelTab("b", "Beta", "magenta", icon="●", shortcut="2"),
        ),
        "a",
        show_numbers=True,
    )
    assert iconed._build_content().plain == " 1 Alpha  │  2 ● Beta "

    plain = PanelTabStrip(
        (
            PanelTab("a", "Alpha", "cyan", shortcut="1"),
            PanelTab("b", "Beta", "magenta", shortcut="2"),
        ),
        "a",
        show_numbers=True,
    )
    assert plain._build_content().plain == " 1 Alpha  │  2 Beta "


async def test_two_cell_icon_click_ranges_are_cell_accurate() -> None:
    tabs = (
        PanelTab("one", "One", "cyan", shortcut="1"),
        PanelTab("two", "Two", "magenta", icon="🔥", shortcut="2"),
        PanelTab("three", "Three", "green", shortcut="3"),
    )

    class _TabStripApp(App[None]):
        selected: str | None = None

        def compose(self) -> ComposeResult:
            yield PanelTabStrip(tabs, "one", show_numbers=True, id="tabs")

        @on(PanelTabStrip.TabClicked)
        def _on_tab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
            self.selected = event.tab_id

    async with _TabStripApp().run_test(size=(60, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", PanelTabStrip)
        # rich.cells.cell_len("🔥") is 2, so a char-counted line width would
        # be one short of this and every click past the icon would land on
        # the wrong tab.
        assert strip._line_width == 32
        start, end = strip._tab_ranges["three"]
        assert (start, end) == (23, 32)

        content_width = max(0, int(strip.size.width))
        center_pad = max(0, (content_width - strip._line_width) // 2)
        await pilot.click(strip, offset=(center_pad + start + 1, 0))
        await pilot.pause()

        assert pilot.app.selected == "three"


async def test_reflow_to_fit_ladder_picks_tier_by_width() -> None:
    tabs = (
        PanelTab(
            "aa",
            "AlphaAlpha",
            "cyan",
            compact_label="AA",
            micro_label="A",
            icon="◉",
            shortcut="1",
        ),
        PanelTab(
            "bb",
            "BetaBeta",
            "magenta",
            compact_label="BB",
            micro_label="B",
            icon="⎇",
            shortcut="2",
        ),
    )

    class _ReflowApp(App[None]):
        def compose(self) -> ComposeResult:
            yield PanelTabStrip(
                tabs, "aa", show_numbers=True, reflow_to_fit=True, id="tabs"
            )

    async with _ReflowApp().run_test(size=(40, 5)) as pilot:
        strip = pilot.app.query_one("#tabs", PanelTabStrip)

        await pilot.resize_terminal(40, 5)
        assert strip._tier == "full"
        assert set(strip._tab_ranges) == {"aa", "bb"}

        await pilot.resize_terminal(20, 5)
        assert strip._tier == "compact"
        assert set(strip._tab_ranges) == {"aa", "bb"}

        await pilot.resize_terminal(10, 5)
        assert strip._tier == "micro"
        assert set(strip._tab_ranges) == {"aa", "bb"}


def test_micro_tier_hides_inactive_labels_only_when_every_tab_has_an_icon() -> None:
    all_iconed = PanelTabStrip(
        (
            PanelTab("a", "Alpha", "cyan", micro_label="A", icon="◉"),
            PanelTab("b", "Beta", "magenta", micro_label="B", icon="⎇"),
        ),
        "a",
    )
    all_iconed._tier = "micro"
    assert all_iconed._build_content().plain == "◉ A│⎇"

    one_missing = PanelTabStrip(
        (
            PanelTab("a", "Alpha", "cyan", micro_label="A", icon="◉"),
            PanelTab("b", "Beta", "magenta", micro_label="B"),
        ),
        "a",
    )
    one_missing._tier = "micro"
    assert one_missing._build_content().plain == "◉ A│B"


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
        assert strip._tier == "compact"
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
    strip._tier = "compact"

    assert strip._build_content().plain == "One│Two│Three"
    assert strip._line_width == 13
    assert strip._tab_ranges == {
        "one": (0, 3),
        "two": (4, 7),
        "three": (8, 13),
    }
