"""Tests for prompt directive completion candidates."""

from __future__ import annotations

from sase.ace.tui.widgets.directive_completion import (
    build_directive_arg_completion_candidates,
    build_directive_completion_candidates,
    extract_directive_arg_token_around_cursor,
    extract_directive_token_around_cursor,
    is_directive_like_token,
)

from ._directive_completion_helpers import (
    directive_metadata,
    single_directive_candidate,
)


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
    auto, _ = single_directive_candidate("%au")
    a_candidates, _ = build_directive_completion_candidates("%a")

    assert auto.insertion == "%auto"
    assert directive_metadata(auto).aliases == ("a",)
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
    model, _ = single_directive_candidate("%mo")
    name, _ = single_directive_candidate("%n")
    wait, _ = single_directive_candidate("%w")
    alt, _ = single_directive_candidate("%al")
    auto, _ = single_directive_candidate("%au")

    assert directive_metadata(model).description == (
        "choose a model and optional launch-family alias overrides"
    )
    assert directive_metadata(model).argument_hint == (":model or (model, alias=model)")
    assert directive_metadata(name).description == (
        "assign an agent name or attach a member to an existing family"
    )
    assert directive_metadata(name).argument_hint == ":agent or (parent, suffix)"
    assert directive_metadata(wait).description == (
        "defer launch for agents, a time floor, or a runner threshold"
    )
    assert directive_metadata(alt).description == (
        "split a prompt into variants; shorthand %{A | B}"
    )
    assert directive_metadata(auto).description == (
        "request automatic gate resolution; arguments are gate-specific"
    )
    assert directive_metadata(auto).argument_hint == (":argument (e.g. plan|tale|epic)")


def test_directive_completion_t_prefix_lists_tribe() -> None:
    """%tribe owns the %t prefix; removed %time remains absent."""
    candidates, _ = build_directive_completion_candidates("%t")
    assert [candidate.insertion for candidate in candidates] == ["%tribe"]

    tale_candidates, _ = build_directive_completion_candidates("%ta")
    assert tale_candidates == []
    ti_candidates, _ = build_directive_completion_candidates("%ti")
    assert ti_candidates == []


def test_directive_completion_includes_tribe_and_alias() -> None:
    tribe, _ = single_directive_candidate("%tr")
    alias, _ = single_directive_candidate("%t")

    assert tribe.insertion == "%tribe"
    assert alias.insertion == "%tribe"
    assert directive_metadata(tribe).aliases == ("t",)
    assert directive_metadata(tribe).argument_hint == ":name"
    assert directive_metadata(tribe).description == (
        "assign a user-managed agent tribe"
    )


def test_directive_completion_includes_clan_and_alias() -> None:
    clan, _ = single_directive_candidate("%cla")
    alias, _ = single_directive_candidate("%c")

    assert clan.insertion == "%clan"
    assert alias.insertion == "%clan"
    assert directive_metadata(clan).aliases == ("c",)
    assert directive_metadata(clan).argument_hint == ":name"
    assert directive_metadata(clan).description == "join a named parallel agent clan"


def test_all_directive_completion_candidates_have_descriptions() -> None:
    candidates, _ = build_directive_completion_candidates("%")

    missing = [
        candidate.insertion
        for candidate in candidates
        if not directive_metadata(candidate).description
    ]
    assert missing == []


def test_directive_completion_filters_partial_name() -> None:
    candidates, shared = build_directive_completion_candidates("%mo")

    assert shared == ""
    assert [candidate.insertion for candidate in candidates] == ["%model"]


def test_directive_completion_matches_aliases_to_canonical_insertions() -> None:
    model, _ = single_directive_candidate("%m")
    repeat, _ = single_directive_candidate("%r")
    wait, _ = single_directive_candidate("%w")

    assert model.insertion == "%model"
    assert repeat.insertion == "%repeat"
    assert wait.insertion == "%wait"


def test_directive_completion_returns_multi_match_without_false_shared_prefix() -> None:
    candidates, shared = build_directive_completion_candidates("%a")

    assert [candidate.insertion for candidate in candidates] == [
        "%alt",
        "%auto",
    ]
    assert shared == ""


def test_e_prefix_completes_only_effort() -> None:
    """``%e`` is the advertised ``%effort`` alias, so it narrows to ``%effort``."""
    candidates, shared = build_directive_completion_candidates("%e")

    assert [candidate.insertion for candidate in candidates] == ["%effort"]
    assert shared == ""


def test_effort_completion_advertises_e_alias() -> None:
    """``%effort`` metadata advertises ``%e`` as its alias."""
    effort, _ = single_directive_candidate("%eff")

    assert effort.insertion == "%effort"
    assert directive_metadata(effort).aliases == ("e",)


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


def test_model_paren_completion_offers_alias_keys_and_model_values() -> None:
    line = "%m(co"
    token = extract_directive_arg_token_around_cursor(line, len(line))
    assert token is not None
    _, _, directive_name, partial = token

    candidates, _ = build_directive_arg_completion_candidates(
        directive_name,
        partial,
    )

    assert "coder=" in {candidate.insertion for candidate in candidates}


def test_wait_paren_completion_uses_keyword_aware_context() -> None:
    line = "%wait(run"
    assert extract_directive_arg_token_around_cursor(line, len(line)) == (
        len("%wait("),
        len(line),
        "wait",
        "run",
    )


def test_model_paren_completion_replaces_kwarg_value_only() -> None:
    line = "%m(opus, coder=son"
    assert extract_directive_arg_token_around_cursor(line, len(line)) == (
        len("%m(opus, coder="),
        len(line),
        "model",
        "son",
    )


def test_model_paren_positional_effort_completion_is_preserved() -> None:
    line = "%m(opus@h"
    assert extract_directive_arg_token_around_cursor(line, len(line)) == (
        len("%m(opus@"),
        len(line),
        "effort",
        "h",
    )
