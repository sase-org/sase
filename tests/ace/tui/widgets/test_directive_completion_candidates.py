"""Tests for prompt directive completion candidates."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from sase.ace.tui.widgets.directive_completion import (
    build_directive_completion_candidates,
    extract_directive_arg_token_around_cursor,
    extract_directive_token_around_cursor,
    is_directive_like_token,
)
from sase.feature_flags import override_flags

from ._directive_completion_helpers import (
    build_directive_arg_completion_candidates,
    directive_metadata,
    single_directive_candidate,
)


@pytest.fixture(autouse=True)
def _typed_launch_units_off_by_default() -> Iterator[None]:
    """Keep candidate lists independent of host typed_launch_units state."""
    with override_flags(typed_launch_units=False):
        yield


def test_directive_like_token_accepts_marker_and_identifier() -> None:
    assert is_directive_like_token("%") is True
    assert is_directive_like_token("%model") is True
    assert is_directive_like_token("model") is False
    assert is_directive_like_token("%model:opus") is False


def canonical_insertions(candidates) -> list[str]:
    return [
        candidate.insertion
        for candidate in candidates
        if not directive_metadata(candidate).is_snippet
    ]


def test_directive_completion_lists_canonical_directives() -> None:
    candidates, shared = build_directive_completion_candidates("%")
    insertions = set(canonical_insertions(candidates))

    assert shared == ""
    assert "%alt" in insertions
    assert "%auto" in insertions
    assert "%model" in insertions
    assert "%id" in insertions
    assert "%wait" in insertions
    assert "%final" in insertions
    assert "%tribe" not in insertions
    assert "%name" not in insertions
    assert "%plan" not in insertions
    assert "%tale" not in insertions
    assert "%epic" not in insertions
    assert "%xprompts_enabled" in insertions
    assert "%approve" not in insertions


def test_auto_completes_from_name_and_advertises_alias() -> None:
    """%auto is the advertised auto-approval directive with %a as its alias."""
    auto, _ = single_directive_candidate("%au")
    a_candidates, _ = build_directive_completion_candidates("%a")

    assert auto.insertion == "%auto"
    assert directive_metadata(auto).aliases == ("a",)
    assert canonical_insertions(a_candidates) == ["%alt", "%auto"]


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


def test_deprecated_name_spellings_are_absent_from_completion() -> None:
    name_candidates, _ = build_directive_completion_candidates("%name")
    n_candidates, _ = build_directive_completion_candidates("%n")

    assert name_candidates == []
    assert n_candidates == []


def test_directive_completion_includes_representative_descriptions() -> None:
    model, _ = single_directive_candidate("%mo")
    agent_id, _ = single_directive_candidate("%i")
    wait, _ = single_directive_candidate("%w")
    alt, _ = single_directive_candidate("%al")
    auto, _ = single_directive_candidate("%au")

    assert directive_metadata(model).description == (
        "Override the LLM model for this prompt"
    )
    assert directive_metadata(model).argument_hint == (":model or (model, alias=model)")
    assert directive_metadata(agent_id).description == (
        "Assign an agent ID with optional bead, clan, family, or user-managed tribe"
    )
    assert directive_metadata(agent_id).argument_hint == (
        ":agent-id or :name.{@key}; ([id], bead=, clan=/family=/tribe=)"
    )
    assert directive_metadata(wait).description == (
        "Wait for another agent/workflow and/or a time floor"
    )
    assert directive_metadata(wait).argument_hint == (
        ":agent or (agent, bead=, time=, runners=, priority=)"
    )
    assert directive_metadata(alt).description == (
        "Split prompt into variants with different text; shorthand %{A | B}"
    )
    assert directive_metadata(auto).description == (
        "Request automatic gate resolution; arguments are interpreted by the gate kind"
    )
    assert directive_metadata(auto).argument_hint == (":argument (e.g. plan|tale|epic)")


def test_final_directive_name_completes_to_canonical_row() -> None:
    for token in ["%f", "%final"]:
        final, _ = single_directive_candidate(token)

        assert final.insertion == "%final"
        assert directive_metadata(final).description == (
            "Select configured finalizer instances for this launch"
        )


def test_removed_tribe_spellings_are_absent_from_completion() -> None:
    candidates, _ = build_directive_completion_candidates("%t")
    assert candidates == []

    tribe_candidates, _ = build_directive_completion_candidates("%tribe")
    assert tribe_candidates == []


def test_directive_completion_includes_clan_and_alias() -> None:
    clan, _ = single_directive_candidate("%cla")
    alias, _ = single_directive_candidate("%c")

    assert clan.insertion == "%clan"
    assert alias.insertion == "%clan"
    assert directive_metadata(clan).aliases == ("c",)
    assert directive_metadata(clan).argument_hint == (
        ":name or :name.{@key}, (name, tribe=/summary=/summary_script=), or :name:: summary"
    )
    assert directive_metadata(clan).description == ("Declare a new parallel agent clan")


def test_clan_parenthesized_completion_advertises_tribe_keyword() -> None:
    context = extract_directive_arg_token_around_cursor(
        "%clan(research, tr)",
        len("%clan(research, tr"),
    )
    assert context is not None
    _, _, directive_name, partial = context

    candidates, shared = build_directive_arg_completion_candidates(
        directive_name,
        partial,
    )

    assert shared == ""
    assert [candidate.insertion for candidate in candidates] == ["tribe="]


def test_clan_parenthesized_completion_advertises_summary_keywords() -> None:
    context = extract_directive_arg_token_around_cursor(
        "%clan(research, su)",
        len("%clan(research, su"),
    )
    assert context is not None
    _, _, directive_name, partial = context

    candidates, shared = build_directive_arg_completion_candidates(
        directive_name,
        partial,
    )

    assert shared == ""
    assert [candidate.insertion for candidate in candidates] == [
        "summary=",
        "summary_script=",
    ]


def test_id_parenthesized_completion_advertises_identity_keywords() -> None:
    for line, expected in (
        ("%id(worker, be", "bead="),
        ("%id(be", "bead="),
        ("%id(worker, cl", "clan="),
        ("%id(worker, fa", "family="),
        ("%id(fa", "family="),
        ("%id(tr", "tribe="),
    ):
        context = extract_directive_arg_token_around_cursor(line, len(line))
        assert context is not None
        _, _, directive_name, partial = context

        candidates, shared = build_directive_arg_completion_candidates(
            directive_name,
            partial,
        )

        assert shared == ""
        assert [candidate.insertion for candidate in candidates] == [expected]


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

    assert shared == "del"
    assert canonical_insertions(candidates) == ["%model"]


def test_directive_completion_includes_contract_recipe_templates() -> None:
    candidates, _ = build_directive_completion_candidates("%mo")
    recipes = [
        candidate
        for candidate in candidates
        if directive_metadata(candidate).is_snippet
    ]

    alias_recipe = next(
        candidate
        for candidate in recipes
        if candidate.display == "%model(..., alias=...)"
    )
    metadata = directive_metadata(alias_recipe)
    assert alias_recipe.insertion == "%model(model, alias=model)"
    assert metadata.template == "%model($1, $2=$3)$0"
    assert metadata.plain_text == "%model(model, alias=model)"


def test_directive_completion_matches_aliases_to_canonical_insertions() -> None:
    agent_id, _ = single_directive_candidate("%i")
    model, _ = single_directive_candidate("%m")
    repeat, _ = single_directive_candidate("%r")
    wait, _ = single_directive_candidate("%w")

    assert agent_id.insertion == "%id"
    assert directive_metadata(agent_id).aliases == ("i",)
    assert model.insertion == "%model"
    assert repeat.insertion == "%repeat"
    assert wait.insertion == "%wait"


def test_directive_completion_returns_multi_match_without_false_shared_prefix() -> None:
    candidates, shared = build_directive_completion_candidates("%a")

    assert canonical_insertions(candidates) == [
        "%alt",
        "%auto",
    ]
    assert shared == ""


def test_e_prefix_completes_only_effort() -> None:
    """``%e`` is the advertised ``%effort`` alias, so it narrows to ``%effort``."""
    candidates, shared = build_directive_completion_candidates("%e")

    assert canonical_insertions(candidates) == ["%effort"]
    assert shared == "ffort"


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
    line = "%m(medium"
    token = extract_directive_arg_token_around_cursor(line, len(line))
    assert token is not None
    _, _, directive_name, partial = token

    candidates, _ = build_directive_arg_completion_candidates(
        directive_name,
        partial,
    )

    assert "medium=" in {candidate.insertion for candidate in candidates}


def test_wait_paren_completion_uses_keyword_aware_context() -> None:
    line = "%wait(run"
    assert extract_directive_arg_token_around_cursor(line, len(line)) == (
        len("%wait("),
        len(line),
        "wait",
        "run",
    )


def test_model_paren_completion_replaces_kwarg_value_only() -> None:
    line = "%m(opus, medium=son"
    assert extract_directive_arg_token_around_cursor(line, len(line)) == (
        len("%m(opus, medium="),
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
