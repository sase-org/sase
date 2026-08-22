"""Tests for prompt directive argument completion candidates."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.directive_completion import (
    BeadCompletionMetadata,
    DirectiveArgCompletionMetadata,
    DirectiveCatalogPlaceholder,
    ModelCompletionMetadata,
    build_agent_arg_completion_candidates,
    build_directive_clause_candidates,
    classify_directive_completion,
)
from sase.ace.tui.widgets._directive_completion_tokens import (
    extract_directive_arg_token_around_cursor,
)
from sase.xprompt._directive_types import AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED
from sase.xprompt.model_completion import _ModelCompletionEntry

from ._directive_completion_helpers import (
    MODEL_CATALOG_PATCH,
    agent_candidate,
    build_directive_arg_completion_candidates,
    directive_arg_metadata,
    model_metadata,
    model_entries,
    model_entries_with_providers,
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
        "agent=",
        "bead=",
        "priority=",
        "proc=",
        "runners=",
        "time=",
        "unit=",
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
        "agent=",
        "bead=",
        "priority=",
        "proc=",
        "runners=",
        "time=",
        "unit=",
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
        "agent=",
        "bead=",
        "priority=",
        "proc=",
        "runners=",
        "unit=",
        "coder",
    ]
    assert shared == ""


def test_wait_priority_completion_describes_order_and_default() -> None:
    candidates, _ = build_directive_arg_completion_candidates("wait", "pri")

    assert [candidate.insertion for candidate in candidates] == ["priority="]
    assert directive_arg_metadata(candidates[0]).description == (
        "Lower values start first; the default is 10"
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


def test_directive_arg_completion_filters_provider_scoped_models() -> None:
    with patch(MODEL_CATALOG_PATCH, return_value=model_entries_with_providers()):
        m_candidates, m_shared = build_directive_arg_completion_candidates(
            "m", "claude/"
        )
        model_candidates, model_shared = build_directive_arg_completion_candidates(
            "model", "claude/"
        )

    assert [candidate.insertion for candidate in m_candidates] == [
        "claude/claude-fable-5"
    ]
    assert [candidate.insertion for candidate in model_candidates] == [
        "claude/claude-fable-5"
    ]
    assert m_shared == ""
    assert model_shared == ""


def test_directive_arg_completion_filters_provider_scope_in_paren_forms() -> None:
    lines = [
        "%model(claude/)",
        "%model(opus, alias=claude/)",
    ]

    with patch(MODEL_CATALOG_PATCH, return_value=model_entries_with_providers()):
        insertions = []
        for line in lines:
            token = extract_directive_arg_token_around_cursor(line, line.index(")"))
            assert token is not None
            _start, _end, directive_name, partial = token
            candidates, shared = build_directive_arg_completion_candidates(
                directive_name, partial
            )
            insertions.append([candidate.insertion for candidate in candidates])
            assert shared == ""

    assert insertions == [
        ["claude/claude-fable-5"],
        ["claude/claude-fable-5"],
    ]


def test_directive_arg_completion_marks_provider_candidates_as_directories() -> None:
    with patch(MODEL_CATALOG_PATCH, return_value=model_entries_with_providers()):
        candidates, shared = build_directive_arg_completion_candidates("model", "cl")

    provider = next(
        candidate for candidate in candidates if candidate.insertion == "claude/"
    )
    assert provider.is_dir is True
    metadata = model_metadata(provider)
    assert metadata.kind == "provider"
    assert metadata.provider_display == "Claude"
    assert metadata.provider_model_count == 1
    assert shared == "aude"


def test_provider_scoped_model_completion_has_no_shared_extension() -> None:
    catalog = [
        _ModelCompletionEntry(
            value="opus",
            display="opus",
            description="Claude",
            provider="claude",
        ),
        _ModelCompletionEntry(
            value="sonnet",
            display="sonnet",
            description="Claude",
            provider="claude",
        ),
        _ModelCompletionEntry(
            value="claude/",
            display="claude/",
            description="Claude",
            kind="provider",
            provider="claude",
            provider_model_count=2,
        ),
    ]

    with patch(MODEL_CATALOG_PATCH, return_value=catalog):
        candidates, shared = build_directive_arg_completion_candidates(
            "model", "claude/"
        )

    assert [candidate.insertion for candidate in candidates] == [
        "claude/opus",
        "claude/sonnet",
    ]
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


def test_qualified_model_at_suffix_routes_to_effort_completion() -> None:
    line = "%m:claude/opus@"
    token = extract_directive_arg_token_around_cursor(line, len(line))

    assert token == (len("%m:claude/opus@"), len(line), "effort", "")
    candidates, shared = build_directive_arg_completion_candidates("effort", "")
    assert [candidate.insertion for candidate in candidates] == list(
        EFFORT_LEVELS_ORDERED
    )
    assert shared == ""


def test_model_alias_candidate_carries_resolution_and_provenance() -> None:
    catalog = [
        _ModelCompletionEntry(
            value="@medium",
            display="@medium",
            description="Medium phase worker model.",
            kind="implicit_alias",
            aliases=("medium",),
            alias_kind="role",
            target_provider="codex",
            target_model="gpt-5.6-sol",
            target_effort="high",
            provenance="configured",
            reference="large",
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
        value="@medium",
        kind="implicit_alias",
        alias_kind="role",
        target_provider="codex",
        target_model="gpt-5.6-sol",
        target_effort="high",
        provenance="configured",
        reference="large",
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


def test_xprompts_enabled_offers_bool_values() -> None:
    candidates, _ = build_directive_arg_completion_candidates("xprompts_enabled", "")

    assert [candidate.insertion for candidate in candidates] == ["false", "true"]
    assert all(
        directive_arg_metadata(candidate).description for candidate in candidates
    )


def test_repeat_offers_positive_count_examples() -> None:
    candidates, _ = build_directive_arg_completion_candidates("repeat", "")

    assert [candidate.insertion for candidate in candidates] == ["2", "3"]


def test_id_conflict_omits_family_and_tribe_after_clan() -> None:
    line = "%id(worker, clan=builders, )"
    clause = classify_directive_completion(line, line.index(")"))
    assert clause is not None
    candidates, _ = build_directive_clause_candidates(clause)

    assert [candidate.insertion for candidate in candidates] == ["bead="]


def test_clan_summary_conflict_omits_summary_script() -> None:
    line = "%clan(research, summary=hi, )"
    clause = classify_directive_completion(line, line.index(")"))
    assert clause is not None
    candidates, _ = build_directive_clause_candidates(clause)

    assert [candidate.insertion for candidate in candidates] == ["tribe="]


def test_id_clan_value_filters_to_clan_kind() -> None:
    line = "%id(worker, clan=re"
    clause = classify_directive_completion(line, len(line))
    assert clause is not None
    candidates, _ = build_directive_clause_candidates(
        clause,
        agent_candidates=[
            AgentCompletionCandidate("review", "review", "RUNNING", kind="clan"),
            AgentCompletionCandidate("ship", "ship", "RUNNING", kind="family"),
            agent_candidate("coder"),
        ],
    )

    assert [candidate.insertion for candidate in candidates] == ["review"]


def test_wait_bead_values_use_core_ranked_inventory() -> None:
    line = "%wait(bead="
    clause = classify_directive_completion(line, len(line))
    assert clause is not None
    candidates, _ = build_directive_clause_candidates(
        clause,
        bead_inventory=(
            {
                "id": "z-open",
                "title": "Later open",
                "status": "open",
                "type_label": "task",
                "updated_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "a-progress",
                "title": "Active bug",
                "status": "in_progress",
                "type_label": "task",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        ),
        beads_state="warm",
    )

    assert [candidate.insertion for candidate in candidates] == [
        "a-progress",
        "z-open",
    ]
    assert isinstance(candidates[0].metadata, BeadCompletionMetadata)
    assert candidates[0].metadata.title == "Active bug"


def test_wait_bead_values_show_loading_when_catalog_is_cold() -> None:
    line = "%wait(bead="
    clause = classify_directive_completion(line, len(line))
    assert clause is not None
    candidates, _ = build_directive_clause_candidates(clause, beads_state="loading")

    assert len(candidates) == 1
    assert isinstance(candidates[0].metadata, DirectiveCatalogPlaceholder)
    assert candidates[0].metadata.kind == "loading"
    assert candidates[0].insertion == ""
