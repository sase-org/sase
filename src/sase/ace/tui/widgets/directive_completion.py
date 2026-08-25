"""ACE adapters over the shared ``sase_core_rs`` directive completion contract.

This module is the stable public facade. Candidate construction is split by
source across the neighboring ``_directive_completion_*`` modules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets._directive_completion_agents import (
    IDENTITY_ROLES,
    build_agent_arg_completion_candidates,
)
from sase.ace.tui.widgets._directive_completion_candidates import (
    build_bead_clause_candidates,
    build_finalizer_clause_candidates,
    core_candidate_rows,
    directive_name_candidate,
    directive_recipe_candidates,
    parenthesized_keyword_fallback,
    shared_extension,
    static_or_keyword_candidate,
)
from sase.ace.tui.widgets._directive_completion_models import (
    build_model_clause_candidates,
)
from sase.ace.tui.widgets._directive_completion_tokens import (
    DirectiveClauseCompletion,
    classify_directive_completion,
    extract_directive_arg_token_around_cursor,
    extract_directive_token_around_cursor,
    is_directive_like_token,
    selected_wait_values_around_cursor,
    synthetic_directive_clause,
)
from sase.ace.tui.widgets._directive_completion_types import (
    BeadCompletionMetadata,
    BeadsState,
    DirectiveArgCompletionMetadata,
    DirectiveCatalogPlaceholder,
    DirectiveCompletionMetadata,
    FinalizerCompletionMetadata,
    FinalizersState,
    ModelCompletionMetadata,
    PathCandidateBuilder,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.xprompt.model_completion import build_model_completion_catalog

# Shell kinds an ordinary ``%wait`` cannot resolve. ``#fork`` accepts a proc
# shell, but wait dependencies resolve agent artifacts only, so offering a
# proc row here would complete a dependency that never releases.
_WAIT_UNSUPPORTED_TARGET_KINDS = frozenset({"proc"})


def build_directive_completion_candidates(
    token: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates and shared extension for a directive token."""
    if not is_directive_like_token(token):
        return [], ""

    clause = synthetic_directive_clause(
        kind="directive_name",
        token=token,
        directive_name=None,
    )
    candidates = [
        directive_name_candidate(row)
        for row in core_candidate_rows(clause)
        if isinstance(row.get("insertion"), str)
    ]
    recipe_candidates = directive_recipe_candidates(token)
    canonical_insertions = [candidate.insertion[1:] for candidate in candidates]
    shared = shared_extension(canonical_insertions, token[1:])
    if not shared and len(canonical_insertions) == 1:
        canonical = canonical_insertions[0]
        partial = token[1:]
        if canonical.startswith(partial) and len(canonical) > len(partial):
            shared = canonical[len(partial) :]
    return [*candidates, *recipe_candidates], shared


def build_directive_clause_candidates(
    clause: DirectiveClauseCompletion,
    *,
    agent_candidates: Sequence[AgentCompletionCandidate] | None = None,
    bead_inventory: Sequence[Mapping[str, str]] | None = None,
    beads_state: BeadsState = "unavailable",
    excluded_bead_ids: Sequence[str] = (),
    finalizer_inventory: Sequence[Mapping[str, object]] | None = None,
    finalizers_state: FinalizersState = "unavailable",
    path_candidates: PathCandidateBuilder | None = None,
) -> tuple[list[CompletionCandidate], str]:
    """Build ACE rows for a classified directive clause."""
    if clause.is_name:
        return build_directive_completion_candidates(clause.token)

    if clause.value_role == "path_or_executable" and path_candidates is not None:
        token = clause.token if clause.token else "./"
        return path_candidates(token)

    if _offers_model_values(clause):
        return build_model_clause_candidates(
            clause,
            catalog_builder=build_model_completion_catalog,
        )

    keyword_fallback = parenthesized_keyword_fallback(clause)
    if keyword_fallback is not None:
        return keyword_fallback

    if clause_needs_finalizer_inventory(clause):
        return build_finalizer_clause_candidates(
            clause,
            finalizer_inventory=finalizer_inventory,
            finalizers_state=finalizers_state,
        )

    if clause.value_role == "bead":
        return build_bead_clause_candidates(
            clause,
            bead_inventory=bead_inventory,
            beads_state=beads_state,
            excluded_bead_ids=excluded_bead_ids,
        )

    if clause.value_role in IDENTITY_ROLES:
        return build_agent_arg_completion_candidates(
            clause.token,
            agent_candidates,
            excluded_names=frozenset(clause.selected_values),
            required_kind=clause.value_role,
        )

    if clause.is_wait_positional or clause.value_role == "agent":
        return _build_wait_or_agent_clause_candidates(clause, agent_candidates)

    partial_lower = clause.token.lower()
    candidates = [
        static_or_keyword_candidate(row, clause)
        for row in core_candidate_rows(
            clause,
            bead_inventory=bead_inventory,
            excluded_bead_ids=excluded_bead_ids,
            finalizer_inventory=finalizer_inventory,
        )
        if isinstance(row.get("insertion"), str)
        and str(row["insertion"]).lower().startswith(partial_lower)
    ]
    if clause.kind == "directive_argument_keyword":
        return candidates, ""
    return candidates, shared_extension(
        [candidate.insertion for candidate in candidates],
        clause.token,
    )


def is_directive_catalog_placeholder(candidate: CompletionCandidate) -> bool:
    """Return True when *candidate* is a non-selectable catalog status row."""
    return isinstance(candidate.metadata, DirectiveCatalogPlaceholder)


def clause_needs_agent_snapshot(clause: DirectiveClauseCompletion) -> bool:
    """Return True when live agent rows can appear for *clause*."""
    return clause.is_wait_positional or clause.value_role in {
        "agent",
        *IDENTITY_ROLES,
    }


def clause_needs_bead_inventory(clause: DirectiveClauseCompletion) -> bool:
    """Return True when bead-backed completion should be warmed for *clause*."""
    if clause.value_role == "bead":
        return True
    return clause.directive_name in {"wait", "id"} and clause.syntax_form == (
        "parenthesized"
    )


def clause_needs_finalizer_inventory(clause: DirectiveClauseCompletion) -> bool:
    """Return True when ``%final`` catalog rows should back *clause*."""
    if clause.is_name:
        return False
    return clause.directive_name == "final" or clause.value_role == "finalizer_instance"


def _offers_model_values(clause: DirectiveClauseCompletion) -> bool:
    if clause.directive_name != "model":
        return False
    if clause.value_role == "model":
        return True
    if clause.kind == "directive_argument_keyword":
        return True
    return clause.syntax_form == "parenthesized" and clause.clause_kind == "positional"


def _build_wait_or_agent_clause_candidates(
    clause: DirectiveClauseCompletion,
    agent_candidates: Sequence[AgentCompletionCandidate] | None,
) -> tuple[list[CompletionCandidate], str]:
    keywords = [
        static_or_keyword_candidate(row, clause)
        for row in core_candidate_rows(clause)
        if isinstance(row.get("insertion"), str) and str(row["insertion"]).endswith("=")
    ]
    agents, agent_shared = build_agent_arg_completion_candidates(
        clause.token,
        agent_candidates,
        excluded_names=frozenset(clause.selected_values),
        excluded_kinds=_WAIT_UNSUPPORTED_TARGET_KINDS,
    )
    candidates = [*keywords, *agents]
    if keywords:
        return candidates, ""
    return candidates, agent_shared


__all__ = [
    "BeadCompletionMetadata",
    "BeadsState",
    "DirectiveArgCompletionMetadata",
    "DirectiveCatalogPlaceholder",
    "DirectiveClauseCompletion",
    "DirectiveCompletionMetadata",
    "FinalizerCompletionMetadata",
    "FinalizersState",
    "ModelCompletionMetadata",
    "PathCandidateBuilder",
    "build_agent_arg_completion_candidates",
    "build_directive_clause_candidates",
    "build_directive_completion_candidates",
    "classify_directive_completion",
    "clause_needs_agent_snapshot",
    "clause_needs_bead_inventory",
    "clause_needs_finalizer_inventory",
    "extract_directive_arg_token_around_cursor",
    "extract_directive_token_around_cursor",
    "is_directive_catalog_placeholder",
    "is_directive_like_token",
    "selected_wait_values_around_cursor",
]
