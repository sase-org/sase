"""Tests for prompt ``%wait`` directive completion UI interactions."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp
from ._directive_completion_helpers import agent_candidate, directive_arg_metadata


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
            "@builders",
            "review",
            "ship",
            "coder",
        ]
        assert all(
            not candidate.insertion.endswith("=")
            for candidate in ta._file_completion_candidates
        )
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "wait targets"


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
            "agent=",
            "bead=",
            "priority=",
            "proc=",
            "runners=",
            "time=",
            "unit=",
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
        ] == [
            "agent=",
            "bead=",
            "priority=",
            "proc=",
            "runners=",
            "unit=",
            "planner",
            "coder",
        ]


async def test_wait_arg_completion_excludes_selected_keyword_to_cursor_right() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("planner"),
        agent_candidate("coder"),
        agent_candidate("reviewer"),
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
        ] == ["planner", "reviewer"]


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


async def test_wait_paren_empty_clause_offers_documented_bead_keyword() -> None:
    """Regression for `%w(..., )`: bead= is a documented wait keyword row."""
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder")
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "%w(time=5m, )"
        ta.load_text(text)
        ta.cursor_location = (0, text.index(")"))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

        insertions = [
            candidate.insertion for candidate in ta._file_completion_candidates
        ]
        assert insertions[:5] == ["agent=", "bead=", "priority=", "proc=", "runners="]
        bead = ta._file_completion_candidates[1]
        assert directive_arg_metadata(bead).description == (
            "Wait until this bead is closed"
        )


async def test_wait_bead_value_uses_warm_inventory_without_blocking() -> None:
    app = CompletionTestApp()
    app.wait_bead_inventory = lambda: (  # type: ignore[attr-defined]
        (
            {
                "id": "sase-a",
                "title": "Active bug",
                "status": "in_progress",
                "type_label": "task",
                "updated_at": "2026-08-20T12:00:00Z",
            },
            {
                "id": "sase-b",
                "title": "Open follow-up",
                "status": "open",
                "type_label": "task",
                "updated_at": "2026-08-19T12:00:00Z",
            },
        ),
        True,
    )
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        text = "%wait(bead="
        ta.load_text(text)
        ta.cursor_location = (0, len(text))

        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["sase-a", "sase-b"]
        bar = app.query_one(PromptInputBar)
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "beads"
        assert "Active bug" in panel.render().plain
