"""ACE prompt repo-mention catalog cache helpers."""

from __future__ import annotations

from dataclasses import dataclass

from sase.xprompt.repo_mention_catalog import (
    EditorRepoMentionCatalog,
    EditorRepoMentionCatalogResult,
    editor_repo_mention_catalog_for_project,
)


@dataclass(frozen=True, slots=True)
class PromptRepoMentionContext:
    """A prompt-local project selection for repo-mention semantics."""

    project_ref: str | None
    launch_workspace: str | None


@dataclass(frozen=True, slots=True)
class _PromptRepoMentionLoadResult:
    """One off-thread repo-mention warm result."""

    generation: int
    context: PromptRepoMentionContext
    result: EditorRepoMentionCatalogResult

    @property
    def catalog(self) -> EditorRepoMentionCatalog | None:
        return self.result.catalog

    @property
    def diagnostics(self) -> tuple[str, ...]:
        return self.result.diagnostics


def load_prompt_repo_mention_context(
    context: PromptRepoMentionContext,
    *,
    generation: int,
) -> _PromptRepoMentionLoadResult:
    """Load and compile the repo-mention catalog selected by *context*."""

    result = editor_repo_mention_catalog_for_project(
        context.project_ref,
        launch_workspace=context.launch_workspace,
    )
    return _PromptRepoMentionLoadResult(
        generation=generation,
        context=context,
        result=result,
    )


__all__ = [
    "PromptRepoMentionContext",
    "load_prompt_repo_mention_context",
]
