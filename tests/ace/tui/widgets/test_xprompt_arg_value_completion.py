"""Tests for type-aware xprompt argument completion in the prompt widget."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from _pytest.monkeypatch import MonkeyPatch
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
)

from ._completion_helpers import CompletionTestApp


def _input_hint(name: str, type_: str, position: int) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=True,
        default_display=None,
        position=position,
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

        with patch(
            "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
            return_value=[_entry()],
        ):
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

        with patch(
            "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
            return_value=[_entry()],
        ):
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


async def test_parenthesized_arg_name_completion_skips_existing_names() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#review(path=foo, e")
        ta.cursor_location = (0, len("#review(path=foo, e"))

        with patch(
            "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
            return_value=[_entry()],
        ):
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

        with patch(
            "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
            return_value=[_entry()],
        ):
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

        with patch(
            "sase.ace.tui.widgets.prompt_text_area.build_xprompt_assist_entries",
            return_value=[_entry()],
        ):
            await pilot.press("tab")

    assert ta.cursor_location == (0, len("x= y="))
    assert ta._file_completion_active is False
