"""Widget-level tests for the commits filter command line."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from sase.ace.tui.widgets.artifacts.commit_filter_bar import CommitFilterBar
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea


class _FilterBarApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        yield CommitFilterBar()

    def on_commit_filter_bar_query_changed(
        self, message: CommitFilterBar.QueryChanged
    ) -> None:
        self.messages.append(("changed", message.text))

    def on_commit_filter_bar_submitted(
        self, message: CommitFilterBar.Submitted
    ) -> None:
        self.messages.append(("submitted", message.text))

    def on_commit_filter_bar_dismissed(
        self, _message: CommitFilterBar.Dismissed
    ) -> None:
        self.messages.append(("dismissed", ""))


def _option_labels(option_list: OptionList) -> list[str]:
    return [
        option_list.get_option_at_index(index).prompt.plain
        for index in range(option_list.option_count)
    ]


async def test_open_prefills_focuses_and_filters_repo_candidates() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.set_completion_sources(
            repos=("sase-nvim", "sase", "chezmoi", "SASE"),
            authors=("Bryan Bugyi",),
        )
        bar.open("repo:sa")
        await pilot.pause()

        editor = app.query_one("#commit-filter-input", SingleLineVimTextArea)
        completion = app.query_one("#commit-filter-completion", OptionList)
        labels = _option_labels(completion)

        assert bar.display is True
        assert app.focused is editor
        assert editor.text == "repo:sa"
        assert completion.display is True
        assert len(labels) == 2
        assert labels[0].startswith("sase ")
        assert labels[1].startswith("sase-nvim")
        assert app.messages == []


async def test_cursor_movement_switches_completion_context() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.set_completion_sources(
            repos=("sase",),
            authors=("Bryan Bugyi", "Alice"),
        )
        query = "repo:sa author:Bry"
        bar.open(query)
        await pilot.pause()

        editor = app.query_one("#commit-filter-input", SingleLineVimTextArea)
        completion = app.query_one("#commit-filter-completion", OptionList)
        assert _option_labels(completion)[0].startswith("Bryan Bugyi")

        editor.cursor_position = len("repo:sa")
        await pilot.pause()
        assert _option_labels(completion)[0].startswith("sase")


async def test_tab_accepts_value_quotes_it_and_emits_changed() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.set_completion_sources(repos=(), authors=("Bryan Bugyi",))
        bar.open("author:Bry")
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()

        editor = app.query_one("#commit-filter-input", SingleLineVimTextArea)
        assert editor.text == 'author:"Bryan Bugyi" '
        assert editor.cursor_position == len(editor.text)
        assert app.messages == [("changed", editor.text)]


async def test_tab_preserves_repeatable_comma_values() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.set_completion_sources(repos=("sase-nvim",), authors=())
        bar.open("repo:sase,sa")
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()

        editor = app.query_one("#commit-filter-input", SingleLineVimTextArea)
        assert editor.text == "repo:sase,sase-nvim "


async def test_negative_key_and_value_completion_preserve_minus_and_quotes() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.set_completion_sources(repos=("plans",), authors=("Build Bot",))
        bar.open("-re")
        await pilot.pause()

        completion = app.query_one("#commit-filter-completion", OptionList)
        assert len(_option_labels(completion)) == 1
        assert _option_labels(completion)[0].startswith("-repo:")
        await pilot.press("tab")
        await pilot.pause()
        editor = app.query_one("#commit-filter-input", SingleLineVimTextArea)
        assert editor.text == "-repo:"

        editor.load_text("-author:Build")
        editor.cursor_position = len(editor.text)
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert editor.text == '-author:"Build Bot" '


async def test_negative_completion_omits_non_negatable_keys() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.open("-")
        await pilot.pause()

        labels = _option_labels(app.query_one("#commit-filter-completion", OptionList))
        assert any(label.startswith("-repo:") for label in labels)
        assert any(label.startswith("-author:") for label in labels)
        assert not any(label.startswith("-since:") for label in labels)
        assert not any(label.startswith("-until:") for label in labels)
        assert not any(label.startswith("-sidecar:") for label in labels)
        assert not any(label.startswith("-limit:") for label in labels)


async def test_sidecar_key_and_boolean_values_complete_without_io() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.open("side")
        await pilot.pause()

        completion = app.query_one("#commit-filter-completion", OptionList)
        labels = _option_labels(completion)
        assert len(labels) == 1
        assert labels[0].startswith("sidecar:")
        assert "include sidecar repositories" in labels[0]

        editor = app.query_one("#commit-filter-input", SingleLineVimTextArea)
        editor.load_text("sidecar:")
        editor.cursor_position = len(editor.text)
        await pilot.pause()
        labels = _option_labels(completion)
        assert labels[0].startswith("true")
        assert labels[1].startswith("false")
        assert all("true or false" in label for label in labels)


async def test_project_name_and_warm_inventory_values_complete() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.set_project_completion_sources(("sase", "sase-github"))
        bar.open("proj")
        await pilot.pause()

        completion = app.query_one("#commit-filter-completion", OptionList)
        labels = _option_labels(completion)
        assert len(labels) == 1
        assert labels[0].startswith("project:")
        assert "single project name" in labels[0]
        assert "omitted means all projects" in labels[0]

        editor = app.query_one("#commit-filter-input", SingleLineVimTextArea)
        editor.load_text("project:sase-g")
        editor.cursor_position = len(editor.text)
        await pilot.pause()
        assert len(_option_labels(completion)) == 1
        assert _option_labels(completion)[0].startswith("sase-github")
        assert "project name" in _option_labels(completion)[0]


async def test_typing_emits_changed_before_submitted() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.open("")
        await pilot.pause()

        await pilot.press("f", "i", "x", "enter")
        await pilot.pause()

        assert app.messages == [
            ("changed", "f"),
            ("changed", "fi"),
            ("changed", "fix"),
            ("submitted", "fix"),
        ]


async def test_enter_submits_unless_user_highlighted_completion() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.set_completion_sources(repos=("sase",), authors=())
        bar.open("repo:")
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        assert app.messages == [("submitted", "repo:")]

        app.messages.clear()
        await pilot.press("down", "enter")
        await pilot.pause()
        editor = app.query_one("#commit-filter-input", SingleLineVimTextArea)
        assert editor.text == "repo:sase "
        assert not any(kind == "submitted" for kind, _text in app.messages)


async def test_escape_closes_dropdown_before_dismissing() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.open("")
        await pilot.pause()
        completion = app.query_one("#commit-filter-completion", OptionList)
        assert completion.display is True

        await pilot.press("escape")
        await pilot.pause()
        assert completion.display is False
        assert app.messages == []

        await pilot.press("escape")
        await pilot.pause()
        assert app.messages == [("dismissed", "")]


async def test_status_renders_coverage_only_and_preserves_parse_error() -> None:
    app = _FilterBarApp()
    async with app.run_test():
        bar = app.query_one(CommitFilterBar)
        status = app.query_one("#commit-filter-status", Static)

        bar.set_status(1, True, None)
        assert status.render().plain == "exact"

        bar.set_status(
            40,
            False,
            None,
            coverage_label="capped",
            lower_bound=True,
        )
        assert status.render().plain == "capped"

        bar.set_status(
            1,
            False,
            None,
            coverage_label="capped",
            lower_bound=True,
        )
        assert status.render().plain == "capped"

        bar.set_status(None, False, "repo: requires a value")
        assert status.render().plain == "repo: requires a value"
        assert status.has_class("error")


async def test_static_value_completions_explain_dates_merges_and_caps() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)
        bar.open("until:")
        await pilot.pause()

        completion = app.query_one("#commit-filter-completion", OptionList)
        assert all(
            "named days include the full day" in label
            for label in _option_labels(completion)
        )

        editor = app.query_one("#commit-filter-input", SingleLineVimTextArea)
        editor.load_text("limit:")
        editor.cursor_position = len(editor.text)
        await pilot.pause()
        assert all("row cap or all" in label for label in _option_labels(completion))

        editor.load_text("merges:")
        editor.cursor_position = len(editor.text)
        await pilot.pause()
        labels = _option_labels(completion)
        assert [label.split()[0] for label in labels] == ["hide", "show", "only"]
        assert all("hide, show, or only" in label for label in labels)


async def test_close_leaves_persistent_bar_visible_and_hides_completion() -> None:
    app = _FilterBarApp()
    async with app.run_test():
        bar = app.query_one(CommitFilterBar)
        bar.open("")
        bar.close()

        assert bar.display is True
        assert app.query_one("#commit-filter-completion", OptionList).display is False


async def test_programmatic_query_update_does_not_emit_user_change() -> None:
    app = _FilterBarApp()
    async with app.run_test() as pilot:
        bar = app.query_one(CommitFilterBar)

        bar.set_query("sidecar:false since:24h")
        await pilot.pause()

        assert bar.query_one("#commit-filter-input", SingleLineVimTextArea).text == (
            "sidecar:false since:24h"
        )
        assert bar.query_one("#commit-filter-completion", OptionList).display is False
        assert app.messages == []
