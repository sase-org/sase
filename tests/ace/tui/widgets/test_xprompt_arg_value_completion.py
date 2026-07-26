"""Tests for type-aware xprompt argument completion in the prompt widget."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from unittest.mock import patch

from _pytest.monkeypatch import MonkeyPatch
from textual.widgets import Static

import sase.ace.tui.models.tribe_display as tribe_display
from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    AgentVcsWorkflow,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
)

from ._completion_helpers import CompletionTestApp


def _style_at(text: Any, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    base_style = getattr(text, "style", None)
    return str(base_style) if base_style else None


def _input_hint(
    name: str,
    type_: str,
    position: int,
    *,
    repeatable: bool = False,
) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=True,
        default_display=None,
        position=position,
        repeatable=repeatable,
    )


def _entry() -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name="review",
        insertion="#review",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(
            _input_hint("path", "path", 0),
            _input_hint("enabled", "bool", 1),
            _input_hint("count", "int", 2),
        ),
        content_preview=None,
    )


def _fork_entry() -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name="fork",
        insertion="#fork",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(_input_hint("names", "agent", 0, repeatable=True),),
        content_preview=None,
    )


def _gh_entry() -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name="gh",
        insertion="#gh",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(_input_hint("project", "word", 0),),
        content_preview=None,
    )


def _ask_entry() -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name="ask",
        insertion="#ask",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(_input_hint("body", "text", 0),),
        content_preview=None,
    )


def _agent_candidate(
    name: str,
    *,
    status: str = "RUNNING",
    vcs_tag: str = "#gh:sase",
    snippet: str = "Fix prompt completion",
    tribe: str | None = None,
    kind: Literal["agent", "family", "clan", "tribe"] = "agent",
    member_count: int | None = None,
    member_names: tuple[str, ...] = (),
) -> AgentCompletionCandidate:
    return AgentCompletionCandidate(
        name=name,
        label=name,
        status=status,
        kind=kind,
        member_count=member_count,
        aggregate_status=status if kind != "agent" else None,
        member_names=member_names,
        tribe=tribe,
        vcs_workflow=AgentVcsWorkflow(
            tag=vcs_tag,
            workflow_type="gh",
            project="sase",
            provider_display="GitHub",
            style="bold #5FD7FF",
        ),
        prompt_snippet=snippet,
    )


def _seed_entries(
    ta: PromptTextArea,
    entries: list[XPromptAssistEntry],
    project: str | None = None,
) -> None:
    ta._xprompt_arg_assist_entries_by_project[project] = entries


async def test_colon_path_arg_uses_existing_file_completion(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alpha.txt").write_text("x", encoding="utf-8")
    (tmp_path / "apple.txt").write_text("x", encoding="utf-8")
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#review:")
        ta.cursor_location = (0, len("#review:"))

        _seed_entries(ta, [_entry()])
        assert ta._try_file_completion_tab() is True

        assert ta.text == "#review:./a"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt_arg_path"
        assert {c.name for c in ta._file_completion_candidates} == {
            "alpha.txt",
            "apple.txt",
        }
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "xprompt path"


async def test_bool_named_arg_offers_true_false_values() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#review(enabled=)")
        ta.cursor_location = (0, len("#review(enabled="))

        _seed_entries(ta, [_entry()])
        await pilot.press("ctrl+t")
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt_arg_value"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "true",
            "false",
        ]
        await pilot.press("ctrl+l")

    assert ta.text == "#review(enabled=true)"
    assert ta._file_completion_active is False


async def test_fork_agent_arg_completion_replaces_value() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        _agent_candidate("coder")
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_fork_entry()]
        ta.load_text("#fork:co")
        ta.cursor_location = (0, len("#fork:co"))

        assert ta._try_file_completion_tab() is True

    assert ta.text == "#fork:coder"
    assert ta._file_completion_active is False


async def test_fork_agent_arg_completion_inserts_tribe_target() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        _agent_candidate("epic.builder", tribe="@epic")
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_fork_entry()]
        ta.load_text("#fork:@ep")
        ta.cursor_location = (0, len("#fork:@ep"))

        assert ta._try_file_completion_tab() is True

    assert ta.text == "#fork:@epic"
    assert ta._file_completion_active is False


async def test_repeatable_fork_completion_replaces_only_active_element() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        _agent_candidate("coder"),
        _agent_candidate("planner"),
        _agent_candidate("reviewer.@"),
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_fork_entry()]
        ta.load_text("#fork:planner,co")
        ta.cursor_location = (0, len("#fork:planner,co"))

        assert ta._try_file_completion_tab() is True

    assert ta.text == "#fork:planner,coder"


async def test_repeatable_fork_completion_filters_selected_parent_and_templates() -> (
    None
):
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        _agent_candidate("coder"),
        _agent_candidate("planner"),
        _agent_candidate("reviewer.@"),
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_fork_entry()]
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
        _agent_candidate("coder"),
        _agent_candidate("planner"),
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_fork_entry()]
        ta.load_text("#fork(co, planner)")
        ta.cursor_location = (0, len("#fork(co"))

        assert ta._try_file_completion_tab() is True

    assert ta.text == "#fork(coder, planner)"


async def test_fork_agent_arg_menu_renders_visible_agent_metadata() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        _agent_candidate("coder"),
        _agent_candidate("planner", status="DONE", snippet="Write the plan"),
    ]
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_fork_entry()]
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
        _agent_candidate(
            "@builders",
            kind="tribe",
            member_count=4,
            member_names=("review.alpha", "review.beta", "ship--code", "coder"),
        ),
        _agent_candidate(
            "review",
            kind="clan",
            member_count=2,
            member_names=("review.alpha", "review.beta"),
        ),
        _agent_candidate(
            "ship",
            kind="family",
            member_count=2,
            member_names=("ship--plan", "ship--code"),
        ),
        _agent_candidate("coder"),
    ]
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_fork_entry()]
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
        _agent_candidate(
            "@epic",
            kind="tribe",
            member_count=4,
            member_names=("epic.one",),
        ),
        _agent_candidate(
            "@review",
            kind="tribe",
            member_count=1,
            member_names=("review.one",),
        ),
    ]

    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_fork_entry()]
        ta.load_text("#fork:")
        ta.cursor_location = (0, len("#fork:"))
        assert ta._try_file_completion_tab() is True
        rendered = bar.query_one("#prompt-completion", Static).render()

    assert _style_at(rendered, rendered.plain.index("@epic")) == ("rgb(18,52,86) bold")
    assert _style_at(rendered, rendered.plain.index("tribe · 4")) == (
        "rgb(255,215,95) bold"
    )


async def test_fork_agent_arg_auto_menu_uses_xprompt_gate() -> None:
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        _agent_candidate("coder"),
        _agent_candidate("planner"),
    ]
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_fork_entry()]

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
        _agent_candidate("coder"),
        _agent_candidate("planner"),
    ]
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        # ``#gh:sase`` is a leading VCS tag, so the widget resolves project
        # ``sase`` and looks up assist entries under that key.
        entries = [_gh_entry(), _fork_entry()]
        _seed_entries(ta, entries)
        _seed_entries(ta, entries, project="sase")
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
        _agent_candidate("coder")
    ]
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [
            _ask_entry(),
            _fork_entry(),
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
        _agent_candidate("coder")
    ]
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta._xprompt_arg_assist_entries_by_project[None] = [_fork_entry()]

        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_xprompt_menu=False),
        ):
            for char in "#fork:":
                await pilot.press(char)

        assert ta.text == "#fork:"
        assert ta._file_completion_active is False


async def test_parenthesized_arg_name_completion_skips_existing_names() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#review(path=foo, e")
        ta.cursor_location = (0, len("#review(path=foo, e"))

        _seed_entries(ta, [_entry()])
        await pilot.press("ctrl+t")

    assert ta.text == "#review(path=foo, enabled="
    assert ta._file_completion_active is False


async def test_numeric_arg_keeps_hint_without_value_suggestions() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#review(count=")
        ta.cursor_location = (0, len("#review(count="))

        _seed_entries(ta, [_entry()])
        assert ta._try_file_completion_tab() is True

    assert ta._file_completion_active is False
    assert ta._active_xprompt_arg_hint is not None
    assert bar._completion_visible is True


async def test_named_arg_completion_does_not_interfere_with_snippet_tab() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        assert ta._expand_snippet_template_at_range("x=$1 y=$0", (0, 0), (0, 0))
        assert ta.text == "x= y="
        assert ta._snippet_tabstops

        _seed_entries(ta, [_entry()])
        await pilot.press("tab")

    assert ta.cursor_location == (0, len("x= y="))
    assert ta._file_completion_active is False
