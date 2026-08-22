"""Model candidates for ACE prompt directive completion."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from sase.ace.tui.widgets._directive_completion_candidates import shared_extension
from sase.ace.tui.widgets._directive_completion_tokens import DirectiveClauseCompletion
from sase.ace.tui.widgets._directive_completion_types import (
    DirectiveArgCompletionMetadata,
    ModelCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.llm_provider.provider_disable_peek import peek_active_provider_disables
from sase.llm_provider.temporary_override import peek_active_alias_overrides
from sase.xprompt.model_completion import filter_model_completion_entries

ModelCatalogBuilder = Callable[..., list[Any]]


class _ModelEntryDisplay(Protocol):
    """Catalog scalars used to recover the provider's display label."""

    @property
    def kind(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def aliases(self) -> tuple[str, ...]: ...


def build_model_clause_candidates(
    clause: DirectiveClauseCompletion,
    *,
    catalog_builder: ModelCatalogBuilder,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates for a model-valued directive clause."""
    if clause.kind == "directive_argument_keyword":
        return _build_model_alias_key_completion_candidates(
            clause.token,
            selected_keywords=clause.selected_keywords,
        )
    models, shared = _build_model_arg_completion_candidates(
        clause.token,
        catalog_builder=catalog_builder,
    )
    if clause.active_keyword:
        models = [
            candidate
            for candidate in models
            if not _model_insertion_is_self_ref(
                candidate.insertion,
                clause.active_keyword,
            )
        ]
    if (
        clause.syntax_form == "parenthesized"
        and clause.clause_kind == "positional"
        and not clause.is_keyword_value
    ):
        aliases, _ = _build_model_alias_key_completion_candidates(
            clause.token,
            selected_keywords=clause.selected_keywords,
        )
        return [*models, *aliases], ""
    return models, shared


def _build_model_arg_completion_candidates(
    partial: str,
    *,
    catalog_builder: ModelCatalogBuilder,
) -> tuple[list[CompletionCandidate], str]:
    entries = filter_model_completion_entries(
        catalog_builder(
            overrides=peek_active_alias_overrides(),
            provider_disables=peek_active_provider_disables(),
        ),
        partial,
    )
    candidates = [
        CompletionCandidate(
            display=entry.display,
            insertion=entry.value,
            is_dir=entry.kind == "provider",
            name=entry.value,
            metadata=ModelCompletionMetadata(
                value=entry.value,
                kind=entry.kind,
                alias_kind=entry.alias_kind,
                provider=entry.provider,
                provider_display=_model_provider_display(entry),
                short_alias=(
                    entry.aliases[0] if entry.kind == "model" and entry.aliases else ""
                ),
                target_provider=entry.target_provider,
                target_model=entry.target_model,
                target_effort=entry.target_effort,
                provenance=entry.provenance,
                reference=entry.reference,
                reference_effort=entry.reference_effort,
                pool_available=entry.pool_available,
                pool_total=entry.pool_total,
                description=entry.description,
                config_source=entry.config_source,
                provider_model_count=entry.provider_model_count,
            ),
        )
        for entry in entries
    ]

    shared = ""
    partial_lower = partial.lower()
    if len(candidates) > 1 and all(
        candidate.insertion.lower().startswith(partial_lower)
        for candidate in candidates
    ):
        shared = shared_extension(
            [candidate.insertion for candidate in candidates],
            partial,
        )
    return candidates, shared


def _build_model_alias_key_completion_candidates(
    partial: str,
    *,
    selected_keywords: Sequence[str] = (),
) -> tuple[list[CompletionCandidate], str]:
    """Build ``alias=`` candidates for parenthesized ``%model`` kwargs."""
    from sase.llm_provider.config import model_alias_description, model_alias_names

    partial_lower = partial.lower()
    selected = {
        value.split("=", 1)[0].casefold() if "=" in value else value.casefold()
        for value in selected_keywords
    }
    candidates = [
        CompletionCandidate(
            display=f"{alias}=",
            insertion=f"{alias}=",
            is_dir=True,
            name=alias,
            metadata=DirectiveArgCompletionMetadata(
                directive_name="model",
                description=model_alias_description(alias) or "model alias override",
            ),
        )
        for alias in sorted(model_alias_names())
        if alias.lower().startswith(partial_lower) and alias.casefold() not in selected
    ]
    return candidates, shared_extension(
        [candidate.insertion for candidate in candidates],
        partial,
    )


def _model_provider_display(entry: _ModelEntryDisplay) -> str:
    """Extract the provider display label retained in a model entry."""
    if entry.kind == "provider":
        return entry.description
    if entry.kind != "model":
        return ""
    if not entry.aliases:
        return entry.description
    suffix = f" ({entry.aliases[0]})"
    return entry.description.removesuffix(suffix)


def _model_insertion_is_self_ref(insertion: str, keyword: str) -> bool:
    return insertion.lstrip("@").casefold() == keyword.lstrip("@").casefold()
