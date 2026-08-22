"""ACE surface normalization for directive completion parity tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.widgets.directive_completion import (
    BeadCompletionMetadata,
    DirectiveArgCompletionMetadata,
    DirectiveCatalogPlaceholder,
    DirectiveCompletionMetadata,
    FinalizerCompletionMetadata,
    FinalizersState,
    ModelCompletionMetadata,
    build_directive_clause_candidates,
    classify_directive_completion,
)
from sase.xprompt.model_completion import _ModelCompletionEntry
from tests._xprompt_directive_completion_parity_helpers import _FINALIZER_ROWS
from tests._xprompt_directive_completion_parity_lsp import (
    LspSession,
    LspSurfaceRow,
    SurfaceRow,
    _surface_rows,
)

MODEL_CATALOG_PATCH = (
    "sase.ace.tui.widgets.directive_completion.build_model_completion_catalog"
)
MODEL_ALIAS_NAMES_PATCH = "sase.llm_provider.config.model_alias_names"
MODEL_ALIAS_DESCRIPTION_PATCH = "sase.llm_provider.config.model_alias_description"
_AGENT_ROWS = (
    AgentCompletionCandidate("planner", "planner", "RUNNING"),
    AgentCompletionCandidate("coder", "coder", "RUNNING"),
    AgentCompletionCandidate("review", "review", "RUNNING", kind="clan"),
    AgentCompletionCandidate("ship", "ship", "RUNNING", kind="family"),
    AgentCompletionCandidate("@builders", "builders", "RUNNING", kind="tribe"),
)
_BEAD_ROWS = (
    {
        "id": "sase-a",
        "title": "Active bug",
        "status": "in_progress",
        "type_label": "task",
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-20T12:00:00Z",
        "task_type": "bug",
        "project": "sase",
    },
)


def _ace_and_lsp_rows(
    tmp_path: Path,
    text: str,
    *,
    finalizer_inventory: Sequence[Mapping[str, object]] = _FINALIZER_ROWS,
    finalizers_state: FinalizersState = "warm",
    helper: Path | None = None,
) -> tuple[list[SurfaceRow], list[LspSurfaceRow]]:
    ace_rows = _ace_clause_rows(
        text,
        finalizer_inventory=finalizer_inventory,
        finalizers_state=finalizers_state,
    )
    with LspSession(
        tmp_path,
        helper=helper,
        finalizer_catalog=None if helper is not None else finalizer_inventory,
    ) as lsp:
        lsp_rows = lsp.complete(text)
    return ace_rows, lsp_rows


def _ace_clause_rows(
    text: str,
    *,
    finalizer_inventory: Sequence[Mapping[str, object]] = _FINALIZER_ROWS,
    finalizers_state: FinalizersState = "warm",
) -> list[SurfaceRow]:
    clause = classify_directive_completion(text, len(text))
    assert clause is not None
    candidates, _shared = build_directive_clause_candidates(
        clause,
        agent_candidates=_AGENT_ROWS,
        bead_inventory=_BEAD_ROWS,
        beads_state="warm",
        finalizer_inventory=finalizer_inventory,
        finalizers_state=finalizers_state,
    )
    return _ace_surface_rows(candidates)


def _ace_surface_rows(candidates: Iterable[Any]) -> list[SurfaceRow]:
    rows: list[SurfaceRow] = []
    for candidate in candidates:
        metadata = candidate.metadata
        documentation = ""
        detail = ""
        if isinstance(metadata, DirectiveCompletionMetadata):
            documentation = metadata.description
            if metadata.aliases:
                detail = f"alias %{metadata.aliases[0]}"
        elif isinstance(metadata, DirectiveArgCompletionMetadata):
            documentation = metadata.description
            detail = "keyword" if candidate.insertion.endswith("=") else ""
        elif isinstance(metadata, AgentCompletionCandidate):
            detail = metadata.status
            if metadata.kind != "agent":
                detail = metadata.kind
        elif isinstance(metadata, BeadCompletionMetadata):
            documentation = metadata.documentation
            detail = " · ".join(
                part
                for part in (
                    metadata.status,
                    metadata.type_label,
                    metadata.task_type,
                )
                if part
            )
        elif isinstance(metadata, ModelCompletionMetadata):
            documentation = _model_documentation(metadata)
            detail = _model_detail(metadata)
        elif isinstance(metadata, FinalizerCompletionMetadata):
            documentation = metadata.documentation
            detail = _finalizer_surface_detail(
                kind=metadata.kind,
                status=metadata.status,
                provider=metadata.provider,
            )
        elif isinstance(metadata, DirectiveCatalogPlaceholder):
            documentation = metadata.message
            detail = metadata.kind
        rows.append(
            SurfaceRow(
                label=candidate.display,
                insertion=candidate.insertion,
                documentation=documentation,
                detail=detail,
            )
        )
    return rows


def _model_detail(metadata: ModelCompletionMetadata) -> str:
    if metadata.kind not in {"implicit_alias", "user_alias"}:
        return metadata.provider
    if metadata.target_provider and metadata.target_model:
        target = f"{metadata.target_provider.upper()}({metadata.target_model})"
    elif metadata.target_model:
        target = metadata.target_model
    else:
        target = metadata.target_provider.upper()
    if target and metadata.target_effort:
        target = f"{target} @ {metadata.target_effort}"
    if target:
        return target
    return "  ".join(part for part in (metadata.provider, metadata.description) if part)


def _model_documentation(metadata: ModelCompletionMetadata) -> str:
    sections = []
    if metadata.description:
        sections.append(metadata.description)
    if metadata.provenance:
        provenance = metadata.provenance
        if metadata.reference:
            provenance = f"{provenance} → @{metadata.reference.lstrip('@')}"
            if metadata.reference_effort:
                provenance = f"{provenance} @ {metadata.reference_effort}"
        sections.append(f"**Provenance:** {provenance}")
    if metadata.config_source:
        alias = metadata.value.lstrip("@")
        sections.append(
            f"**Config:** `llm_provider.model_aliases.{metadata.config_source}.{alias}`"
        )
    return "\n\n".join(sections)


def _model_entries() -> list[_ModelCompletionEntry]:
    return [
        _ModelCompletionEntry(
            value="claude-fable-5",
            display="claude-fable-5",
            description="Claude (fable)",
            provider="claude",
            aliases=("fable",),
        ),
        _ModelCompletionEntry(
            value="@medium",
            display="@medium",
            description="Medium phase worker model.",
            kind="implicit_alias",
            aliases=("medium",),
            alias_kind="role",
            target_provider="claude",
            target_model="claude-fable-5",
            target_effort="high",
            provenance="configured",
        ),
    ]


def _model_alias_description(alias: str) -> str:
    assert alias == "medium"
    return "Medium phase worker model."


def _finalizer_surface_detail(*, kind: str, status: str, provider: str) -> str:
    if kind == "finalizer_remove":
        head = f"remove · {provider}" if provider else "remove"
    elif kind == "finalizer_clear":
        head = "clear"
    else:
        head = provider
    if status and status not in head.split(" · "):
        return f"{head} · {status}" if head else status
    return head


def _selectable_surface_rows(rows: Iterable[SurfaceRow]) -> list[SurfaceRow]:
    return _surface_rows(row for row in rows if row.insertion)
