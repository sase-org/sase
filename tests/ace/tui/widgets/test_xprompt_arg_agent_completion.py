"""Tests for agent-valued xprompt argument completion."""

from __future__ import annotations

from unittest.mock import patch

from _pytest.monkeypatch import MonkeyPatch
from textual.widgets import Static

import sase.ace.tui.models.tribe_display as tribe_display
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp
from ._xprompt_arg_completion_helpers import (
    agent_candidate,
    ask_entry,
    fork_entry,
    gh_entry,
    seed_entries,
    style_at,
)


async def test_fork_agent_arg_completion_replaces_value() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder")
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [fork_entry()]
        ta.load_text("#fork:co")
        ta.cursor_location = (0, len("#fork:co"))

        assert ta._try_file_completion_tab() is True

    assert ta.text == "#fork:coder"
    assert ta._file_completion_active is False


async def test_fork_agent_arg_completion_inserts_tribe_target() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("epic.builder", tribe="@epic")
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [fork_entry()]
        ta.load_text("#fork:@ep")
        ta.cursor_location = (0, len("#fork:@ep"))

        assert ta._try_file_completion_tab() is True

    assert ta.text == "#fork:@epic"
    assert ta._file_completion_active is False


async def test_repeatable_fork_completion_replaces_only_active_element() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder"),
        agent_candidate("planner"),
        agent_candidate("reviewer.@"),
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [fork_entry()]
        ta.load_text("#fork:planner,co")
        ta.cursor_location = (0, len("#fork:planner,co"))

        assert ta._try_file_completion_tab() is True

    assert ta.text == "#fork:planner,coder"


async def test_repeatable_fork_completion_filters_selected_parent_and_templates() -> (
    None
):
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder"),
        agent_candidate("planner"),
        agent_candidate("reviewer.@"),
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [fork_entry()]
        ta.load_text("#fork(planner, ")
        ta.cursor_location = (0, len("#fork(planner, "))

        assert ta._try_file_completion_tab() is True
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == [
            "coder",
            "reviewer.@",
        ]


async def test_repeatable_fork_completion_replaces_earlier_parenthesized_element() -> (
    None
):
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder"),
        agent_candidate("planner"),
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [fork_entry()]
        ta.load_text("#fork(co, planner)")
        ta.cursor_location = (0, len("#fork(co"))

        assert ta._try_file_completion_tab() is True

    assert ta.text == "#fork(coder, planner)"


async def test_fork_agent_arg_menu_renders_visible_agent_metadata() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder"),
        agent_candidate("planner", status="DONE", snippet="Write the plan"),
    ]
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [fork_entry()]
        ta.load_text("#fork:")
        ta.cursor_location = (0, len("#fork:"))

        assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render().plain
        assert panel.border_title == "fork targets"
        assert "coder" in rendered
        assert "#gh:sase" in rendered
        assert "Fix prompt completion" in rendered


async def test_fork_target_menu_renders_all_four_aligned_kinds() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate(
            "@builders",
            kind="tribe",
            member_count=4,
            member_names=("review.alpha", "review.beta", "ship--code", "coder"),
        ),
        agent_candidate(
            "review",
            kind="clan",
            member_count=2,
            member_names=("review.alpha", "review.beta"),
        ),
        agent_candidate(
            "ship",
            kind="family",
            member_count=2,
            member_names=("ship--plan", "ship--code"),
        ),
        agent_candidate("coder"),
    ]
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [fork_entry()]
        ta.load_text("#fork:")
        ta.cursor_location = (0, len("#fork:"))

        assert ta._try_file_completion_tab() is True
        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render().plain

    assert panel.border_title == "fork targets"
    assert "@ @builders" in rendered and "tribe · 4" in rendered
    assert "C review" in rendered and "clan · 2" in rendered
    assert "F ship" in rendered and "family · 2" in rendered
    assert "● coder" in rendered and "#gh:sase" in rendered


async def test_fork_tribe_completion_colors_only_the_identity(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {"epic": {"color": "#123456"}}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("completion-tribe-color",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate(
            "@epic",
            kind="tribe",
            member_count=4,
            member_names=("epic.one",),
        ),
        agent_candidate(
            "@review",
            kind="tribe",
            member_count=1,
            member_names=("review.one",),
        ),
    ]

    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [fork_entry()]
        ta.load_text("#fork:")
        ta.cursor_location = (0, len("#fork:"))
        assert ta._try_file_completion_tab() is True
        rendered = bar.query_one("#prompt-completion", Static).render()

    assert style_at(rendered, rendered.plain.index("@epic")) == ("rgb(18,52,86) bold")
    assert style_at(rendered, rendered.plain.index("tribe · 4")) == (
        "rgb(255,215,95) bold"
    )


async def test_fork_agent_arg_auto_menu_uses_xprompt_gate() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder"),
        agent_candidate("planner"),
    ]
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [fork_entry()]

        for char in "#fork:":
            await pilot.press(char)

        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt_arg_agent"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "coder",
            "planner",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "fork targets"


async def test_fork_agent_arg_completion_after_earlier_xprompt_reference() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder"),
        agent_candidate("planner"),
    ]
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        # ``#gh:sase`` is a leading VCS tag, so the widget resolves project
        # ``sase`` and looks up assist entries under that key.
        entries = [gh_entry(), fork_entry()]
        seed_entries(ta, entries)
        seed_entries(ta, entries, project="sase")
        ta.load_text("#gh:sase #fork:")
        ta.cursor_location = (0, len("#gh:sase #fork:"))

        # Ctrl+T opens the fork-agent menu for the trailing ``#fork:`` rather
        # than falling through to file history, even though the earlier
        # ``#gh:sase`` reference is scanned first.
        assert ta._try_file_completion_tab() is True
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt_arg_agent"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "coder",
            "planner",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "fork targets"


async def test_double_colon_free_text_does_not_open_fork_agent_menu() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder")
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [
            ask_entry(),
            fork_entry(),
        ]
        ta.load_text("#ask:: after #fork:")
        ta.cursor_location = (0, len("#ask:: after #fork:"))

        # Ctrl+T may fall through to xprompt-name completion, but it must never
        # open the fork-agent menu inside the double-colon free-text body.
        ta._try_file_completion_tab()
        assert ta._completion_kind != "xprompt_arg_agent"


async def test_fork_agent_arg_auto_menu_respects_disabled_xprompt_gate() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        agent_candidate("coder")
    ]
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [fork_entry()]

        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_xprompt_menu=False),
        ):
            for char in "#fork:":
                await pilot.press(char)

        assert ta.text == "#fork:"
        assert ta._file_completion_active is False
