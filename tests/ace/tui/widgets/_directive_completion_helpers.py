"""Shared helpers for prompt directive-completion tests."""

from __future__ import annotations

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.directive_completion import (
    DirectiveArgCompletionMetadata,
    DirectiveCompletionMetadata,
    ModelCompletionMetadata,
    build_directive_completion_candidates,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.xprompt.model_completion import _ModelCompletionEntry

MODEL_CATALOG_PATCH = (
    "sase.ace.tui.widgets.directive_completion.build_model_completion_catalog"
)


def single_directive_candidate(token: str) -> tuple[CompletionCandidate, str]:
    candidates, shared = build_directive_completion_candidates(token)
    assert len(candidates) == 1
    return candidates[0], shared


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
