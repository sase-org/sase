"""Tests for type-aware xprompt argument completion in the prompt widget."""

from __future__ import annotations

from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp
from ._xprompt_arg_completion_helpers import (
    gh_entry,
    review_entry,
    rich_review_entry,
    seed_entries,
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

        seed_entries(ta, [review_entry()])
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

        seed_entries(ta, [review_entry()])
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


async def test_auto_keyword_arg_menu_uses_declaration_order_and_metadata() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#review(")
        ta.cursor_location = (0, len("#review("))
        seed_entries(ta, [rich_review_entry()])

        assert ta._try_auto_xprompt_arg_completion() is True

        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt_arg_name"
        assert ta._xprompt_arg_completion_trigger == "auto"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "path=",
            "enabled=",
            "count=",
            "label=",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render().plain
        assert panel.border_title == "#review args"
        assert str(panel.border_subtitle) == "file to review"
        assert rendered.index("path=") < rendered.index("enabled=")
        assert "path=     path" in rendered
        assert "enabled=  bool  =true" in rendered
        assert "turn on" in rendered


async def test_auto_keyword_arg_enter_submits_until_user_interacts() -> None:
    app = CompletionTestApp()
    submitted = 0
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        original_submit = ta.action_submit_prompt

        def record_submit() -> None:
            nonlocal submitted
            submitted += 1
            original_submit()

        ta.action_submit_prompt = record_submit  # type: ignore[method-assign]
        seed_entries(ta, [rich_review_entry()])
        ta.load_text("#review(")
        ta.cursor_location = (0, len("#review("))
        assert ta._try_auto_xprompt_arg_completion() is True

        await pilot.press("enter")
        assert submitted == 1
        assert ta.text == "#review("
        assert ta._file_completion_active is False

        ta.load_text("#review(")
        ta.cursor_location = (0, len("#review("))
        assert ta._try_auto_xprompt_arg_completion() is True
        await pilot.press("ctrl+g")
        assert submitted == 1
        assert ta.text == "#review(path="
        assert ta._insert_g_prefix_pending is False

        ta.load_text("#review(")
        ta.cursor_location = (0, len("#review("))
        assert ta._try_auto_xprompt_arg_completion() is True
        await pilot.press("e", "ctrl+g")

    assert submitted == 1
    assert ta.text == "#review(enabled="
    assert ta._file_completion_active is True
    assert ta._completion_kind == "xprompt_arg_value"
    assert ta._xprompt_arg_completion_trigger == "manual"


async def test_keyword_arg_selection_movement_hands_ctrl_g_to_menu() -> None:
    app = CompletionTestApp()
    submitted = 0
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        def record_submit() -> None:
            nonlocal submitted
            submitted += 1

        ta.action_submit_prompt = record_submit  # type: ignore[method-assign]
        seed_entries(ta, [rich_review_entry()])
        ta.load_text("#review(")
        ta.cursor_location = (0, len("#review("))
        assert ta._try_auto_xprompt_arg_completion() is True

        await pilot.press("ctrl+n", "ctrl+g", "ctrl+g")

    assert submitted == 0
    assert ta.text == "#review(enabled=true"
    assert ta._file_completion_active is False
    assert ta._insert_g_prefix_pending is False


async def test_keyword_arg_enter_submits_even_after_selection_moves() -> None:
    app = CompletionTestApp()
    submitted = 0
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        original_submit = ta.action_submit_prompt

        def record_submit() -> None:
            nonlocal submitted
            submitted += 1
            original_submit()

        ta.action_submit_prompt = record_submit  # type: ignore[method-assign]
        seed_entries(ta, [rich_review_entry()])
        ta.load_text("#review(")
        ta.cursor_location = (0, len("#review("))
        assert ta._try_auto_xprompt_arg_completion() is True

        await pilot.press("ctrl+n", "enter")

    assert submitted == 1
    assert ta.text == "#review("
    assert ta._file_completion_active is False


async def test_ctrl_n_and_ctrl_p_open_keyword_arg_menu_from_cold_start() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        entries = [gh_entry(), rich_review_entry()]
        seed_entries(ta, entries)
        seed_entries(ta, entries, project="sase")
        ta.load_text("#gh:sase #review(")
        ta.cursor_location = (0, len("#gh:sase #review("))

        await pilot.press("ctrl+n")
        assert ta.text == "#gh:sase #review("
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt_arg_name"
        assert ta._file_completion_index == 0
        assert ta._completion_selection_moved is True

        ta._clear_file_completion()
        ta.load_text("#gh:sase #review(")
        ta.cursor_location = (0, len("#gh:sase #review("))
        await pilot.press("ctrl+p")

    assert ta.text == "#gh:sase #review("
    assert ta._file_completion_active is True
    assert ta._completion_kind == "xprompt_arg_name"
    assert ta._file_completion_index == 3


async def test_accepting_keyword_names_chains_by_input_type(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "alpha.txt").write_text("x", encoding="utf-8")
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        seed_entries(ta, [rich_review_entry()])

        ta.load_text("#review(e")
        ta.cursor_location = (0, len("#review(e"))
        assert ta._try_file_completion_tab() is True
        assert ta.text == "#review(enabled="
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt_arg_value"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "true",
            "false",
        ]

        ta._clear_file_completion()
        ta.load_text("#review(p")
        ta.cursor_location = (0, len("#review(p"))
        assert ta._try_file_completion_tab() is True
        assert ta.text == "#review(path="
        assert ta._file_completion_active is True
        assert ta._completion_kind == "xprompt_arg_path"
        assert "alpha.txt" in {c.name for c in ta._file_completion_candidates}

        ta._clear_file_completion()
        ta.load_text("#review(l")
        ta.cursor_location = (0, len("#review(l"))
        assert ta._try_file_completion_tab() is True
        assert ta.text == "#review(label="
        assert ta._file_completion_active is False
        assert ta._active_xprompt_arg_hint is not None


async def test_parenthesized_arg_name_completion_skips_existing_names() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("#review(path=foo, e")
        ta.cursor_location = (0, len("#review(path=foo, e"))

        seed_entries(ta, [review_entry()])
        await pilot.press("ctrl+t")

    assert ta.text == "#review(path=foo, enabled="
    assert ta._file_completion_active is True
    assert ta._completion_kind == "xprompt_arg_value"
    assert [c.insertion for c in ta._file_completion_candidates] == ["true", "false"]


async def test_numeric_arg_keeps_hint_without_value_suggestions() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("#review(count=")
        ta.cursor_location = (0, len("#review(count="))

        seed_entries(ta, [review_entry()])
        assert ta._try_file_completion_tab() is True

    assert ta._file_completion_active is False
    assert ta._active_xprompt_arg_hint is not None
    assert bar._completion_visible is True


async def test_named_arg_completion_does_not_interfere_with_snippet_tab() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        assert ta._expand_snippet_template_at_range(
            "x=$1 y=$0",
            (0, 0),
            (0, 0),
            session_policy="nest",
        )
        assert ta.text == "x= y="
        assert ta.snippet_session_active

        seed_entries(ta, [review_entry()])
        await pilot.press("tab")

    assert ta.cursor_location == (0, len("x= y="))
    assert ta._file_completion_active is False
