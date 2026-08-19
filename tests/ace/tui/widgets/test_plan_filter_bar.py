"""Widget-level tests for the plans filter command line."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from sase.ace.tui.widgets.artifacts.plan_filter_bar import PlanFilterBar
from sase.ace.tui.widgets.artifacts.types import ARTIFACTS_ACCENTS
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


def test_default_accent_is_plans_purple() -> None:
    assert PlanFilterBar().ACCENT == ARTIFACTS_ACCENTS["plans"]


def test_contract_accent_overrides_the_pinned_plans_default() -> None:
    """A non-Plan document provider's filter bar must not render Plans-purple."""
    bar = PlanFilterBar(accent="#058D1D")
    assert bar.ACCENT == "#058D1D"
    assert bar.ACCENT != ARTIFACTS_ACCENTS["plans"]


class _PlanFilterBarApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        yield PlanFilterBar()

    def on_plan_filter_bar_query_changed(
        self, message: PlanFilterBar.QueryChanged
    ) -> None:
        self.messages.append(("changed", message.text))

    def on_plan_filter_bar_submitted(self, message: PlanFilterBar.Submitted) -> None:
        self.messages.append(("submitted", message.text))

    def on_plan_filter_bar_dismissed(self, _message: PlanFilterBar.Dismissed) -> None:
        self.messages.append(("dismissed", ""))


def _option_labels(option_list: OptionList) -> list[str]:
    return [
        option_list.get_option_at_index(index).prompt.plain
        for index in range(option_list.option_count)
    ]


async def test_cursor_movement_switches_plan_completion_context() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.set_completion_sources(
            statuses=("approved",),
            projects=("SASE Core", "tools"),
        )
        query = "kind:ac status:app project:SA"
        bar.open(query)
        await pilot.pause()

        editor = app.query_one("#plan-filter-input", SingleLineVimTextArea)
        completion = app.query_one("#plan-filter-completion", OptionList)
        assert _option_labels(completion)[0].startswith("SASE Core")

        editor.cursor_position = len("kind:ac")
        await pilot.pause()
        assert _option_labels(completion)[0].startswith("active")

        editor.cursor_position = len("kind:ac status:app")
        await pilot.pause()
        assert _option_labels(completion)[0].startswith("approved")


async def test_tab_accepts_filtered_repeatable_status_candidate() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.set_completion_sources(
            statuses=("Approved", "approved", " archived "),
            projects=(),
        )
        bar.open("status:closed,ap")
        await pilot.pause()

        completion = app.query_one("#plan-filter-completion", OptionList)
        assert len(_option_labels(completion)) == 1
        assert _option_labels(completion)[0].startswith("Approved")

        await pilot.press("tab")
        await pilot.pause()

        editor = app.query_one("#plan-filter-input", SingleLineVimTextArea)
        assert editor.text == "status:closed,Approved "
        assert editor.cursor_position == len(editor.text)
        assert app.messages == [("changed", editor.text)]


async def test_status_completion_keeps_proposed_document_status() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.open("status:pr")
        await pilot.pause()

        completion = app.query_one("#plan-filter-completion", OptionList)
        labels = _option_labels(completion)
        assert labels[0].startswith("proposed")
        assert not any(label.startswith("claimed") for label in labels)


async def test_tab_quotes_project_display_name() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.set_completion_sources(statuses=(), projects=("SASE Core",))
        bar.open("project:SA")
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()

        editor = app.query_one("#plan-filter-input", SingleLineVimTextArea)
        assert editor.text == 'project:"SASE Core" '
        assert editor.cursor_position == len(editor.text)


async def test_negative_key_and_comma_value_completion_preserve_minus() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.set_completion_sources(statuses=("blocked",), projects=("SASE Core",))
        bar.open("-st")
        await pilot.pause()

        completion = app.query_one("#plan-filter-completion", OptionList)
        assert len(_option_labels(completion)) == 1
        assert _option_labels(completion)[0].startswith("-status:")
        await pilot.press("tab")
        await pilot.pause()
        editor = app.query_one("#plan-filter-input", SingleLineVimTextArea)
        assert editor.text == "-status:"

        editor.load_text("-status:open,bl")
        editor.cursor_position = len(editor.text)
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert editor.text == "-status:open,blocked "

        editor.load_text("-project:SA")
        editor.cursor_position = len(editor.text)
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert editor.text == '-project:"SASE Core" '


async def test_negative_plan_completion_omits_date_bounds() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.open("-")
        await pilot.pause()

        labels = _option_labels(app.query_one("#plan-filter-completion", OptionList))
        assert any(label.startswith("-kind:") for label in labels)
        assert any(label.startswith("-status:") for label in labels)
        assert not any(label.startswith("-since:") for label in labels)
        assert not any(label.startswith("-until:") for label in labels)


async def test_completion_sources_are_trimmed_sorted_and_deduplicated() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.set_completion_sources(
            statuses=(" Zeta ", "alpha", "ALPHA", "open"),
            projects=(" Zebra ", "alpha", "ALPHA", ""),
        )
        bar.open("status:")
        await pilot.pause()

        completion = app.query_one("#plan-filter-completion", OptionList)
        labels = _option_labels(completion)
        assert sum(label.startswith("open") for label in labels) == 1
        assert sum(label.startswith("alpha") for label in labels) == 1
        assert sum(label.startswith("Zeta") for label in labels) == 1

        editor = app.query_one("#plan-filter-input", SingleLineVimTextArea)
        editor.load_text("project:")
        editor.cursor_position = len(editor.text)
        await pilot.pause()
        assert [label.split()[0] for label in _option_labels(completion)] == [
            "alpha",
            "Zebra",
        ]


async def test_kind_completion_includes_observed_document_roles() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.set_completion_sources(
            statuses=(),
            projects=(),
            kinds=("designs", "research"),
        )
        bar.open("kind:d")
        await pilot.pause()

        labels = _option_labels(app.query_one("#plan-filter-completion", OptionList))
        assert labels[0].startswith("designs")


async def test_typing_emits_changed_before_submitted() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.open("")
        await pilot.pause()

        await pilot.press("e", "p", "i", "c", "enter")
        await pilot.pause()

        assert app.messages == [
            ("changed", "e"),
            ("changed", "ep"),
            ("changed", "epi"),
            ("changed", "epic"),
            ("submitted", "epic"),
        ]


async def test_enter_accepts_only_a_user_highlighted_completion() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.open("kind:")
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        assert app.messages == [("submitted", "kind:")]

        app.messages.clear()
        await pilot.press("down", "enter")
        await pilot.pause()
        editor = app.query_one("#plan-filter-input", SingleLineVimTextArea)
        assert editor.text == "kind:proposal "
        assert not any(kind == "submitted" for kind, _text in app.messages)


async def test_escape_closes_dropdown_before_dismissing() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PlanFilterBar)
        bar.open("")
        await pilot.pause()
        completion = app.query_one("#plan-filter-completion", OptionList)
        assert completion.display is True

        await pilot.press("escape")
        await pilot.pause()
        assert completion.display is False
        assert app.messages == []

        await pilot.press("escape")
        await pilot.pause()
        assert app.messages == [("dismissed", "")]


async def test_status_and_close_use_plan_ids() -> None:
    app = _PlanFilterBarApp()
    async with app.run_test():
        bar = app.query_one(PlanFilterBar)
        status = app.query_one("#plan-filter-status", Static)

        bar.set_status(2, True, None)
        assert status.render().plain == "2 matches  ·  exact"

        bar.open("")
        bar.close()
        assert bar.display is True
        assert app.query_one("#plan-filter-completion", OptionList).display is False
        editor = app.query_one("#plan-filter-input", SingleLineVimTextArea)
        assert editor.display is False
        assert editor.can_focus is False
