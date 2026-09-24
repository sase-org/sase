"""Tests for ``@`` after ``%m:<model> `` opening the effort completion menu."""

from __future__ import annotations

import pytest
from textual.pilot import Pilot

from sase.ace.tui.widgets._model_effort_spacer import find_model_effort_spacer
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp
from .test_model_explicit_completion import ModelExplicitCompletionTestApp

EFFORTS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]


@pytest.mark.parametrize(
    "line",
    [
        "%m:gpt-6-sol ",
        "%model:@large ",
        "%m:codex/gpt-6-sol ",
        "fix it %m:opus ",
    ],
)
def test_helper_matches(line: str) -> None:
    assert find_model_effort_spacer(line, len(line)) == len(line) - 1


@pytest.mark.parametrize(
    "line",
    [
        "%m:gpt-6-sol@high ",
        "%m: ",
        "%m:opus  ",
        "%model(opus ",
        "`%m:opus ",
        "%effort:high ",
        "hello ",
    ],
)
def test_helper_rejects(line: str) -> None:
    assert find_model_effort_spacer(line, len(line)) is None


def test_helper_rejects_cursor_position() -> None:
    assert find_model_effort_spacer("%m:opus fix", 7) is None
    assert find_model_effort_spacer("%m:opus fix", 8) is None
    assert find_model_effort_spacer("%m:opus  x", 9) is None


def test_helper_allows_cursor_before_whitespace() -> None:
    assert find_model_effort_spacer("%m:opus \tfix", 8) == 7


async def _type(pilot: Pilot, text: str) -> None:
    for ch in text:
        await pilot.press("space" if ch == " " else ch)


def _insertions(ta: PromptTextArea) -> list[str]:
    return [c.insertion.removeprefix("@") for c in ta._file_completion_candidates]


async def test_typed_model_space_at_opens_effort_menu() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _type(pilot, "%m:gpt-6-sol @")
        assert ta.text == "%m:gpt-6-sol@"
        assert ta.cursor_location == (0, len(ta.text))
        assert ta._file_completion_active
        assert ta._completion_kind == "directive_arg"
        assert _insertions(ta) == EFFORTS


async def test_shortcut_then_at_opens_effort_menu() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _type(pilot, "==gpt")
        await pilot.press("ctrl+f")
        assert ta.text == "%m:gpt-5.6-sol "
        await pilot.press("@")
        assert ta.text == "%m:gpt-5.6-sol@"
        assert ta._file_completion_active
        assert ta._completion_kind == "directive_arg"


async def test_disabled_auto_menu_still_swallows_space() -> None:
    app = ModelExplicitCompletionTestApp(
        settings=PromptCompletionSettings(auto_directive_menu=False)
    )
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _type(pilot, "%m:gpt-6-sol @")
        assert ta.text == "%m:gpt-6-sol@"
        assert not ta._file_completion_active


async def test_plain_prose_at_keeps_space() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _type(pilot, "hello @")
        assert ta.text == "hello @"


async def test_undo_restores_space() -> None:
    app = ModelExplicitCompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await _type(pilot, "%m:gpt-6-sol @")
        ta.action_undo()
        assert ta.text == "%m:gpt-6-sol "
