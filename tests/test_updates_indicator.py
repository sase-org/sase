"""Tests for the UpdatesAvailableIndicator widget rendering."""

from sase.ace.tui.widgets.updates_indicator import UpdatesAvailableIndicator


def test_zero_updates_renders_hidden_badge() -> None:
    text = UpdatesAvailableIndicator._build_content(0)

    assert text.plain == ""


def test_positive_updates_render_updates_badge() -> None:
    text = UpdatesAvailableIndicator._build_content(3)

    assert text.plain == " ↑ 3 "
    assert "#AF87FF" in str(text.style)


def test_tooltip_singular_and_plural() -> None:
    assert (
        UpdatesAvailableIndicator._build_tooltip(1)
        == "1 update available - open the Updates tab (click, or press # then 5)"
    )
    assert (
        UpdatesAvailableIndicator._build_tooltip(2)
        == "2 updates available - open the Updates tab (click, or press # then 5)"
    )


def test_set_available_updates_count_and_tooltip() -> None:
    indicator = UpdatesAvailableIndicator()

    indicator.set_available(2)

    assert indicator.count == 2
    assert indicator.tooltip == (
        "2 updates available - open the Updates tab (click, or press # then 5)"
    )


async def test_click_dispatches_open_updates_panel_action() -> None:
    from textual.app import App, ComposeResult

    calls: list[str] = []

    class _TestApp(App[None]):
        def compose(self) -> ComposeResult:
            yield UpdatesAvailableIndicator(id="updates-indicator")

        def action_open_updates_panel(self) -> None:
            calls.append("opened")

    app = _TestApp()
    async with app.run_test() as pilot:
        indicator = pilot.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(1)
        await pilot.click("#updates-indicator")
        await pilot.pause()
        assert calls == ["opened"]
