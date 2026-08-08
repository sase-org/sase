"""ACE prompt glossary catalog cache helpers."""

from __future__ import annotations

from dataclasses import dataclass

from sase.xprompt.glossary_catalog import (
    EditorGlossaryCatalog,
    EditorGlossaryCatalogResult,
    editor_glossary_catalog_for_project,
)


@dataclass(frozen=True, slots=True)
class PromptGlossaryContext:
    """A prompt-local project selection for glossary semantics."""

    project_ref: str | None
    launch_workspace: str | None


@dataclass(frozen=True, slots=True)
class _PromptGlossaryLoadResult:
    """One off-thread glossary warm result."""

    generation: int
    context: PromptGlossaryContext
    result: EditorGlossaryCatalogResult

    @property
    def catalog(self) -> EditorGlossaryCatalog | None:
        return self.result.catalog

    @property
    def diagnostics(self) -> tuple[str, ...]:
        return self.result.diagnostics


def load_prompt_glossary_context(
    context: PromptGlossaryContext,
    *,
    generation: int,
) -> _PromptGlossaryLoadResult:
    """Load and compile the glossary selected by *context*."""

    result = editor_glossary_catalog_for_project(
        context.project_ref,
        launch_workspace=context.launch_workspace,
    )
    return _PromptGlossaryLoadResult(
        generation=generation,
        context=context,
        result=result,
    )


__all__ = [
    "PromptGlossaryContext",
    "load_prompt_glossary_context",
]
