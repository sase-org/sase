"""Tests for prompt directive completion."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.directive_completion import (
    DirectiveArgCompletionMetadata,
    DirectiveCompletionMetadata,
    build_directive_arg_completion_candidates,
    build_directive_completion_candidates,
    extract_directive_arg_token_around_cursor,
    extract_directive_token_around_cursor,
    is_directive_like_token,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.xprompt._directive_types import AUTO_MODES_ORDERED
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED
from sase.xprompt.model_completion import _ModelCompletionEntry

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


def test_directive_arg_extraction_detects_empty_partial_and_alias() -> None:
    assert extract_directive_arg_token_around_cursor("%effort:", len("%effort:")) == (
        8,
        8,
        "effort",
        "",
    )
    assert extract_directive_arg_token_around_cursor("%a:", len("%a:")) == (
        3,
        3,
        "auto",
        "",
    )


def test_directive_arg_extraction_returns_partial_span() -> None:
    line = "run %effort:hi now"
    col = line.index(" now")
    assert extract_directive_arg_token_around_cursor(line, col) == (
        line.index(":") + 1,
        col,
        "effort",
        "hi",
    )


def test_directive_arg_extraction_accepts_model_alias_and_special_chars() -> None:
    assert extract_directive_arg_token_around_cursor(
        "%m:gpt-5.5", len("%m:gpt-5.5")
    ) == (
        3,
        len("%m:gpt-5.5"),
        "model",
        "gpt-5.5",
    )
    line = "%model:anthropic/claude-sonnet-4-5"
    assert extract_directive_arg_token_around_cursor(line, len(line)) == (
        len("%model:"),
        len(line),
        "model",
        "anthropic/claude-sonnet-4-5",
    )


def test_directive_arg_extraction_redirects_model_at_suffix_to_effort() -> None:
    assert extract_directive_arg_token_around_cursor(
        "%model:opus@",
        len("%model:opus@"),
    ) == (
        len("%model:opus@"),
        len("%model:opus@"),
        "effort",
        "",
    )
    assert extract_directive_arg_token_around_cursor(
        "%model:opus@xh",
        len("%model:opus@xh"),
    ) == (
        len("%model:opus@"),
        len("%model:opus@xh"),
        "effort",
        "xh",
    )


def test_directive_arg_extraction_rejects_non_argument_contexts() -> None:
    assert extract_directive_arg_token_around_cursor("%effort", len("%effort")) is None
    assert extract_directive_arg_token_around_cursor("%effort:", 4) is None
    assert (
        extract_directive_arg_token_around_cursor(
            "word%effort:",
            len("word%effort:"),
        )
        is None
    )
    assert (
        extract_directive_arg_token_around_cursor("%unknown:", len("%unknown:")) is None
    )
    assert (
        extract_directive_arg_token_around_cursor(
            "%effort:high ",
            len("%effort:high "),
        )
        is None
    )
    assert (
        extract_directive_arg_token_around_cursor(
            "%effort:hi.now",
            len("%effort:hi.now"),
        )
        is None
    )


def test_directive_arg_completion_builds_fixed_value_candidates() -> None:
    effort_candidates, effort_shared = build_directive_arg_completion_candidates(
        "effort",
        "",
    )
    auto_candidates, auto_shared = build_directive_arg_completion_candidates(
        "auto",
        "",
    )

    assert [candidate.insertion for candidate in effort_candidates] == list(
        EFFORT_LEVELS_ORDERED
    )
    assert [candidate.insertion for candidate in auto_candidates] == list(
        AUTO_MODES_ORDERED
    )
    assert effort_shared == ""
    assert auto_shared == ""


def test_directive_arg_completion_filters_case_insensitive_prefixes() -> None:
    effort_candidates, _ = build_directive_arg_completion_candidates("effort", "h")
    auto_candidates, _ = build_directive_arg_completion_candidates("auto", "t")
    xhigh_candidates, _ = build_directive_arg_completion_candidates("effort", "XH")

    assert [candidate.insertion for candidate in effort_candidates] == ["high"]
    assert [candidate.insertion for candidate in auto_candidates] == ["tale"]
    assert [candidate.insertion for candidate in xhigh_candidates] == ["xhigh"]


def test_directive_arg_completion_ignores_open_text_directives() -> None:
    candidates, shared = build_directive_arg_completion_candidates("name", "")

    assert candidates == []
    assert shared == ""


def test_directive_arg_completion_builds_model_candidates_from_catalog() -> None:
    with patch(
        "sase.ace.tui.widgets.directive_completion.build_model_completion_catalog",
        return_value=_model_entries(),
    ):
        candidates, shared = build_directive_arg_completion_candidates("model", "")

    assert [candidate.insertion for candidate in candidates] == [
        "claude-fable-5",
        "gpt-5.5",
    ]
    assert shared == ""
    assert _arg_metadata(candidates[0]).description == "Claude (fable)"


def test_directive_arg_completion_filters_model_candidates_by_short_alias() -> None:
    with patch(
        "sase.ace.tui.widgets.directive_completion.build_model_completion_catalog",
        return_value=_model_entries(),
    ):
        candidates, shared = build_directive_arg_completion_candidates("model", "fa")

    assert [candidate.insertion for candidate in candidates] == ["claude-fable-5"]
    assert shared == ""


def test_directive_arg_completion_metadata_has_descriptions() -> None:
    candidates, _ = build_directive_arg_completion_candidates("auto", "")

    assert all(_arg_metadata(candidate).description for candidate in candidates)


def test_auto_mode_completion_values_mirror_parser_and_rust_registry() -> None:
    # Keep this expected tuple aligned with Rust
    # directive_argument_candidates("auto") in sase-core.
    assert AUTO_MODES_ORDERED == ("plan", "tale", "epic")
    candidates, _ = build_directive_arg_completion_candidates("auto", "")
    assert tuple(candidate.insertion for candidate in candidates) == AUTO_MODES_ORDERED


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

        with patch(
            "sase.ace.tui.widgets.directive_completion.build_model_completion_catalog",
            return_value=_model_entries(),
        ):
            for char in "%model:":
                await pilot.press(char)

        assert ta.text == "%model:"
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive_arg"
        assert [c.insertion for c in ta._file_completion_candidates] == [
            "claude-fable-5",
            "gpt-5.5",
        ]
        panel = bar.query_one("#prompt-completion", Static)
        assert panel.border_title == "directive values"
        assert "Claude (fable)" in panel.render().plain


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
            patch(
                "sase.ace.tui.widgets.directive_completion.build_model_completion_catalog",
                return_value=_model_entries(),
            ),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model:claude-fable-5"
    assert ta._file_completion_active is False


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


def _arg_metadata(candidate) -> DirectiveArgCompletionMetadata:
    assert isinstance(candidate.metadata, DirectiveArgCompletionMetadata)
    return candidate.metadata


def _model_entries() -> list[_ModelCompletionEntry]:
    return [
        _ModelCompletionEntry(
            value="claude-fable-5",
            display="claude-fable-5",
            description="Claude (fable)",
            provider="claude",
            aliases=("fable",),
        ),
        _ModelCompletionEntry(
            value="gpt-5.5",
            display="gpt-5.5",
            description="Codex (gpt55)",
            provider="codex",
            aliases=("gpt55",),
        ),
    ]
