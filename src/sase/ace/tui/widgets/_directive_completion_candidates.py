"""Core-backed and catalog-backed directive completion candidates."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from functools import cache
from typing import Literal

from sase.ace.tui.widgets._directive_completion_tokens import (
    DirectiveClauseCompletion,
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
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.core.rust import require_rust_binding

_FINALIZER_KINDS = frozenset({"finalizer", "finalizer_remove", "finalizer_clear"})


def build_bead_clause_candidates(
    clause: DirectiveClauseCompletion,
    *,
    bead_inventory: Sequence[Mapping[str, str]] | None,
    beads_state: BeadsState,
    excluded_bead_ids: Sequence[str],
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates for a bead-valued directive clause."""
    if beads_state == "loading":
        return [_catalog_placeholder("loading", "loading beads…", catalog="beads")], ""
    if beads_state != "warm":
        return [
            _catalog_placeholder(
                "unavailable",
                "bead store unavailable — type a bead ID",
                catalog="beads",
            )
        ], ""

    rows = core_candidate_rows(
        clause,
        bead_inventory=bead_inventory or (),
        excluded_bead_ids=excluded_bead_ids,
    )
    by_id = {
        str(entry.get("id")): entry
        for entry in (bead_inventory or ())
        if entry.get("id")
    }
    candidates = [
        _bead_candidate(row, by_id.get(str(row.get("insertion") or "")))
        for row in rows
        if isinstance(row.get("insertion"), str)
    ]
    if not candidates:
        return [
            _catalog_placeholder(
                "unavailable",
                "no matching open beads",
                catalog="beads",
            )
        ], ""
    return candidates, ""


def build_finalizer_clause_candidates(
    clause: DirectiveClauseCompletion,
    *,
    finalizer_inventory: Sequence[Mapping[str, object]] | None,
    finalizers_state: FinalizersState,
) -> tuple[list[CompletionCandidate], str]:
    """Build candidates for a finalizer-valued directive clause."""
    if finalizers_state == "loading":
        return [
            _catalog_placeholder(
                "loading",
                "loading finalizers…",
                catalog="finalizers",
            )
        ], ""
    if finalizers_state != "warm":
        return [
            _catalog_placeholder(
                "unavailable",
                "finalizer catalog unavailable — type a selector",
                catalog="finalizers",
            )
        ], ""

    rows = core_candidate_rows(
        clause,
        finalizer_inventory=finalizer_inventory or (),
    )
    candidates = [
        _finalizer_candidate(row)
        for row in rows
        if isinstance(row.get("insertion"), str)
        and str(row.get("kind") or "") in _FINALIZER_KINDS
    ]
    return candidates, shared_extension(
        [candidate.insertion for candidate in candidates],
        clause.token,
    )


def core_candidate_rows(
    clause: DirectiveClauseCompletion,
    *,
    bead_inventory: Sequence[Mapping[str, str]] | None = None,
    excluded_bead_ids: Sequence[str] = (),
    finalizer_inventory: Sequence[Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    """Return Rust completion rows for an ACE directive clause."""
    inventories: dict[str, object] = {
        "models": [],
        "model_alias_keys": [],
        "agents": [],
        "beads": [dict(entry) for entry in bead_inventory or ()],
        "finalizers": [dict(entry) for entry in finalizer_inventory or ()],
        "excluded_bead_ids": list(excluded_bead_ids),
        "enabled_feature_flags": _enabled_feature_flags(),
    }
    payload = require_rust_binding("directive_completion_candidates")(
        clause.raw,
        inventories,
    )
    if not isinstance(payload, dict):
        return []
    rows = payload.get("candidates")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def directive_name_candidate(row: dict[str, object]) -> CompletionCandidate:
    """Adapt a core directive-name row for the ACE completion menu."""
    insertion = str(row["insertion"])
    name = str(row.get("name") or insertion.removeprefix("%"))
    contract = _directive_contract_by_name().get(name, {})
    alias = contract.get("alias")
    aliases = (str(alias),) if isinstance(alias, str) and alias else ()
    argument_hint = contract.get("argument_hint")
    description = contract.get("description") or row.get("documentation") or ""
    return CompletionCandidate(
        display=str(row.get("display") or insertion),
        insertion=insertion,
        is_dir=False,
        name=name,
        metadata=DirectiveCompletionMetadata(
            aliases=aliases,
            argument_hint=str(argument_hint) if argument_hint else "",
            description=str(description),
        ),
    )


def directive_recipe_candidates(token: str) -> list[CompletionCandidate]:
    """Build full-form directive template rows from the shared contract."""
    partial = token.removeprefix("%").lower()
    enabled_flags = frozenset(_enabled_feature_flags())
    candidates: list[CompletionCandidate] = []
    for name, contract in _directive_contract_by_name().items():
        if not _directive_contract_visible(contract, enabled_flags):
            continue
        alias = contract.get("alias")
        aliases = (str(alias),) if isinstance(alias, str) and alias else ()
        recipes = contract.get("recipes")
        if not isinstance(recipes, list):
            continue
        for recipe in recipes:
            if not isinstance(recipe, dict):
                continue
            label = str(recipe.get("label") or "")
            if not label:
                continue
            label_key = label.removeprefix("%").lower()
            if partial and not (
                name.startswith(partial)
                or any(alias.startswith(partial) for alias in aliases)
                or label_key.startswith(partial)
            ):
                continue
            template = str(recipe.get("template") or "")
            plain_text = str(recipe.get("plain_text") or "")
            documentation = str(recipe.get("documentation") or "")
            candidates.append(
                CompletionCandidate(
                    display=label,
                    insertion=plain_text,
                    is_dir=False,
                    name=name,
                    metadata=DirectiveCompletionMetadata(
                        aliases=(),
                        argument_hint=str(contract.get("argument_hint") or ""),
                        description=documentation
                        or str(contract.get("description") or ""),
                        template=template,
                        plain_text=plain_text,
                        is_snippet=bool(template),
                    ),
                )
            )
    return candidates


def parenthesized_keyword_fallback(
    clause: DirectiveClauseCompletion,
) -> tuple[list[CompletionCandidate], str] | None:
    """Offer keyword names where clan/id positional syntax is ambiguous."""
    if (
        clause.kind != "directive_argument"
        or clause.syntax_form != "parenthesized"
        or clause.clause_kind != "positional"
        or clause.directive_name not in {"clan", "id"}
    ):
        return None
    keyword_clause = synthetic_directive_clause(
        kind="directive_argument_keyword",
        token=clause.token,
        directive_name=clause.directive_name,
        syntax_form="parenthesized",
        clause_kind="keyword_name",
        selected_values=clause.selected_values,
        selected_keywords=clause.selected_keywords,
    )
    candidates = [
        static_or_keyword_candidate(row, keyword_clause)
        for row in core_candidate_rows(keyword_clause)
        if isinstance(row.get("insertion"), str)
        and str(row["insertion"]).lower().startswith(clause.token.lower())
    ]
    return (candidates, "") if candidates else None


def static_or_keyword_candidate(
    row: dict[str, object],
    clause: DirectiveClauseCompletion,
) -> CompletionCandidate:
    """Adapt a static value or keyword row for the ACE completion menu."""
    insertion = str(row["insertion"])
    documentation = row.get("documentation") or ""
    return CompletionCandidate(
        display=str(row.get("display") or insertion),
        insertion=insertion,
        is_dir=insertion.endswith("="),
        name=str(row.get("name") or insertion.removesuffix("=")),
        metadata=DirectiveArgCompletionMetadata(
            directive_name=clause.directive_name or "",
            description=str(documentation),
        ),
    )


def _catalog_placeholder(
    kind: Literal["loading", "unavailable"],
    message: str,
    *,
    catalog: Literal["beads", "finalizers"] = "beads",
) -> CompletionCandidate:
    """Build a non-selectable dynamic-catalog status candidate."""
    return CompletionCandidate(
        display=message,
        insertion="",
        is_dir=False,
        name="",
        metadata=DirectiveCatalogPlaceholder(
            kind=kind,
            message=message,
            catalog=catalog,
        ),
    )


def _enabled_feature_flags() -> list[str]:
    from sase.feature_flags.registry import FeatureFlag
    from sase.xprompt.code_value import typed_launch_units_enabled

    if typed_launch_units_enabled():
        return [FeatureFlag.typed_launch_units]
    return []


def _directive_contract_visible(
    contract: Mapping[str, object],
    enabled_flags: frozenset[str],
) -> bool:
    feature_flag = contract.get("feature_flag")
    return not isinstance(feature_flag, str) or feature_flag in enabled_flags


def shared_extension(insertions: Sequence[str], partial: str) -> str:
    """Return the suffix shared by multiple completion insertions."""
    if len(insertions) <= 1:
        return ""
    shared_prefix = os.path.commonprefix(list(insertions))
    if len(shared_prefix) > len(partial):
        return shared_prefix[len(partial) :]
    return ""


@cache
def _directive_contract_by_name() -> dict[str, dict[str, object]]:
    entries: dict[str, dict[str, object]] = {}
    for entry in require_rust_binding("directive_contract")():
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            entries[str(entry["name"])] = entry
    return entries


def _finalizer_candidate(row: dict[str, object]) -> CompletionCandidate:
    insertion = str(row["insertion"])
    kind = str(row.get("kind") or "finalizer")
    status = str(row.get("status") or "")
    provider = str(row.get("detail") or "")
    documentation = str(row.get("documentation") or "")
    return CompletionCandidate(
        display=str(row.get("display") or insertion),
        insertion=insertion,
        is_dir=False,
        name=str(row.get("name") or insertion),
        metadata=FinalizerCompletionMetadata(
            value=insertion,
            kind=kind,
            status=status,
            provider=provider,
            documentation=documentation,
        ),
    )


def _bead_candidate(
    row: dict[str, object],
    inventory: Mapping[str, str] | None,
) -> CompletionCandidate:
    bead_id = str(row["insertion"])
    title = ""
    status = str(row.get("status") or "")
    type_label = ""
    task_type = ""
    project = str(row.get("project") or "")
    created_at = ""
    documentation = str(row.get("documentation") or "")
    if inventory is not None:
        title = str(inventory.get("title") or "")
        status = str(inventory.get("status") or status)
        type_label = str(inventory.get("type_label") or "")
        task_type = str(inventory.get("task_type") or "")
        project = str(inventory.get("project") or project)
        created_at = str(inventory.get("created_at") or "")
        if not documentation:
            documentation = title
    return CompletionCandidate(
        display=str(row.get("display") or bead_id),
        insertion=bead_id,
        is_dir=False,
        name=bead_id,
        metadata=BeadCompletionMetadata(
            bead_id=bead_id,
            title=title,
            status=status,
            type_label=type_label,
            task_type=task_type,
            project=project,
            created_at=created_at,
            documentation=documentation,
        ),
    )
