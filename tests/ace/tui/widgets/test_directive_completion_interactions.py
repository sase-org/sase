"""Tests for prompt directive completion UI interactions."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED

from ._completion_helpers import CompletionTestApp
from ._directive_completion_helpers import (
    MODEL_CATALOG_PATCH,
    agent_candidate,
    model_entries,
    model_entries_with_providers,
)


async def test_ctrl_t_at_percent_opens_directive_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("%")
        ta.cursor_location = (0, 1)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive"
        assert panel.border_title == "directives"
        assert (
            "choose a model and optional launch-family alias overrides"
            in panel.render().plain
        )


async def test_ctrl_t_at_partial_directive_inserts_single_candidate() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%mo")
        ta.cursor_location = (0, 3)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model"
    assert ta._file_completion_active is False


async def test_ctrl_t_at_alias_partial_inserts_canonical_directive() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%m")
        ta.cursor_location = (0, 2)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model"
    assert ta._file_completion_active is False


async def test_multi_candidate_directive_completion_accepts_ctrl_l() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%a")
        ta.cursor_location = (0, 2)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            await pilot.press("ctrl+t")
            assert ta._file_completion_active is True
            await pilot.press("down")
            selected = ta._file_completion_candidates[
                ta._file_completion_index
            ].insertion
            await pilot.press("ctrl+l")

    assert ta.text == selected
    assert ta._file_completion_active is False


async def test_percent_partial_auto_opens_directive_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")
        assert ta.text == "%"
        assert ta._file_completion_active is True

        await pilot.press("m")

        # A single ``%m`` -> ``%model`` match keeps the menu open but never
        # auto-accepts: the text stays ``%m`` until the user accepts explicitly.
        assert ta.text == "%m"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive"
        assert [c.insertion for c in ta._file_completion_candidates] == ["%model"]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "directives"


async def test_colon_after_effort_auto_opens_directive_value_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        for char in "%effort:":
            await pilot.press(char)

        assert ta.text == "%effort:"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive_arg"
        assert [c.insertion for c in ta._file_completion_candidates] == list(
            EFFORT_LEVELS_ORDERED
        )
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "directive values"
        assert "reasoning effort" in panel.render().plain


async def test_colon_after_model_auto_opens_model_value_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        with patch(MODEL_CATALOG_PATCH, return_value=model_entries()):
            for char in "%model:":
                await pilot.press(char)

        assert ta.text == "%model:"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive_arg"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "claude-fable-5",
            "gpt-5.6-sol",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "%model values"
        assert "Claude" in panel.render().plain
        assert panel.border_subtitle.replace(r"\[", "[") == "[@] model aliases"


async def test_colon_after_wait_auto_opens_wait_targets_panel() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        AgentCompletionCandidate("@builders", "builders", "RUNNING", kind="tribe"),
        AgentCompletionCandidate("review", "review", "RUNNING", kind="clan"),
        AgentCompletionCandidate("ship", "ship", "RUNNING", kind="family"),
        AgentCompletionCandidate("coder", "coder", "RUNNING"),
    ]
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        for char in "%wait:":
            await pilot.press(char)

        assert ta._completion_kind == "directive_arg"
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == [
            "priority=",
            "runners=",
            "time=",
            "@builders",
            "review",
            "ship",
            "coder",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "wait targets"


async def test_directive_arg_refresh_narrows_widens_and_dismisses() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        for char in "%effort:":
            await pilot.press(char)
        await pilot.press("h")

        assert ta.text == "%effort:h"
        assert [c.insertion for c in ta._file_completion_candidates] == ["high"]

        await pilot.press("backspace")
        assert ta.text == "%effort:"
        assert [c.insertion for c in ta._file_completion_candidates] == list(
            EFFORT_LEVELS_ORDERED
        )

        await pilot.press("space")
        assert ta.text == "%effort: "
        assert ta._file_completion_active is False


async def test_directive_arg_completion_accepts_selection() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%auto:")
        ta.cursor_location = (0, len("%auto:"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            await pilot.press("ctrl+t")
            assert ta._file_completion_active is True
            assert ta._completion_kind == "directive_arg"
            await pilot.press("down")
            selected = ta._file_completion_candidates[
                ta._file_completion_index
            ].insertion
            await pilot.press("ctrl+l")

    assert selected == "tale"
    assert ta.text == "%auto:tale"
    assert ta._file_completion_active is False


async def test_directive_arg_completion_replaces_only_partial_value() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%effort:h")
        ta.cursor_location = (0, len("%effort:h"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%effort:high"
    assert ta._file_completion_active is False


async def test_wait_arg_completion_replaces_only_active_fragment() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder")
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%wait:planner, co")
        ta.cursor_location = (0, len("%wait:planner, co"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%wait:planner, coder"
    assert ta._file_completion_active is False


async def test_wait_arg_completion_excludes_selected_agent_and_groups() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        AgentCompletionCandidate("@builders", "builders", "RUNNING", kind="tribe"),
        AgentCompletionCandidate("review", "review", "RUNNING", kind="clan"),
        AgentCompletionCandidate("ship", "ship", "RUNNING", kind="family"),
        AgentCompletionCandidate("planner", "planner", "RUNNING"),
        AgentCompletionCandidate("coder", "coder", "RUNNING"),
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%wait(planner, , @builders, review)")
        ta.cursor_location = (0, len("%wait(planner, "))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == [
            "priority=",
            "runners=",
            "time=",
            "ship",
            "coder",
        ]


async def test_wait_arg_completion_excludes_selected_keyword_in_paren_form() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("planner"),
        agent_candidate("coder"),
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "%wait(time=5m, )"
        ta.load_text(text)
        ta.cursor_location = (0, text.index(")"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["priority=", "runners=", "planner", "coder"]


async def test_wait_arg_completion_excludes_selected_keyword_to_cursor_right() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("planner"),
        agent_candidate("coder"),
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "%wait:, runners=1, Coder"
        ta.load_text(text)
        ta.cursor_location = (0, len("%wait:"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["priority=", "time=", "planner"]


async def test_wait_arg_completion_inserts_tribe_target() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("epic.builder", tribe="@epic")
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%w:@ep")
        ta.cursor_location = (0, len("%w:@ep"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%w:@epic"
    assert ta._file_completion_active is False


async def test_prose_comma_after_wait_directive_does_not_reopen_panel() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder")
    ]
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%w:coder some prose")
        ta.cursor_location = (0, len("%w:coder some prose"))

        await pilot.press(",")

        assert ta.text == "%w:coder some prose,"
        assert ta._file_completion_active is False


async def test_real_comma_after_wait_agent_reopens_panel() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder"),
        agent_candidate("planner"),
    ]
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%w:coder")
        ta.cursor_location = (0, len("%w:coder"))

        await pilot.press(",")

        assert ta.text == "%w:coder,"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive_arg"


async def test_wait_paren_completion_preserves_later_arguments() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder")
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "%wait(planner, co, time=5m)"
        ta.load_text(text)
        ta.cursor_location = (0, text.index(", time"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%wait(planner, coder, time=5m)"
    assert ta._file_completion_active is False


async def test_model_arg_completion_replaces_partial_with_canonical_value() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%model:fa")
        ta.cursor_location = (0, len("%model:fa"))

        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(MODEL_CATALOG_PATCH, return_value=model_entries()),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model:claude-fable-5"
    assert ta._file_completion_active is False


async def test_model_provider_row_acceptance_drills_down_to_scoped_menu() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%model:cl")
        ta.cursor_location = (0, len("%model:cl"))

        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(MODEL_CATALOG_PATCH, return_value=model_entries_with_providers()),
        ):
            await pilot.press("ctrl+t")
            assert [c.insertion for c in ta._file_completion_candidates] == [
                "claude-fable-5",
                "claude/",
            ]
            await pilot.press("down")
            await pilot.press("ctrl+l")

    assert ta.text == "%model:claude/"
    assert ta._file_completion_active is True
    assert [c.insertion for c in ta._file_completion_candidates] == [
        "claude/claude-fable-5"
    ]


async def test_ctrl_t_unique_model_provider_row_drills_down() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%model:cod")
        ta.cursor_location = (0, len("%model:cod"))

        with (
            patch.object(
                type(ta),
                "_ace_app",
                new_callable=lambda: property(lambda _s: app),
            ),
            patch(MODEL_CATALOG_PATCH, return_value=model_entries_with_providers()),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model:codex/"
    assert ta._file_completion_active is True
    assert [c.insertion for c in ta._file_completion_candidates] == [
        "codex/gpt-5.6-sol"
    ]


async def test_model_at_effort_completion_replaces_only_suffix() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%model:opus@xh")
        ta.cursor_location = (0, len("%model:opus@xh"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model:opus@xhigh"
    assert ta._file_completion_active is False


async def test_directive_arg_auto_menu_uses_directive_gate() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_directive_menu=False),
        ):
            for char in "%auto:":
                await pilot.press(char)

        assert ta.text == "%auto:"
        assert ta._file_completion_active is False


async def test_bare_percent_auto_opens_directive_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")

        assert ta.text == "%"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive"
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "directives"


async def test_bare_percent_auto_menu_uses_directive_gate() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_directive_menu=False),
        ):
            await pilot.press("%")

        assert ta.text == "%"
        assert ta._file_completion_active is False


async def test_bare_percent_then_brace_clears_menu_and_inserts_alt_pair() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")
        assert ta._file_completion_active is True

        await pilot.press("{")

        assert ta.text == "%{  }"
        assert ta._file_completion_active is False


async def test_unknown_directive_does_not_show_placeholder() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")
        await pilot.press("z")

        assert ta.text == "%z"
        assert ta._file_completion_active is False
        assert ta._file_completion_candidates == []


async def test_directive_invalid_context_does_not_auto_open() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("word")
        ta.cursor_location = (0, 4)

        await pilot.press("%")
        await pilot.press("m")

        assert ta.text == "word%m"
        assert ta._file_completion_active is False


async def test_directive_typing_narrows_deleting_widens_and_space_dismisses() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")
        await pilot.press("a")
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "%alt",
            "%auto",
        ]

        await pilot.press("u")
        assert ta.text == "%au"
        assert [c.insertion for c in ta._file_completion_candidates] == ["%auto"]

        await pilot.press("backspace")
        assert ta.text == "%a"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "%alt",
            "%auto",
        ]

        await pilot.press("space")
        assert ta.text == "%a "
        assert ta._file_completion_active is False
