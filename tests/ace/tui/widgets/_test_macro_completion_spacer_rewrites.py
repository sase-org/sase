"""Tests for macro completion spacer behavior.

Private implementation module; import test names from the legacy facade.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from sase.ace.tui.agent_completion import AgentCompletionCandidate, AgentVcsWorkflow
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.macro_arg_assist import (
    MacroAssistEntry,
    MacroInputHint,
    has_no_required_inputs,
    has_only_optional_inputs,
)

from ._completion_helpers import CompletionTestApp
from ._macro_completion_spacer_helpers import input_hint, macro_entry, seed_entries


def _optional_entry(name: str = "optional") -> MacroAssistEntry:
    """A macro whose single input is optional (optional-only)."""
    return macro_entry(name, inputs=(input_hint("topic", "word", required=False),))


def _optional_agent_entry(name: str = "fork") -> MacroAssistEntry:
    """An optional-only macro whose next argument has agent completions."""
    return macro_entry(name, inputs=(input_hint("name", "agent", required=False),))


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


async def _compute_soft_now(ta: PromptTextArea) -> None:
    await asyncio.sleep(0)
    ta._clear_soft_completion(cancel_timer=True)
    ta._prompt_completion_generation += 1
    ta._set_soft_completion(ta._build_current_soft_completion())


def test_no_required_and_optional_only_input_predicates() -> None:
    assert has_no_required_inputs(macro_entry("plain")) is True
    assert has_no_required_inputs(_optional_entry()) is True
    assert has_only_optional_inputs(_optional_entry()) is True
    # No inputs are eligible for comma tightening, but not colon arguments.
    assert has_only_optional_inputs(macro_entry("plain")) is False
    required = macro_entry(
        "mixed",
        inputs=(input_hint("path", "path", required=True),),
    )
    assert has_no_required_inputs(required) is False
    assert has_only_optional_inputs(required) is False


async def test_optional_only_ctrl_t_single_candidate_then_colon() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_entry()])
        await pilot.press("ctrl+t")

        assert ta.text == "#optional "
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press(":")

    assert ta.text == "#optional:"
    assert ta._pending_macro_completion_spacer is None


async def test_no_input_ctrl_t_single_candidate_then_comma() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#p")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [macro_entry("plain")])
        await pilot.press("ctrl+t")

        pending = ta._pending_macro_completion_spacer
        assert ta.text == "#plain "
        assert pending is not None
        assert pending.has_optional_inputs is False

        await pilot.press(",")

    assert ta.text == "#plain,"
    assert ta.cursor_location == (0, len("#plain,"))
    assert ta._pending_macro_completion_spacer is None


async def test_optional_only_ctrl_t_single_candidate_then_comma() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_entry()])
        await pilot.press("ctrl+t")

        pending = ta._pending_macro_completion_spacer
        assert ta.text == "#optional "
        assert pending is not None
        assert pending.has_optional_inputs is True

        await pilot.press(",")

    assert ta.text == "#optional,"
    assert ta.cursor_location == (0, len("#optional,"))
    assert ta._pending_macro_completion_spacer is None


async def test_completion_before_punctuation_records_no_spacer() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("(#o)")
        ta.cursor_location = (0, len("(#o"))
        seed_entries(ta, [_optional_entry()])
        await pilot.press("ctrl+t")

        assert ta.text == "(#optional)"
        assert ta.cursor_location == (0, len("(#optional"))
        assert ta._pending_macro_completion_spacer is None

        await pilot.press(",")

    assert ta.text == "(#optional,)"
    assert ta._pending_macro_completion_spacer is None


async def test_completion_panel_accept_then_comma() -> None:
    entries = [_optional_entry(), macro_entry("ship")]
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#")
        ta.cursor_location = (0, 1)
        seed_entries(ta, entries)
        # Two candidates -> the panel opens; ``ctrl+f`` accepts the first.
        await pilot.press("ctrl+t")
        await pilot.press("ctrl+f")

        assert ta.text == "#optional "
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press(",")

    assert ta.text == "#optional,"
    assert ta._pending_macro_completion_spacer is None


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
        seed_entries(ta, [entry])
        await pilot.press("ctrl+t")

        assert ta.text == "#fork "
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press(":")

    assert ta.text == "#fork:"
    assert ta._pending_macro_completion_spacer is None
    assert ta._file_completion_active is True
    assert ta._completion_kind == "macro_arg_agent"
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
        seed_entries(ta, [entry])
        await pilot.press("ctrl+t")

        assert ta.text == "#fork "
        assert ta._pending_macro_completion_spacer is not None

        with patch.object(
            type(ta),
            "_prompt_completion_settings",
            return_value=PromptCompletionSettings(auto_macro_menu=False),
        ):
            await pilot.press(":")

    assert ta.text == "#fork:"
    assert ta._pending_macro_completion_spacer is None
    assert ta._file_completion_active is False


async def test_no_input_soft_completion_then_comma() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        seed_entries(ta, [macro_entry("plain")])
        ta.load_text("#p")
        ta.cursor_location = (0, 2)
        await _compute_soft_now(ta)

        await pilot.press("ctrl+l")
        assert ta.text == "#plain "
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press(",")

    assert ta.text == "#plain,"
    assert ta._pending_macro_completion_spacer is None


async def test_optional_only_selector_smart_insertion_then_comma() -> None:
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
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press(",")

    assert ta.text == "#optional,"
    assert ta._pending_macro_completion_spacer is None


async def test_no_input_macro_colon_is_not_rewritten() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#p")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [macro_entry("plain")])
        await pilot.press("ctrl+t")

        assert ta.text == "#plain "
        assert ta._pending_macro_completion_spacer is not None

        await pilot.press(":")

    # The trailing space survives; the colon simply inserts after it.
    assert ta.text == "#plain :"
    assert ta._pending_macro_completion_spacer is None


async def test_intervening_keystroke_clears_pending_spacer() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_entry()])
        await pilot.press("ctrl+t")

        assert ta.text == "#optional "
        assert ta._pending_macro_completion_spacer is not None

        # Any other character cancels the one-shot spacer rewrite.
        await pilot.press("x")
        assert ta._pending_macro_completion_spacer is None

        await pilot.press(",")

    assert ta.text == "#optional x,"


async def test_cursor_movement_invalidates_later_comma_rewrite() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_entry()])
        await pilot.press("ctrl+t")

        assert ta._pending_macro_completion_spacer is not None
        ta.cursor_location = (0, len("#optional"))
        await pilot.press(",")

    assert ta.text == "#optional, "
    assert ta._pending_macro_completion_spacer is None


async def test_changed_reference_invalidates_later_comma_rewrite() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_entry()])
        await pilot.press("ctrl+t")

        assert ta._pending_macro_completion_spacer is not None
        ta.load_text("#changedx ")
        ta.cursor_location = (0, len("#changedx "))
        await pilot.press(",")

    assert ta.text == "#changedx ,"
    assert ta._pending_macro_completion_spacer is None


async def test_absent_spacer_invalidates_later_comma_rewrite() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#o")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [_optional_entry()])
        await pilot.press("ctrl+t")

        assert ta._pending_macro_completion_spacer is not None
        spacer_offset = len("#optional")
        ta._replace_absolute_range(spacer_offset, spacer_offset + 1, "x")
        await pilot.press(",")

    assert ta.text == "#optionalx,"
    assert ta._pending_macro_completion_spacer is None


async def test_required_text_completion_does_not_record_pending_spacer() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        entry = macro_entry(
            "body",
            inputs=(input_hint("body", "text", required=True),),
        )
        ta.load_text("#b")
        ta.cursor_location = (0, 2)
        seed_entries(ta, [entry])
        await pilot.press("ctrl+t")

        assert ta.text == "#body:: "
        assert ta._pending_macro_completion_spacer is None
        await pilot.press(",")

    assert ta.text == "#body:: ,"
