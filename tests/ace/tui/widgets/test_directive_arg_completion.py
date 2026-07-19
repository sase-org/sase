"""Tests for prompt directive argument completion candidates."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.directive_completion import (
    build_agent_arg_completion_candidates,
    build_directive_arg_completion_candidates,
)
from sase.xprompt._directive_types import AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED

from ._directive_completion_helpers import (
    MODEL_CATALOG_PATCH,
    agent_candidate,
    directive_arg_metadata,
    model_entries,
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
        AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
    )
    assert effort_shared == ""
    assert auto_shared == ""


def test_directive_arg_completion_accepts_effort_e_alias() -> None:
    """``%e:`` offers the canonical effort vocabulary, same as ``%effort:``."""
    e_candidates, e_shared = build_directive_arg_completion_candidates("e", "")

    assert [candidate.insertion for candidate in e_candidates] == list(
        EFFORT_LEVELS_ORDERED
    )
    assert e_shared == ""


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


def test_wait_arg_completion_filters_visible_agent_candidates() -> None:
    candidates, shared = build_directive_arg_completion_candidates(
        "wait",
        "co",
        agent_candidates=[
            agent_candidate("coder"),
            agent_candidate("planner"),
        ],
    )

    assert [candidate.insertion for candidate in candidates] == ["coder"]
    assert isinstance(candidates[0].metadata, AgentCompletionCandidate)
    assert shared == ""


def test_wait_arg_completion_offers_deduplicated_tribe_targets() -> None:
    candidates, shared = build_directive_arg_completion_candidates(
        "wait",
        "@e",
        agent_candidates=[
            agent_candidate("epic.alpha", tag="@epic"),
            agent_candidate("epic.beta", tag="@epic"),
            agent_candidate("reviewer", tag="@review"),
        ],
    )

    assert [candidate.insertion for candidate in candidates] == ["@epic"]
    assert isinstance(candidates[0].metadata, AgentCompletionCandidate)
    assert candidates[0].metadata.kind == "tribe"
    assert candidates[0].metadata.member_count == 2
    assert shared == ""


def test_wait_arg_completion_orders_kinds_and_matches_bare_tribe() -> None:
    tribe = AgentCompletionCandidate(
        "@builders",
        "builders",
        "RUNNING",
        kind="tribe",
        member_count=3,
    )
    candidates, _ = build_directive_arg_completion_candidates(
        "wait",
        "",
        agent_candidates=[
            AgentCompletionCandidate("coder", "coder", "RUNNING"),
            AgentCompletionCandidate(
                "review", "review", "RUNNING", kind="clan", member_count=2
            ),
            AgentCompletionCandidate(
                "ship", "ship", "RUNNING", kind="family", member_count=2
            ),
            tribe,
        ],
    )

    assert [candidate.insertion for candidate in candidates] == [
        "runners=",
        "time=",
        "@builders",
        "review",
        "ship",
        "coder",
    ]
    bare, _ = build_directive_arg_completion_candidates(
        "wait",
        "bui",
        agent_candidates=[tribe],
    )
    assert [candidate.insertion for candidate in bare] == ["@builders"]


def test_wait_arg_completion_excludes_groups_and_deduplicates_insertions() -> None:
    candidates, _ = build_directive_arg_completion_candidates(
        "wait",
        "",
        agent_candidates=[
            AgentCompletionCandidate("@builders", "builders", "RUNNING", kind="tribe"),
            AgentCompletionCandidate("review", "review", "RUNNING", kind="clan"),
            AgentCompletionCandidate("ship", "ship", "RUNNING", kind="family"),
            AgentCompletionCandidate("ship", "ship", "RUNNING"),
            AgentCompletionCandidate("coder", "coder", "RUNNING"),
        ],
    )
    assert [candidate.insertion for candidate in candidates] == [
        "runners=",
        "time=",
        "@builders",
        "review",
        "ship",
        "coder",
    ]

    # Fork passes already-selected values through the shared target builder.
    filtered, _ = build_agent_arg_completion_candidates(
        "",
        [
            candidate.metadata
            for candidate in candidates[2:]
            if isinstance(candidate.metadata, AgentCompletionCandidate)
        ],
        excluded_names=frozenset({"@builders", "review", "ship"}),
    )
    assert [candidate.insertion for candidate in filtered] == ["coder"]


def test_wait_arg_completion_ignores_time_keyword_fragment() -> None:
    candidates, shared = build_directive_arg_completion_candidates(
        "wait",
        "time=5m",
        agent_candidates=[agent_candidate("coder")],
    )

    assert candidates == []
    assert shared == ""


def test_wait_paren_arg_completion_suggests_runners_keyword() -> None:
    candidates, shared = build_directive_arg_completion_candidates(
        "wait",
        "run",
        agent_candidates=[agent_candidate("coder")],
    )

    assert [candidate.insertion for candidate in candidates] == ["runners="]
    assert shared == ""


def test_directive_arg_completion_builds_model_candidates_from_catalog() -> None:
    with patch(MODEL_CATALOG_PATCH, return_value=model_entries()):
        candidates, shared = build_directive_arg_completion_candidates("model", "")

    assert [candidate.insertion for candidate in candidates] == [
        "claude-fable-5",
        "gpt-5.6-sol",
    ]
    assert shared == ""
    assert directive_arg_metadata(candidates[0]).description == "Claude (fable)"


def test_directive_arg_completion_filters_model_candidates_by_short_alias() -> None:
    with patch(MODEL_CATALOG_PATCH, return_value=model_entries()):
        candidates, shared = build_directive_arg_completion_candidates("model", "fa")

    assert [candidate.insertion for candidate in candidates] == ["claude-fable-5"]
    assert shared == ""


def test_directive_arg_completion_metadata_has_descriptions() -> None:
    candidates, _ = build_directive_arg_completion_candidates("auto", "")

    assert all(
        directive_arg_metadata(candidate).description for candidate in candidates
    )


def test_auto_argument_completion_suggests_compatibility_values_without_closing_parser() -> (
    None
):
    # Keep these suggestions aligned with Rust directive_argument_candidates("auto")
    # in sase-core. They are not a parser allowlist: the eventual gate adapter
    # owns validation of the retained raw argument.
    assert AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS == ("plan", "tale", "epic")
    candidates, _ = build_directive_arg_completion_candidates("auto", "")
    assert tuple(candidate.insertion for candidate in candidates) == (
        AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
    )

    cleaned, directives = extract_prompt_directives("%auto:foo\nDo the work")
    assert cleaned == "Do the work"
    assert directives.auto_argument == "foo"
