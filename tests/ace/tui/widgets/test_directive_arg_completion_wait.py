"""Wait/id/clan/bead directive argument completion.

Split from ``test_directive_arg_completion``; shared builders live in
``_directive_completion_helpers`` and the original module re-exports these
tests so its import path keeps working.
"""

from __future__ import annotations

import pytest

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.directive_completion import (
    BeadCompletionMetadata,
    DirectiveCatalogPlaceholder,
    build_agent_arg_completion_candidates,
    build_directive_clause_candidates,
    classify_directive_completion,
)

from ._directive_completion_helpers import (
    agent_candidate,
    build_directive_arg_completion_candidates,
)

__all__ = [
    "test_clan_summary_conflict_omits_summary_script",
    "test_id_clan_value_filters_to_clan_kind",
    "test_id_conflict_omits_session_and_tribe_after_clan",
    "test_id_session_value_filters_to_session_kind",
    "test_wait_arg_completion_excludes_groups_and_deduplicates_insertions",
    "test_wait_arg_completion_excludes_selected_keywords_case_insensitively",
    "test_wait_arg_completion_filters_visible_agent_candidates",
    "test_wait_arg_completion_ignores_time_keyword_fragment",
    "test_wait_arg_completion_offers_deduplicated_tribe_targets",
    "test_wait_arg_completion_omits_named_proc_targets",
    "test_wait_arg_completion_orders_kinds_and_matches_bare_tribe",
    "test_wait_bead_values_show_loading_when_catalog_is_cold",
    "test_wait_bead_values_use_core_ranked_inventory",
    "test_wait_paren_arg_completion_does_not_suggest_queue_keywords",
]


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


def test_wait_arg_completion_omits_named_proc_targets() -> None:
    # `#fork` accepts a named proc, but a `%wait` dependency resolves agent
    # artifacts only, so completing one would never release.
    proc = AgentCompletionCandidate(
        name="abc123def456",
        label="build-docs",
        status="RUNNING",
        kind="proc",
        proc_id="abc123def456",
    )

    candidates, _shared = build_directive_arg_completion_candidates(
        "wait",
        "abc",
        agent_candidates=[agent_candidate("abc-coder"), proc],
    )

    assert [candidate.insertion for candidate in candidates] == ["abc-coder"]

    # The unfiltered builder backing ``#fork:`` still offers the named proc.
    fork_candidates, _fork_shared = build_agent_arg_completion_candidates(
        "abc",
        [agent_candidate("abc-coder"), proc],
    )

    assert [candidate.insertion for candidate in fork_candidates] == [
        "abc-coder",
        "abc123def456",
    ]


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
                "ship", "ship", "RUNNING", kind="session", member_count=2
            ),
            tribe,
        ],
    )

    assert [candidate.insertion for candidate in candidates] == [
        "agent=",
        "bead=",
        "for_epic=",
        "hood=",
        "proc=",
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
            AgentCompletionCandidate("ship", "ship", "RUNNING", kind="session"),
            AgentCompletionCandidate("ship", "ship", "RUNNING"),
            AgentCompletionCandidate("coder", "coder", "RUNNING"),
        ],
    )
    assert [candidate.insertion for candidate in candidates] == [
        "agent=",
        "bead=",
        "for_epic=",
        "hood=",
        "proc=",
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
            for candidate in candidates
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


def test_wait_paren_arg_completion_does_not_suggest_queue_keywords() -> None:
    candidates, shared = build_directive_arg_completion_candidates(
        "wait",
        "run",
        agent_candidates=[agent_candidate("coder")],
    )

    assert candidates == []
    priority_candidates, _ = build_directive_arg_completion_candidates("wait", "pri")
    assert priority_candidates == []
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
        "for_epic=",
        "hood=",
        "proc=",
        "unit=",
        "coder",
    ]
    assert shared == ""


def test_id_conflict_omits_session_and_tribe_after_clan() -> None:
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
            AgentCompletionCandidate("ship", "ship", "RUNNING", kind="session"),
            agent_candidate("coder"),
        ],
    )

    assert [candidate.insertion for candidate in candidates] == ["review"]


@pytest.mark.parametrize("keyword", ["session", "family"])
def test_id_session_value_filters_to_session_kind(keyword: str) -> None:
    # Core still emits value_role "family" for both spellings until core-contract.
    line = f"%id(worker, {keyword}=sh"
    clause = classify_directive_completion(line, len(line))
    assert clause is not None
    candidates, _ = build_directive_clause_candidates(
        clause,
        agent_candidates=[
            AgentCompletionCandidate("review", "review", "RUNNING", kind="clan"),
            AgentCompletionCandidate("ship", "ship", "RUNNING", kind="session"),
            AgentCompletionCandidate("shell", "shell", "RUNNING"),
        ],
    )

    assert [candidate.insertion for candidate in candidates] == ["ship"]


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
