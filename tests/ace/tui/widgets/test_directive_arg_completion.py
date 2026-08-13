"""Tests for prompt directive argument completion candidates."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.directive_completion import (
    DirectiveArgCompletionMetadata,
    ModelCompletionMetadata,
    build_agent_arg_completion_candidates,
    build_directive_arg_completion_candidates,
)
from sase.xprompt._directive_types import AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED
from sase.xprompt.model_completion import _ModelCompletionEntry

from ._directive_completion_helpers import (
    MODEL_CATALOG_PATCH,
    agent_candidate,
    directive_arg_metadata,
    model_metadata,
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
            agent_candidate("epic.alpha", tribe="@epic"),
            agent_candidate("epic.beta", tribe="@epic"),
            agent_candidate("reviewer", tribe="@review"),
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
        "priority=",
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
        "priority=",
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


def test_wait_arg_completion_excludes_selected_keywords_case_insensitively() -> None:
    candidates, shared = build_directive_arg_completion_candidates(
        "wait",
        "",
        agent_candidates=[agent_candidate("planner"), agent_candidate("coder")],
        selected_values=frozenset({"TIME=5m", "Planner"}),
    )

    assert [candidate.insertion for candidate in candidates] == [
        "priority=",
        "runners=",
        "coder",
    ]
    assert shared == ""


def test_wait_priority_completion_describes_order_and_default() -> None:
    candidates, _ = build_directive_arg_completion_candidates("wait", "pri")

    assert [candidate.insertion for candidate in candidates] == ["priority="]
    assert directive_arg_metadata(candidates[0]).description == (
        "lower values start first; the default is 10"
    )


def test_directive_arg_completion_builds_model_candidates_from_catalog() -> None:
    with patch(MODEL_CATALOG_PATCH, return_value=model_entries()):
        candidates, shared = build_directive_arg_completion_candidates("model", "")

    assert [candidate.insertion for candidate in candidates] == [
        "claude-fable-5",
        "gpt-5.6-sol",
    ]
    assert shared == ""
    metadata = model_metadata(candidates[0])
    assert metadata.description == "Claude (fable)"
    assert metadata.provider == "claude"
    assert metadata.provider_display == "Claude"
    assert metadata.short_alias == "fable"


def test_directive_arg_completion_filters_model_candidates_by_short_alias() -> None:
    with patch(MODEL_CATALOG_PATCH, return_value=model_entries()):
        candidates, shared = build_directive_arg_completion_candidates("model", "fa")

    assert [candidate.insertion for candidate in candidates] == ["claude-fable-5"]
    assert shared == ""


def test_directive_arg_completion_filters_leading_at_to_model_aliases() -> None:
    catalog = [
        *model_entries(),
        _ModelCompletionEntry(
            value="@default",
            display="@default",
            description="default model when a prompt has no %model",
            provider="claude",
            aliases=(),
            kind="implicit_alias",
        ),
    ]

    with patch(MODEL_CATALOG_PATCH, return_value=catalog):
        candidates, shared = build_directive_arg_completion_candidates("model", "@")

    assert [candidate.insertion for candidate in candidates] == ["@default"]
    assert all(candidate.insertion.startswith("@") for candidate in candidates)
    assert shared == ""


def test_model_alias_candidate_carries_resolution_and_provenance() -> None:
    catalog = [
        _ModelCompletionEntry(
            value="@medium_worker",
            display="@medium_worker",
            description="Medium phase worker model.",
            kind="implicit_alias",
            aliases=("medium_worker",),
            alias_kind="role",
            target_provider="codex",
            target_model="gpt-5.6-sol",
            target_effort="high",
            provenance="configured",
            reference="default",
            reference_effort="medium",
            pool_available=2,
            pool_total=3,
            config_source="builtin",
        )
    ]

    with patch(MODEL_CATALOG_PATCH, return_value=catalog):
        candidates, _ = build_directive_arg_completion_candidates("model", "@")

    metadata = model_metadata(candidates[0])
    assert metadata == ModelCompletionMetadata(
        value="@medium_worker",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="codex",
        target_model="gpt-5.6-sol",
        target_effort="high",
        provenance="configured",
        reference="default",
        reference_effort="medium",
        pool_available=2,
        pool_total=3,
        description="Medium phase worker model.",
        config_source="builtin",
    )


def test_model_completion_keystroke_path_never_uses_override_lock() -> None:
    with (
        patch(MODEL_CATALOG_PATCH, return_value=model_entries()),
        patch(
            "sase.llm_provider.temporary_override.get_active_alias_overrides",
            side_effect=AssertionError("authoritative override load reached"),
        ),
        patch(
            "sase.llm_provider.temporary_override_state._locked_state",
            side_effect=AssertionError("override lock reached"),
        ),
    ):
        candidates, _ = build_directive_arg_completion_candidates("model", "")

    assert [candidate.insertion for candidate in candidates] == [
        "claude-fable-5",
        "gpt-5.6-sol",
    ]


def test_directive_arg_completion_metadata_has_descriptions() -> None:
    candidates, _ = build_directive_arg_completion_candidates("auto", "")

    assert all(
        directive_arg_metadata(candidate).description for candidate in candidates
    )
    assert all(
        isinstance(candidate.metadata, DirectiveArgCompletionMetadata)
        for candidate in candidates
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
