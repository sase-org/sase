"""Placeholder completion and highlighting in ``PromptTextArea``."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
    PlaceholderCompletionMetadata,
    _editor_position_for_offset,
    _editor_position_to_offset,
    build_placeholder_completion_result,
    placeholder_lone_leading_match,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def _highlight_names(ta: PromptTextArea) -> list[str]:
    return [name for row in ta._highlights.values() for *_range, name in row]


def _sources(ta: PromptTextArea) -> list[str | None]:
    return [
        getattr(candidate.metadata, "source", None)
        for candidate in ta._file_completion_candidates
    ]


def _insertions(ta: PromptTextArea) -> list[str]:
    return [candidate.insertion for candidate in ta._file_completion_candidates]


def test_builder_maps_utf16_ranges_to_python_offsets() -> None:
    text = "😀 <Alpha> use <A>"
    result = build_placeholder_completion_result(text, text.index("A>", 10) + 1)

    assert result is not None
    assert result.prefix == "A"
    assert (result.replacement_start, result.replacement_end) == (
        text.rindex("<") + 1,
        text.rindex(">"),
    )
    assert [candidate.insertion for candidate in result.candidates] == ["Alpha"]

    position = _editor_position_for_offset(text, text.index("<"))
    assert position is not None
    assert position.character == 3
    assert _editor_position_to_offset(text, position) == text.index("<")


async def test_typing_open_bracket_auto_opens_and_live_narrows() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> and <alpine> then ")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("<")

        assert ta._completion_kind == PLACEHOLDER_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == [
            "alpha",
            "alpine",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "placeholder"
        assert panel.border_subtitle == "[^D] delete"
        assert "<> alpha" in panel.render().plain  # type: ignore[union-attr]

        await pilot.press("a", "l", "p", "h")

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["alpha"]


async def test_accept_replaces_inner_text_with_and_without_closing_bracket() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> then <a>")
        ta.cursor_location = (0, len(ta.text) - 1)
        assert ta._try_auto_placeholder_completion() is True

        await pilot.press("enter")

        assert ta.text == "Use <alpha> then <alpha>"
        assert ta.cursor_location == (0, len(ta.text))

        ta.load_text("Use <alpha> then <a")
        ta.cursor_location = (0, len(ta.text))
        assert ta._try_auto_placeholder_completion() is True

        await pilot.press("enter")

        assert ta.text == "Use <alpha> then <alpha>"
        assert ta.cursor_location == (0, len(ta.text))


async def test_placeholder_free_prompt_stays_silent() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("<")

        assert ta.text == "<"
        assert ta._file_completion_active is False
        assert ta._file_completion_candidates == []


async def test_ctrl_t_explicitly_accepts_single_placeholder_with_auto_off() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> then <a")
        ta.cursor_location = (0, len(ta.text))

        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto="off"),
        ):
            await pilot.press("ctrl+t")

        assert ta.text == "Use <alpha> then <alpha>"
        assert ta._file_completion_active is False


async def test_snippet_tabstop_opens_completion_and_survives_accept() -> None:
    app = CompletionTestApp(snippets={"cbi": "`<$1>`$0"})
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Reuse <alpha>: cbi")
        ta.cursor_location = (0, len(ta.text))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda self: app),
        ):
            await pilot.press("tab")

            assert ta.text == "Reuse <alpha>: `<>`"
            assert ta._completion_kind == PLACEHOLDER_COMPLETION_KIND
            assert ta._file_completion_active is True
            assert ta.cursor_location == (0, ta.text.rindex("<") + 1)

            await pilot.press("enter")

            assert ta.text == "Reuse <alpha>: `<alpha>`"
            assert ta.cursor_location == (0, ta.text.rindex(">") + 1)

            await pilot.press("tab")

            assert ta.cursor_location == (0, len(ta.text))


async def test_placeholder_highlight_uses_cached_rust_spans() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use `<alpha>` and <beta>")
        ta._build_highlight_map()

        names = _highlight_names(ta)
        assert names.count("placeholder.delimiter") == 2
        assert names.count("placeholder.inner") == 1
        assert "placeholder.delimiter" in ta._theme.syntax_styles
        assert "placeholder.inner" in ta._theme.syntax_styles

        cached = ta._placeholder_cached_spans
        ta._build_highlight_map()
        assert ta._placeholder_cached_spans is cached

        ta.load_text("Use <gamma>")
        ta._build_highlight_map()
        assert ta._placeholder_cached_spans is not cached


def test_builder_appends_saved_candidates_after_prompt_local_ones() -> None:
    text = "Use <feature flag> and <fe"
    result = build_placeholder_completion_result(
        text,
        len(text),
        ["fedora", "feature branch"],
    )

    assert result is not None
    assert [candidate.insertion for candidate in result.candidates] == [
        "feature flag",
        "fedora",
        "feature branch",
    ]
    assert [candidate.metadata for candidate in result.candidates] == [
        PlaceholderCompletionMetadata(source="prompt"),
        PlaceholderCompletionMetadata(source="common"),
        PlaceholderCompletionMetadata(source="common"),
    ]


def test_builder_ranks_live_then_literal_then_saved_candidates() -> None:
    text = "Use <feature branch> and `<feature flag>` then <fe"
    result = build_placeholder_completion_result(text, len(text), ["fedora"])

    assert result is not None
    assert [candidate.insertion for candidate in result.candidates] == [
        "feature branch",
        "feature flag",
        "fedora",
    ]
    assert [candidate.metadata for candidate in result.candidates] == [
        PlaceholderCompletionMetadata(source="prompt"),
        PlaceholderCompletionMetadata(source="prompt"),
        PlaceholderCompletionMetadata(source="common"),
    ]


def test_lone_leading_match_counts_only_the_highest_priority_group() -> None:
    lone_prompt = build_placeholder_completion_result(
        "Use <alpha> then <a",
        len("Use <alpha> then <a"),
        ["anchor", "aperture"],
    )
    multiple_prompt = build_placeholder_completion_result(
        "Use <alpha> and <alpine> then <a",
        len("Use <alpha> and <alpine> then <a"),
        ["anchor"],
    )

    assert lone_prompt is not None
    assert placeholder_lone_leading_match(lone_prompt) is True
    assert multiple_prompt is not None
    assert placeholder_lone_leading_match(multiple_prompt) is False


def test_builder_shows_prompt_and_store_duplicate_once_as_prompt_local() -> None:
    text = "Use <alpha> then <a"
    result = build_placeholder_completion_result(text, len(text), ["alpha", "Alpha"])

    assert result is not None
    # The exact duplicate collapses onto the prompt-local row; the casing
    # variant survives because it is a genuinely different insertion.
    assert [
        (candidate.insertion, getattr(candidate.metadata, "source", None))
        for candidate in result.candidates
    ] == [("alpha", "prompt"), ("Alpha", "common")]


def test_builder_drops_saved_candidates_at_an_empty_prefix_by_default() -> None:
    text = "Use <alpha> then <"

    auto = build_placeholder_completion_result(text, len(text), ["beta"])
    assert auto is not None
    assert [candidate.insertion for candidate in auto.candidates] == ["alpha"]

    manual = build_placeholder_completion_result(
        text,
        len(text),
        ["beta"],
        include_common_when_prefix_empty=True,
    )
    assert manual is not None
    assert [candidate.insertion for candidate in manual.candidates] == [
        "alpha",
        "beta",
    ]


def test_builder_stays_silent_when_only_saved_candidates_are_filtered_out() -> None:
    # No prompt-local tags plus a suppressed saved group means no menu at all,
    # preserving today's "a bare ``<`` in prose does nothing" contract.
    assert build_placeholder_completion_result("a < b", 3, ["beta"]) is None


async def test_auto_trigger_gains_saved_group_only_once_a_prefix_is_typed() -> None:
    app = CompletionTestApp(common_placeholders=["feature flag", "fedora"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> and ")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("<")

        assert ta._completion_kind == PLACEHOLDER_COMPLETION_KIND
        assert ta._placeholder_completion_trigger == "auto"
        assert _insertions(ta) == ["alpha"]

        await pilot.press("f", "e")

        assert _insertions(ta) == ["feature flag", "fedora"]
        assert _sources(ta) == ["common", "common"]

        # Backspacing back to a bare ``<`` drops the saved group again.
        await pilot.press("backspace", "backspace")

        assert _insertions(ta) == ["alpha"]

        await pilot.press("f")

        assert _insertions(ta) == ["feature flag", "fedora"]


async def test_manual_trigger_shows_the_full_saved_list_at_a_bare_bracket() -> None:
    app = CompletionTestApp(common_placeholders=["feature flag", "fedora"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> and <alpine> then <")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta._completion_kind == PLACEHOLDER_COMPLETION_KIND
        assert ta._placeholder_completion_trigger == "manual"
        assert _insertions(ta) == [
            "alpha",
            "alpine",
            "feature flag",
            "fedora",
        ]
        assert _sources(ta) == ["prompt", "prompt", "common", "common"]
        panel = app.query_one("#prompt-completion", Static)
        assert panel.border_subtitle == "<> prompt   ◆ saved  [^D] delete"
        rendered = panel.render().plain  # type: ignore[union-attr]
        assert "<> alpha" in rendered
        assert "◆  feature flag" in rendered


async def test_manual_bare_bracket_accepts_lone_prompt_before_saved_group() -> None:
    app = CompletionTestApp(common_placeholders=["feature flag", "fedora"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> and <")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == "Use <alpha> and <alpha>"
        assert ta._file_completion_active is False


async def test_ctrl_d_deletes_saved_placeholder_keeps_menu_open_and_toasts() -> None:
    app = CompletionTestApp(common_placeholders=["alpha", "alpine"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <")
        ta.cursor_location = (0, len(ta.text))

        with (
            patch("sase.ace.tui.util.io_async.schedule_persist") as schedule,
            patch.object(app, "notify") as notify,
        ):
            await pilot.press("ctrl+t", "ctrl+d")

        assert app.forgotten_common_placeholders == ["alpha"]
        assert app.common_placeholders() == ["alpine"]
        assert ta._file_completion_active is True
        assert _insertions(ta) == ["alpine"]
        notify.assert_called_once_with(
            "Deleted saved placeholder: <alpha>",
            severity="information",
            markup=False,
        )
        assert schedule.call_args.args[0] is app
        assert schedule.call_args.args[2] == "alpha"
        before = app.warm_common_requests
        schedule.call_args.kwargs["on_error"](OSError("disk full"))
        assert app.warm_common_requests == before + 1


async def test_ctrl_d_on_prompt_placeholder_only_explains_without_deleting() -> None:
    app = CompletionTestApp(common_placeholders=["beta"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> and <alpine> then <")
        ta.cursor_location = (0, len(ta.text))

        with (
            patch("sase.ace.tui.util.io_async.schedule_persist") as schedule,
            patch.object(app, "notify") as notify,
        ):
            await pilot.press("ctrl+t", "ctrl+d")

        assert _insertions(ta) == ["alpha", "alpine", "beta"]
        assert app.common_placeholders() == ["beta"]
        assert app.forgotten_common_placeholders == []
        schedule.assert_not_called()
        notify.assert_called_once_with(
            "This placeholder comes from the current prompt, not the saved list",
            severity="information",
            markup=False,
        )


async def test_ctrl_d_deleting_last_saved_placeholder_closes_menu() -> None:
    app = CompletionTestApp(common_placeholders=["alpha", "alpine"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <")
        ta.cursor_location = (0, len(ta.text))

        with patch("sase.ace.tui.util.io_async.schedule_persist") as schedule:
            await pilot.press("ctrl+t", "ctrl+d", "ctrl+d")

        assert app.forgotten_common_placeholders == ["alpha", "alpine"]
        assert ta._file_completion_active is False
        assert schedule.call_count == 2


async def test_ctrl_d_saved_placeholder_falls_back_to_local_row_removal() -> None:
    app = CompletionTestApp(common_placeholders=["alpha", "alpine"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <")
        ta.cursor_location = (0, len(ta.text))

        with (
            patch.object(
                CompletionTestApp,
                "forget_common_placeholder",
                None,
            ),
            patch("sase.ace.tui.util.io_async.schedule_persist"),
        ):
            await pilot.press("ctrl+t", "ctrl+d")

        assert ta._file_completion_active is True
        assert _insertions(ta) == ["alpine"]


async def test_manual_trigger_accepts_a_lone_saved_match_outright() -> None:
    app = CompletionTestApp(common_placeholders=["feature flag"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <fe")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == "Use <feature flag>"
        assert ta._file_completion_active is False


async def test_manual_trigger_accepts_lone_prompt_match_before_saved_group() -> None:
    app = CompletionTestApp(common_placeholders=["ctrl+e", "ctrl+e/y"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Rebind <ctrl+enter> and <ctrl+e")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == "Rebind <ctrl+enter> and <ctrl+enter>"
        assert ta._file_completion_active is False


async def test_manual_trigger_leaves_multiple_prompt_matches_open() -> None:
    app = CompletionTestApp(common_placeholders=["also saved"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        original = "Use <alpha> and <alpine> then <al"
        ta.load_text(original)
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == original
        assert ta._file_completion_active is True
        assert _insertions(ta) == ["alpha", "alpine", "also saved"]
        assert _sources(ta) == ["prompt", "prompt", "common"]


async def test_manual_trigger_leaves_multiple_saved_matches_open() -> None:
    app = CompletionTestApp(common_placeholders=["feature flag", "feature branch"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        original = "Use <fe"
        ta.load_text(original)
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == original
        assert ta._file_completion_active is True
        assert _insertions(ta) == ["feature flag", "feature branch"]
        assert _sources(ta) == ["common", "common"]


async def test_manual_trigger_accepts_lone_literal_prompt_match() -> None:
    app = CompletionTestApp(common_placeholders=["the feature", "ticket"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Fix `<the widget>` and update <t")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == "Fix `<the widget>` and update <the widget>"
        assert ta._file_completion_active is False


async def test_automatic_trigger_never_accepts_a_lone_match() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> then ")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("<", "a")

        assert ta.text == "Use <alpha> then <a"
        assert ta._file_completion_active is True
        assert _insertions(ta) == ["alpha"]


async def test_accepting_a_saved_candidate_closes_the_bracket_either_way() -> None:
    app = CompletionTestApp(common_placeholders=["feature flag"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> then <fe")
        ta.cursor_location = (0, len(ta.text))
        assert ta._try_auto_placeholder_completion() is True

        await pilot.press("enter")

        assert ta.text == "Use <alpha> then <feature flag>"
        assert ta.cursor_location == (0, len(ta.text))

        ta.load_text("Use <alpha> then <fe>")
        ta.cursor_location = (0, len(ta.text) - 1)
        assert ta._try_auto_placeholder_completion() is True

        await pilot.press("enter")

        assert ta.text == "Use <alpha> then <feature flag>"
        assert ta.cursor_location == (0, len(ta.text))


async def test_refresh_keeps_the_highlighted_saved_candidate_across_an_edit() -> None:
    app = CompletionTestApp(common_placeholders=["feature flag", "feature branch"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> then <f")
        ta.cursor_location = (0, len(ta.text))
        assert ta._try_auto_placeholder_completion() is True
        assert _insertions(ta) == ["feature flag", "feature branch"]

        await pilot.press("down")
        assert ta._file_completion_index == 1

        await pilot.press("e")

        assert _insertions(ta) == ["feature flag", "feature branch"]
        assert ta._file_completion_index == 1


async def test_cold_cache_menu_gains_the_saved_group_when_the_cache_warms() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> then <a")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("l")

        assert _insertions(ta) == ["alpha"]

        app.publish_common_placeholders(["also saved"])
        ta._refresh_file_completion_from_cursor()

        assert _insertions(ta) == ["alpha", "also saved"]
        assert _sources(ta) == ["prompt", "common"]


async def test_disabled_feature_reproduces_todays_placeholder_menu() -> None:
    # ``common_placeholder_count: 0`` publishes an empty list, so both the
    # automatic and the manual trigger fall back to prompt-local tags alone.
    app = CompletionTestApp(common_placeholders=[])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Use <alpha> and <alpine> then ")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("<")

        assert _insertions(ta) == ["alpha", "alpine"]
        assert _sources(ta) == ["prompt", "prompt"]

        await pilot.press("ctrl+t")

        assert _insertions(ta) == ["alpha", "alpine"]
        assert _sources(ta) == ["prompt", "prompt"]
