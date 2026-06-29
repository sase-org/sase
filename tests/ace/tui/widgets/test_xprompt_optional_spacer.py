"""Tests for the optional-only xprompt trailing-spacer ``:`` rewrite.

When an optional-only xprompt completes to ``#name `` (a deliberate trailing
spacer), typing ``:`` immediately afterward should replace the spacer so the
prompt becomes ``#name:`` without a manual ``<backspace>``.  No-input xprompts
and any intervening keystroke must leave the spacer untouched.
"""

from __future__ import annotations

from unittest.mock import patch

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
    has_only_optional_inputs,
)

from ._completion_helpers import CompletionTestApp


def _input(
    name: str,
    type_: str,
    *,
    required: bool,
    position: int = 0,
) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=required,
        default_display=None,
        position=position,
    )


def _entry(
    name: str,
    *,
    prefix: str = "#",
    inputs: tuple[XPromptInputHint, ...] = (),
) -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name=name,
        insertion=f"{prefix}{name}",
        reference_prefix=prefix,
        kind="xprompt",
        input_signature=None,
        inputs=inputs,
        content_preview=None,
    )


def _optional_entry(name: str = "optional") -> XPromptAssistEntry:
    """An xprompt whose single input is optional (optional-only)."""
    return _entry(name, inputs=(_input("topic", "word", required=False),))


def _optional_agent_entry(name: str = "fork") -> XPromptAssistEntry:
    """An optional-only xprompt whose next argument has agent completions."""
    return _entry(name, inputs=(_input("name", "agent", required=False),))


def _agent_candidate(
    name: str,
    *,
    status: str = "RUNNING",
    vcs_tag: str = "#gh:sase",
    snippet: str = "Fix prompt completion",
) -> AgentCompletionCandidate:
    return AgentCompletionCandidate(
        name=name,
        label=name,
        status=status,
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


def _compute_soft_now(ta: PromptTextArea) -> None:
    ta._clear_soft_completion(cancel_timer=True)
    ta._prompt_completion_generation += 1
    ta._fire_prompt_completion_timer(
        ta._prompt_completion_generation,
        ta.text,
        ta._absolute_offset(ta.cursor_location),
    )


def test_has_only_optional_inputs_predicate() -> None:
    assert has_only_optional_inputs(_optional_entry()) is True
    # No inputs -> not optional-only (no argument to introduce).
    assert has_only_optional_inputs(_entry("plain")) is False
    # A required input present -> not optional-only.
    assert (
        has_only_optional_inputs(
            _entry("mixed", inputs=(_input("path", "path", required=True),))
        )
        is False
    )


async def test_optional_only_ctrl_t_single_candidate_then_colon() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, [_optional_entry()])
        await pilot.press("ctrl+t")

        assert ta.text == "#optional "
        assert ta._pending_optional_spacer is not None

        await pilot.press(":")

    assert ta.text == "#optional:"
    assert ta._pending_optional_spacer is None


async def test_optional_only_ctrl_t_before_punctuation_records_no_spacer() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("(#o)")
        ta.cursor_location = (0, len("(#o"))
        _seed_entries(ta, [_optional_entry()])
        await pilot.press("ctrl+t")

        assert ta.text == "(#optional)"
        assert ta.cursor_location == (0, len("(#optional"))
        assert ta._pending_optional_spacer is None

        await pilot.press(":")

    assert ta.text == "(#optional:)"
    assert ta._pending_optional_spacer is None


async def test_optional_only_panel_accept_then_colon() -> None:
    entries = [_optional_entry(), _entry("ship")]
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        _seed_entries(ta, entries)
        # Two candidates -> the panel opens; ``enter`` accepts the first.
        await pilot.press("ctrl+t")
        await pilot.press("enter")

        assert ta.text == "#optional "
        assert ta._pending_optional_spacer is not None

        await pilot.press(":")

    assert ta.text == "#optional:"


async def test_optional_agent_spacer_colon_opens_agent_menu() -> None:
    entry = _optional_agent_entry()
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        _agent_candidate("coder"),
        _agent_candidate("planner"),
    ]
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#f")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, [entry])
        await pilot.press("ctrl+t")

        assert ta.text == "#fork "
        assert ta._pending_optional_spacer is not None

        await pilot.press(":")

    assert ta.text == "#fork:"
    assert ta._pending_optional_spacer is None
    assert ta._file_completion_active is True
    assert ta._completion_kind == "xprompt_arg_agent"
    assert [c.insertion for c in ta._file_completion_candidates] == [
        "coder",
        "planner",
    ]


async def test_optional_agent_spacer_colon_respects_disabled_auto_menu() -> None:
    entry = _optional_agent_entry()
    app = CompletionTestApp()
    app.visible_agent_completion_candidates = lambda: [  # type: ignore[attr-defined]
        _agent_candidate("coder"),
    ]
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#f")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, [entry])
        await pilot.press("ctrl+t")

        assert ta.text == "#fork "
        assert ta._pending_optional_spacer is not None

        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_xprompt_menu=False),
        ):
            await pilot.press(":")

    assert ta.text == "#fork:"
    assert ta._pending_optional_spacer is None
    assert ta._file_completion_active is False


async def test_optional_only_soft_completion_then_colon() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _seed_entries(ta, [_optional_entry()])
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        _compute_soft_now(ta)

        await pilot.press("ctrl+l")
        assert ta.text == "#optional "
        assert ta._pending_optional_spacer is not None

        await pilot.press(":")

    assert ta.text == "#optional:"


async def test_optional_only_selector_smart_insertion_then_colon() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)

        # The '#' from the '#@' trigger is already present ('@' was prevented).
        ta.load_text("#")
        ta.cursor_location = (0, 1)

        inserted = bar.insert_snippet_at_target(
            ta, ta.id or "", ((0, 0), (0, 1)), "optional", entry=_optional_entry()
        )
        await pilot.pause()

        assert inserted is True
        assert ta.text == "#optional "
        assert ta._pending_optional_spacer is not None

        await pilot.press(":")

    assert ta.text == "#optional:"


async def test_no_input_xprompt_colon_is_not_rewritten() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#p")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, [_entry("plain")])
        await pilot.press("ctrl+t")

        assert ta.text == "#plain "
        assert ta._pending_optional_spacer is None

        await pilot.press(":")

    # The trailing space survives; the colon simply inserts after it.
    assert ta.text == "#plain :"


async def test_intervening_keystroke_clears_pending_spacer() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        _seed_entries(ta, [_optional_entry()])
        await pilot.press("ctrl+t")

        assert ta.text == "#optional "
        assert ta._pending_optional_spacer is not None

        # Any other character cancels the one-shot spacer rewrite.
        await pilot.press("x")
        assert ta._pending_optional_spacer is None

        await pilot.press(":")

    assert ta.text == "#optional x:"
