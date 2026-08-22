"""Shared helpers for prompt directive-completion tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets._directive_completion_tokens import (
    _canonical_directive_name,
    synthetic_directive_clause,
)
from sase.ace.tui.widgets.directive_completion import (
    BeadsState,
    DirectiveArgCompletionMetadata,
    DirectiveCompletionMetadata,
    ModelCompletionMetadata,
    PathCandidateBuilder,
    build_directive_clause_candidates,
    build_directive_completion_candidates,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.xprompt.model_completion import _ModelCompletionEntry

_SPECIAL_KEYWORD_NAMES = {
    "clan_keyword": "clan",
    "id_keyword": "id",
    "model_alias_key": "model",
}

MODEL_CATALOG_PATCH = (
    "sase.ace.tui.widgets.directive_completion.build_model_completion_catalog"
)


def build_directive_arg_completion_candidates(
    directive_name: str,
    partial: str,
    *,
    agent_candidates: Sequence[AgentCompletionCandidate] | None = None,
    selected_values: frozenset[str] = frozenset(),
    bead_inventory: Sequence[Mapping[str, str]] | None = None,
    beads_state: BeadsState = "unavailable",
    excluded_bead_ids: Sequence[str] = (),
    finalizer_inventory: Sequence[Mapping[str, object]] | None = None,
    finalizers_state: BeadsState = "unavailable",
    path_candidates: PathCandidateBuilder | None = None,
) -> tuple[list[CompletionCandidate], str]:
    """Build argument rows from a historical name/partial dispatch."""
    clause = _clause_from_dispatch_name(
        directive_name,
        partial,
        selected_values=selected_values,
    )
    if clause is None:
        return [], ""
    return build_directive_clause_candidates(
        clause,
        agent_candidates=agent_candidates,
        bead_inventory=bead_inventory,
        beads_state=beads_state,
        excluded_bead_ids=excluded_bead_ids,
        finalizer_inventory=finalizer_inventory,
        finalizers_state=finalizers_state,
        path_candidates=path_candidates,
    )


def _clause_from_dispatch_name(
    directive_name: str,
    partial: str,
    *,
    selected_values: frozenset[str],
):
    if directive_name == "model_or_alias_key":
        return synthetic_directive_clause(
            kind="directive_argument",
            token=partial,
            directive_name="model",
            syntax_form="parenthesized",
            clause_kind="positional",
            value_role="model",
            selected_values=selected_values,
            selected_keywords=selected_values,
        )
    if directive_name in _SPECIAL_KEYWORD_NAMES:
        return synthetic_directive_clause(
            kind="directive_argument_keyword",
            token=partial,
            directive_name=_SPECIAL_KEYWORD_NAMES[directive_name],
            syntax_form="parenthesized",
            clause_kind="keyword_name",
            selected_values=selected_values,
            selected_keywords=selected_values,
        )
    resolved = _canonical_directive_name(directive_name)
    if resolved is None:
        return None
    selected_keywords = frozenset(
        value.split("=", 1)[0] for value in selected_values if "=" in value
    )
    if resolved == "wait":
        return synthetic_directive_clause(
            kind="directive_argument",
            token=partial,
            directive_name="wait",
            syntax_form="parenthesized",
            clause_kind="positional",
            value_role="agent",
            selected_values=selected_values,
            selected_keywords=selected_keywords,
        )
    if resolved == "model":
        return synthetic_directive_clause(
            kind="directive_argument",
            token=partial,
            directive_name="model",
            syntax_form="colon",
            clause_kind="positional",
            value_role="model",
            selected_values=selected_values,
        )
    return synthetic_directive_clause(
        kind="directive_argument",
        token=partial,
        directive_name=resolved,
        syntax_form="colon",
        clause_kind="positional",
        selected_values=selected_values,
    )


def single_directive_candidate(token: str) -> tuple[CompletionCandidate, str]:
    candidates, shared = build_directive_completion_candidates(token)
    canonical = [
        candidate
        for candidate in candidates
        if isinstance(candidate.metadata, DirectiveCompletionMetadata)
        and not candidate.metadata.is_snippet
    ]
    assert len(canonical) == 1
    return canonical[0], shared


def directive_metadata(
    candidate: CompletionCandidate,
) -> DirectiveCompletionMetadata:
    assert isinstance(candidate.metadata, DirectiveCompletionMetadata)
    return candidate.metadata


def directive_arg_metadata(
    candidate: CompletionCandidate,
) -> DirectiveArgCompletionMetadata:
    assert isinstance(candidate.metadata, DirectiveArgCompletionMetadata)
    return candidate.metadata


def model_metadata(candidate: CompletionCandidate) -> ModelCompletionMetadata:
    assert isinstance(candidate.metadata, ModelCompletionMetadata)
    return candidate.metadata


def model_entries() -> list[_ModelCompletionEntry]:
    return [
        _ModelCompletionEntry(
            value="claude-fable-5",
            display="claude-fable-5",
            description="Claude (fable)",
            provider="claude",
            aliases=("fable",),
        ),
        _ModelCompletionEntry(
            value="gpt-5.6-sol",
            display="gpt-5.6-sol",
            description="Codex (gpt56sol)",
            provider="codex",
            aliases=("gpt56sol",),
        ),
    ]


def model_entries_with_providers() -> list[_ModelCompletionEntry]:
    return [
        *model_entries(),
        _ModelCompletionEntry(
            value="claude/",
            display="claude/",
            description="Claude",
            kind="provider",
            provider="claude",
            provider_model_count=1,
        ),
        _ModelCompletionEntry(
            value="codex/",
            display="codex/",
            description="Codex",
            kind="provider",
            provider="codex",
            provider_model_count=1,
        ),
    ]


def agent_candidate(
    name: str,
    *,
    tribe: str | None = None,
) -> AgentCompletionCandidate:
    return AgentCompletionCandidate(
        name=name,
        label=name,
        status="RUNNING",
        tribe=tribe,
        prompt_snippet=f"{name} prompt",
    )
