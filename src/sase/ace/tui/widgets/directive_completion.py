"""ACE adapters over the shared ``sase_core_rs`` directive completion contract."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Literal, Protocol

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    filter_agent_completion_candidates,
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
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.core.rust import require_rust_binding
from sase.llm_provider.provider_disable_peek import peek_active_provider_disables
from sase.llm_provider.temporary_override import peek_active_alias_overrides
from sase.xprompt.model_completion import (
    build_model_completion_catalog,
    filter_model_completion_entries,
)

BeadsState = Literal["warm", "loading", "unavailable"]
FinalizersState = BeadsState
PathCandidateBuilder = Callable[[str], tuple[list[CompletionCandidate], str]]
_FINALIZER_KINDS = frozenset({"finalizer", "finalizer_remove", "finalizer_clear"})


@dataclass(frozen=True, slots=True)
class DirectiveCompletionMetadata:
    """Display metadata for a prompt directive completion candidate."""

    aliases: tuple[str, ...] = ()
    argument_hint: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class DirectiveArgCompletionMetadata:
    """Display metadata for a prompt directive argument completion candidate."""

    directive_name: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class ModelCompletionMetadata:
    """Display metadata for an enriched ``%model`` completion row."""

    value: str
    kind: str
    alias_kind: str = ""
    provider: str = ""
    provider_display: str = ""
    short_alias: str = ""
    target_provider: str = ""
    target_model: str = ""
    target_effort: str = ""
    provenance: str = ""
    reference: str = ""
    reference_effort: str = ""
    pool_available: int = 0
    pool_total: int = 0
    description: str = ""
    config_source: str = ""
    provider_model_count: int = 0


@dataclass(frozen=True, slots=True)
class BeadCompletionMetadata:
    """Display metadata for an open-bead directive value row."""

    bead_id: str
    title: str = ""
    status: str = ""
    type_label: str = ""
    task_type: str = ""
    project: str = ""
    created_at: str = ""
    documentation: str = ""


@dataclass(frozen=True, slots=True)
class FinalizerCompletionMetadata:
    """Display metadata for a ``%final`` selector completion row."""

    value: str
    kind: str
    status: str = ""
    provider: str = ""
    documentation: str = ""

    @property
    def state_label(self) -> str:
        """Accessible policy or operation label, independent of color."""
        if self.kind == "finalizer_remove":
            return "remove"
        if self.kind == "finalizer_clear":
            return "clear"
        if self.status in {"required", "default", "optional", "clear"}:
            return self.status
        return "optional"


@dataclass(frozen=True, slots=True)
class DirectiveCatalogPlaceholder:
    """Non-selectable loading or unavailable dynamic-catalog row."""

    kind: Literal["loading", "unavailable"]
    message: str
    catalog: Literal["beads", "finalizers"] = "beads"


class _ModelEntryDisplay(Protocol):
    """Catalog scalars used to recover the provider's display label."""

    @property
    def kind(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def aliases(self) -> tuple[str, ...]: ...


_TARGET_KIND_ORDER = ("tribe", "clan", "family", "agent")
_IDENTITY_ROLES = frozenset({"clan", "family", "tribe"})
_HIDDEN_COMPLETION_DIRECTIVES = frozenset({"final"})


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
        _directive_name_candidate(row)
        for row in _core_candidate_rows(clause)
        if isinstance(row.get("insertion"), str) and not _is_hidden_directive_name(row)
    ]
    return candidates, _shared_extension(
        [candidate.insertion[1:] for candidate in candidates],
        token[1:],
    )


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
        return _build_model_clause_candidates(clause)

    keyword_fallback = _parenthesized_keyword_fallback(clause)
    if keyword_fallback is not None:
        return keyword_fallback

    if clause_needs_finalizer_inventory(clause):
        return _build_finalizer_clause_candidates(
            clause,
            finalizer_inventory=finalizer_inventory,
            finalizers_state=finalizers_state,
        )

    if clause.value_role == "bead":
        return _build_bead_clause_candidates(
            clause,
            bead_inventory=bead_inventory,
            beads_state=beads_state,
            excluded_bead_ids=excluded_bead_ids,
        )

    if clause.value_role in _IDENTITY_ROLES:
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
        _static_or_keyword_candidate(row, clause)
        for row in _core_candidate_rows(
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
    return candidates, _shared_extension(
        [candidate.insertion for candidate in candidates],
        clause.token,
    )


def build_agent_arg_completion_candidates(
    partial: str,
    agent_candidates: Sequence[AgentCompletionCandidate] | None,
    *,
    excluded_names: frozenset[str] = frozenset(),
    required_kind: str | None = None,
) -> tuple[list[CompletionCandidate], str]:
    """Build kind-aware target candidates for a wait/fork/identity argument."""
    if "=" in partial:
        return [], ""

    partial_lower = partial.lower()
    source_entries = list(agent_candidates or ())
    source_entries = [*_derived_tribe_entries(source_entries), *source_entries]
    if required_kind is not None:
        source_entries = [
            entry for entry in source_entries if entry.kind == required_kind
        ]
    excluded = {name.casefold() for name in excluded_names}
    matching = [
        entry
        for entry in filter_agent_completion_candidates(source_entries, partial)
        if not _target_is_excluded(entry, excluded)
    ]
    ordered = [
        entry for kind in _TARGET_KIND_ORDER for entry in matching if entry.kind == kind
    ]
    candidates: list[CompletionCandidate] = []
    seen_insertions: set[str] = set()
    for entry in ordered:
        if entry.name in seen_insertions:
            continue
        seen_insertions.add(entry.name)
        candidates.append(
            CompletionCandidate(
                display=entry.name,
                insertion=entry.name,
                is_dir=False,
                name=entry.name,
                metadata=entry,
            )
        )

    shared_extension = ""
    if len(candidates) > 1 and all(
        candidate.insertion.lower().startswith(partial_lower)
        for candidate in candidates
    ):
        shared_extension = _shared_extension(
            [candidate.insertion for candidate in candidates],
            partial,
        )
    return candidates, shared_extension


def is_directive_catalog_placeholder(candidate: CompletionCandidate) -> bool:
    """Return True when *candidate* is a non-selectable catalog status row."""
    return isinstance(candidate.metadata, DirectiveCatalogPlaceholder)


def clause_needs_agent_snapshot(clause: DirectiveClauseCompletion) -> bool:
    """Return True when live agent rows can appear for *clause*."""
    return clause.is_wait_positional or clause.value_role in {
        "agent",
        *_IDENTITY_ROLES,
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


@cache
def _directive_contract_by_name() -> dict[str, dict[str, object]]:
    entries: dict[str, dict[str, object]] = {}
    for entry in require_rust_binding("directive_contract")():
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            entries[str(entry["name"])] = entry
    return entries


def _offers_model_values(clause: DirectiveClauseCompletion) -> bool:
    if clause.directive_name != "model":
        return False
    if clause.value_role == "model":
        return True
    if clause.kind == "directive_argument_keyword":
        return True
    return clause.syntax_form == "parenthesized" and clause.clause_kind == "positional"


def _build_model_clause_candidates(
    clause: DirectiveClauseCompletion,
) -> tuple[list[CompletionCandidate], str]:
    if clause.kind == "directive_argument_keyword":
        return _build_model_alias_key_completion_candidates(
            clause.token,
            selected_keywords=clause.selected_keywords,
        )
    models, shared = _build_model_arg_completion_candidates(clause.token)
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


def _model_insertion_is_self_ref(insertion: str, keyword: str) -> bool:
    return insertion.lstrip("@").casefold() == keyword.lstrip("@").casefold()


def _build_bead_clause_candidates(
    clause: DirectiveClauseCompletion,
    *,
    bead_inventory: Sequence[Mapping[str, str]] | None,
    beads_state: BeadsState,
    excluded_bead_ids: Sequence[str],
) -> tuple[list[CompletionCandidate], str]:
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

    rows = _core_candidate_rows(
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


def _build_wait_or_agent_clause_candidates(
    clause: DirectiveClauseCompletion,
    agent_candidates: Sequence[AgentCompletionCandidate] | None,
) -> tuple[list[CompletionCandidate], str]:
    keywords = [
        _static_or_keyword_candidate(row, clause)
        for row in _core_candidate_rows(clause)
        if isinstance(row.get("insertion"), str) and str(row["insertion"]).endswith("=")
    ]
    agents, agent_shared = build_agent_arg_completion_candidates(
        clause.token,
        agent_candidates,
        excluded_names=frozenset(clause.selected_values),
    )
    candidates = [*keywords, *agents]
    if keywords:
        return candidates, ""
    return candidates, agent_shared


def _build_finalizer_clause_candidates(
    clause: DirectiveClauseCompletion,
    *,
    finalizer_inventory: Sequence[Mapping[str, object]] | None,
    finalizers_state: FinalizersState,
) -> tuple[list[CompletionCandidate], str]:
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

    rows = _core_candidate_rows(
        clause,
        finalizer_inventory=finalizer_inventory or (),
    )
    candidates = [
        _finalizer_candidate(row)
        for row in rows
        if isinstance(row.get("insertion"), str)
        and str(row.get("kind") or "") in _FINALIZER_KINDS
    ]
    return candidates, _shared_extension(
        [candidate.insertion for candidate in candidates],
        clause.token,
    )


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


def _core_candidate_rows(
    clause: DirectiveClauseCompletion,
    *,
    bead_inventory: Sequence[Mapping[str, str]] | None = None,
    excluded_bead_ids: Sequence[str] = (),
    finalizer_inventory: Sequence[Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    inventories: dict[str, object] = {
        "models": [],
        "model_alias_keys": [],
        "agents": [],
        "beads": [dict(entry) for entry in bead_inventory or ()],
        "finalizers": [dict(entry) for entry in finalizer_inventory or ()],
        "excluded_bead_ids": list(excluded_bead_ids),
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


def _directive_name_candidate(row: dict[str, object]) -> CompletionCandidate:
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


def _is_hidden_directive_name(row: dict[str, object]) -> bool:
    insertion = str(row.get("insertion") or "")
    name = str(row.get("name") or insertion.removeprefix("%"))
    return name in _HIDDEN_COMPLETION_DIRECTIVES


def _parenthesized_keyword_fallback(
    clause: DirectiveClauseCompletion,
) -> tuple[list[CompletionCandidate], str] | None:
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
        _static_or_keyword_candidate(row, keyword_clause)
        for row in _core_candidate_rows(keyword_clause)
        if isinstance(row.get("insertion"), str)
        and str(row["insertion"]).lower().startswith(clause.token.lower())
    ]
    return (candidates, "") if candidates else None


def _static_or_keyword_candidate(
    row: dict[str, object],
    clause: DirectiveClauseCompletion,
) -> CompletionCandidate:
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


def _catalog_placeholder(
    kind: Literal["loading", "unavailable"],
    message: str,
    *,
    catalog: Literal["beads", "finalizers"] = "beads",
) -> CompletionCandidate:
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


def _derived_tribe_entries(
    entries: Sequence[AgentCompletionCandidate],
) -> list[AgentCompletionCandidate]:
    """Derive aggregate tribe rows from flat agent completion candidates."""
    explicit = {entry.name for entry in entries if entry.kind == "tribe"}
    members_by_tribe: dict[str, list[AgentCompletionCandidate]] = {}
    for entry in entries:
        if entry.kind != "agent" or not entry.tribe:
            continue
        tribe = entry.tribe if entry.tribe.startswith("@") else f"@{entry.tribe}"
        if tribe in explicit:
            continue
        members_by_tribe.setdefault(tribe, []).append(entry)

    legacy: list[AgentCompletionCandidate] = []
    for tribe, members in members_by_tribe.items():
        statuses = [member.status for member in members]
        from sase.ace.tui.models._agent_clan import aggregate_clan_status

        status = aggregate_clan_status(statuses) or "RUNNING"
        legacy.append(
            AgentCompletionCandidate(
                name=tribe,
                label=tribe.removeprefix("@"),
                status=status,
                kind="tribe",
                member_count=len(members),
                aggregate_status=status,
                member_names=tuple(member.name for member in members),
                agent_count=len(members),
                clan_count=0,
                search_aliases=(tribe.removeprefix("@"),),
            )
        )
    return legacy


def _target_is_excluded(
    entry: AgentCompletionCandidate,
    excluded: set[str],
) -> bool:
    canonical = entry.name.casefold()
    if canonical in excluded:
        return True
    return entry.kind == "tribe" and canonical.removeprefix("@") in excluded


def _build_model_arg_completion_candidates(
    partial: str,
) -> tuple[list[CompletionCandidate], str]:
    """Build dynamic candidates for a ``%model`` directive argument token."""
    entries = filter_model_completion_entries(
        build_model_completion_catalog(
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

    shared_extension = ""
    partial_lower = partial.lower()
    if len(candidates) > 1 and all(
        candidate.insertion.lower().startswith(partial_lower)
        for candidate in candidates
    ):
        shared_extension = _shared_extension(
            [candidate.insertion for candidate in candidates],
            partial,
        )
    return candidates, shared_extension


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
    return candidates, _shared_extension(
        [candidate.insertion for candidate in candidates],
        partial,
    )


def _shared_extension(insertions: Sequence[str], partial: str) -> str:
    if len(insertions) <= 1:
        return ""
    shared_prefix = os.path.commonprefix(list(insertions))
    if len(shared_prefix) > len(partial):
        return shared_prefix[len(partial) :]
    return ""


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
