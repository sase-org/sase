"""Tests for prompt directive completion."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.directive_completion import (
    DirectiveCompletionMetadata,
    build_directive_completion_candidates,
    extract_directive_token_around_cursor,
    is_directive_like_token,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def test_directive_like_token_accepts_marker_and_identifier() -> None:
    assert is_directive_like_token("%") is True
    assert is_directive_like_token("%model") is True
    assert is_directive_like_token("model") is False
    assert is_directive_like_token("%model:opus") is False


def test_directive_completion_lists_canonical_directives() -> None:
    candidates, shared = build_directive_completion_candidates("%")
    insertions = {candidate.insertion for candidate in candidates}

    assert shared == ""
    assert "%alt" in insertions
    assert "%auto" in insertions
    assert "%model" in insertions
    assert "%wait" in insertions
    assert "%plan" not in insertions
    assert "%tale" not in insertions
    assert "%epic" not in insertions
    assert "%xprompts_enabled" not in insertions
    assert "%approve" not in insertions


def test_auto_completes_from_name_and_advertises_alias() -> None:
    """%auto is the advertised auto-approval directive with %a as its alias."""
    auto, _ = _single_candidate("%au")
    a_candidates, _ = build_directive_completion_candidates("%a")

    assert auto.insertion == "%auto"
    assert _metadata(auto).aliases == ("a",)
    assert [candidate.insertion for candidate in a_candidates] == ["%alt", "%auto"]


def test_removed_auto_approval_directives_are_absent_from_completion() -> None:
    """Removed auto-approval names and aliases are not completion candidates."""
    approve_candidates, _ = build_directive_completion_candidates("%approve")
    plan_candidates, _ = build_directive_completion_candidates("%pl")
    tale_candidates, _ = build_directive_completion_candidates("%ta")
    epic_candidates, _ = build_directive_completion_candidates("%ep")

    assert approve_candidates == []
    assert plan_candidates == []
    assert tale_candidates == []
    assert epic_candidates == []


def test_directive_completion_includes_representative_descriptions() -> None:
    model, _ = _single_candidate("%mo")
    wait, _ = _single_candidate("%w")
    alt, _ = _single_candidate("%al")
    auto, _ = _single_candidate("%au")

    assert _metadata(model).description == "choose one or more provider/model targets"
    assert _metadata(wait).description == (
        "defer launch until agents complete or a time floor passes"
    )
    assert _metadata(alt).description == (
        "split a prompt into variants; shorthand %{A | B}"
    )
    assert _metadata(auto).description == (
        "auto-approve the submitted plan as plan (default), tale, or epic"
    )


def test_directive_completion_t_prefix_lists_no_directives() -> None:
    """%time is no longer a directive completion candidate."""
    candidates, _ = build_directive_completion_candidates("%t")
    assert candidates == []

    tale_candidates, _ = build_directive_completion_candidates("%ta")
    assert tale_candidates == []
    ti_candidates, _ = build_directive_completion_candidates("%ti")
    assert ti_candidates == []


def test_directive_completion_includes_group() -> None:
    group, _ = _single_candidate("%gr")
    assert group.insertion == "%group"


def test_all_directive_completion_candidates_have_descriptions() -> None:
    candidates, _ = build_directive_completion_candidates("%")

    missing = [
        candidate.insertion
        for candidate in candidates
        if not _metadata(candidate).description
    ]
    assert missing == []


def test_directive_completion_filters_partial_name() -> None:
    candidates, shared = build_directive_completion_candidates("%mo")

    assert shared == ""
    assert [candidate.insertion for candidate in candidates] == ["%model"]


def test_directive_completion_matches_aliases_to_canonical_insertions() -> None:
    model, _ = _single_candidate("%m")
    repeat, _ = _single_candidate("%r")
    wait, _ = _single_candidate("%w")

    assert model.insertion == "%model"
    assert repeat.insertion == "%repeat"
    assert wait.insertion == "%wait"


def test_directive_completion_returns_multi_match_without_false_shared_prefix() -> None:
    candidates, shared = build_directive_completion_candidates("%e")

    assert [candidate.insertion for candidate in candidates] == [
        "%edit",
        "%effort",
    ]
    assert shared == ""


def test_directive_token_extraction_rejects_non_directive_percent_positions() -> None:
    assert extract_directive_token_around_cursor("50%", 3) is None
    assert (
        extract_directive_token_around_cursor("word%model", len("word%model")) is None
    )


def test_directive_token_extraction_accepts_parser_contexts() -> None:
    assert extract_directive_token_around_cursor("%", 1) == (0, 1, "%")
    assert extract_directive_token_around_cursor("run %mo", len("run %mo")) == (
        4,
        7,
        "%mo",
    )
    assert extract_directive_token_around_cursor("(%wait", len("(%wait")) == (
        1,
        6,
        "%wait",
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
        assert "choose one or more provider/model targets" in panel.render().plain


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
        ta.load_text("%e")
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
        assert ta._file_completion_active is False

        await pilot.press("m")

        # A single ``%m`` -> ``%model`` match opens the menu but never
        # auto-accepts: the text stays ``%m`` until the user accepts explicitly.
        assert ta.text == "%m"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive"
        assert [c.insertion for c in ta._file_completion_candidates] == ["%model"]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "directives"


async def test_bare_percent_does_not_auto_open() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)

        await pilot.press("%")

        assert ta.text == "%"
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
        await pilot.press("e")
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "%edit",
            "%effort",
        ]

        await pilot.press("d")
        assert ta.text == "%ed"
        assert [c.insertion for c in ta._file_completion_candidates] == ["%edit"]

        await pilot.press("backspace")
        assert ta.text == "%e"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "%edit",
            "%effort",
        ]

        await pilot.press("space")
        assert ta.text == "%e "
        assert ta._file_completion_active is False


def _single_candidate(token: str):
    candidates, shared = build_directive_completion_candidates(token)
    assert len(candidates) == 1
    return candidates[0], shared


def _metadata(candidate) -> DirectiveCompletionMetadata:
    assert isinstance(candidate.metadata, DirectiveCompletionMetadata)
    return candidate.metadata
