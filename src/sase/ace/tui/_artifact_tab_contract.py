"""Compile widget-free Artifacts pane contracts from declared facts.

Built-in facts come from one host-owned adapter table. Provider facts come
only from the normalized schema-v1 ``ref`` declaration. Each closed
:class:`PaneCapability` is decided by a named pure rule that records an
auditable ON/OFF verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any

from sase.ace.query_profile import (
    CompiledQueryProfile,
    compiled_profile_for_builtin_pane,
)

from ._artifact_tab_contract_adapters import (
    BUILTIN_ADAPTERS,
    GENERIC_DOCUMENT_COPY_KEYMAP_GROUP,
    GENERIC_DOCUMENT_COPY_TARGETS,
    PLAN_ADAPTER,
    PLAN_COPY_TARGETS,
    PROVIDER_BUNDLE_RELATION,
)
from ._artifact_tab_contract_provider import (
    REF_CAPABILITIES_CONFIG_KEY,
    REF_CAPABILITIES_SUPPRESS_KEY,
    REF_GROUPING_CONFIG_KEY,
    REF_RELATIONS_CONFIG_KEY,
    extract_provider_grouping,
    extract_provider_relations,
    extract_provider_suppressions,
    provider_detail_fields,
    provider_facts_from_spec,
    provider_kind_slug,
    provider_query_profile,
)
from ._artifact_tab_contract_rules import derive_capability_verdicts
from ._artifact_tab_model import (
    ArtifactsPaneContract,
    ArtifactsTabDescriptor,
    CapabilityVerdict,
    PaneCapability,
    PaneDeclaredFacts,
    PaneEmptyState,
    PaneGroupingDecl,
    PaneRelationDecl,
)


@dataclass(frozen=True, slots=True)
class ContractCompileResult:
    """One compiled contract plus an optional compiler diagnostic."""

    contract: ArtifactsPaneContract
    error: str | None = None
    error_code: str | None = None


def compile_builtin_contract(
    adapter_id: str,
    *,
    label: str,
    icon: str,
    accent: str,
    order: int = 0,
    digit: str | None = None,
) -> ArtifactsPaneContract:
    """Compile the host-owned contract for one built-in adapter."""

    adapter = BUILTIN_ADAPTERS[adapter_id]
    facts = PaneDeclaredFacts(
        source="builtin",
        adapter=adapter.adapter,
        is_degraded=False,
        has_inventory=adapter.has_inventory,
        has_fields=adapter.has_fields,
        has_stable_identity=adapter.has_stable_identity,
        has_revisions=adapter.has_revisions,
        can_mutate=adapter.can_mutate,
        is_plan_adapter=adapter.is_plan_adapter,
        project_scoped=adapter.project_scoped,
        has_detail=adapter.has_detail,
        relations=adapter.relations,
        grouping=adapter.grouping,
        suppressions={},
    )
    query_profile = compiled_profile_for_builtin_pane(adapter.pane_id)
    assert query_profile is not None, (
        f"no compiled profile for pane {adapter.pane_id!r}"
    )
    return _assemble_contract(
        pane_id=adapter.pane_id,
        label=label,
        icon=icon,
        accent=accent,
        order=order,
        digit=digit,
        ref_kind=adapter.ref_kind,
        target_prefix=adapter.target_prefix,
        facts=facts,
        copy_group=adapter.copy_group,
        copy_targets=adapter.copy_targets,
        copy_keymap_group=adapter.copy_keymap_group,
        detail_fields=adapter.detail_fields,
        detail_scroll_id=adapter.detail_scroll_id,
        empty_state=adapter.empty_state,
        relations=adapter.relations,
        grouping=adapter.grouping,
        adapter=adapter.adapter,
        provider_spec_digest=None,
        query_profile=query_profile,
    )


def compile_provider_contract(
    *,
    kind: str,
    label: str,
    icon: str,
    accent: str,
    spec: Mapping[str, Any] | None,
    provider_spec_digest: str | None,
    order: int = 0,
    digit: str | None = None,
    is_degraded: bool = False,
    configured_pane_ids: tuple[str, ...] = (),
) -> ContractCompileResult:
    """Compile a document-provider contract from a normalized schema-v1 spec."""

    suppressions, compiler_error, compiler_code = extract_provider_suppressions(spec)
    if compiler_error is not None:
        is_degraded = True
    relations, relations_error, relations_code = extract_provider_relations(
        kind,
        spec,
        configured_pane_ids=configured_pane_ids,
    )
    if relations_error is not None:
        is_degraded = True
        if compiler_error is None:
            compiler_error = relations_error
            compiler_code = relations_code
    grouping, grouping_error, grouping_code = extract_provider_grouping(spec)
    if grouping_error is not None:
        is_degraded = True
        if compiler_error is None:
            compiler_error = grouping_error
            compiler_code = grouping_code
    if kind == "plan" and not is_degraded:
        relations = relations or PLAN_ADAPTER.relations
        grouping = grouping if grouping.modes else PLAN_ADAPTER.grouping
    elif not is_degraded and kind != "plan":
        if all(item.name != PROVIDER_BUNDLE_RELATION.name for item in relations):
            relations = (*relations, PROVIDER_BUNDLE_RELATION)

    if kind == "plan":
        query_profile = compiled_profile_for_builtin_pane("ref:plan")
        assert query_profile is not None, "no compiled profile for the plan pane"
    else:
        query_profile, profile_error = provider_query_profile(kind, spec)
        if profile_error is not None:
            is_degraded = True
            if compiler_error is None:
                compiler_error = profile_error
                compiler_code = "invalid_query_profile"

    facts = provider_facts_from_spec(
        kind,
        spec,
        is_degraded=is_degraded,
        suppressions=suppressions,
        relations=relations,
        grouping=grouping,
    )
    if facts.is_plan_adapter:
        copy_group = PLAN_ADAPTER.copy_group
        copy_targets = PLAN_ADAPTER.copy_targets
        copy_keymap_group = PLAN_ADAPTER.copy_keymap_group
        empty_state = PaneEmptyState(
            title=f"No {label.lower()}s",
            body=(f"No {label.lower()}s match the current project scope and filters."),
        )
        target_prefix = "plan"
        adapter = "plan"
    else:
        copy_group = f"artifacts_{provider_kind_slug(kind)}"
        copy_targets = GENERIC_DOCUMENT_COPY_TARGETS
        copy_keymap_group = GENERIC_DOCUMENT_COPY_KEYMAP_GROUP
        empty_state = PaneEmptyState(
            title=f"No {label.lower()}s",
            body=(f"No {label.lower()}s match the current project scope and filters."),
        )
        target_prefix = kind
        adapter = None
    if is_degraded:
        empty_state = PaneEmptyState(
            title=f"{label} unavailable",
            body=compiler_error or "This document provider failed to load.",
        )
        copy_targets = ()
    detail_fields = provider_detail_fields(spec)
    contract = _assemble_contract(
        pane_id=f"ref:{kind}",
        label=label,
        icon=icon,
        accent=accent,
        order=order,
        digit=digit,
        ref_kind=kind,
        target_prefix=target_prefix,
        facts=facts,
        copy_group=copy_group,
        copy_targets=copy_targets,
        copy_keymap_group=copy_keymap_group,
        detail_fields=detail_fields,
        detail_scroll_id="plans-detail-scroll",
        empty_state=empty_state,
        relations=facts.relations,
        grouping=facts.grouping,
        adapter=adapter,
        provider_spec_digest=provider_spec_digest,
        query_profile=query_profile,
    )
    return ContractCompileResult(
        contract=contract,
        error=compiler_error,
        error_code=compiler_code,
    )


def contract_with_digit(
    contract: ArtifactsPaneContract,
    *,
    digit: str | None,
    order: int,
) -> ArtifactsPaneContract:
    """Return a copy with digit/order synchronized and digest refreshed."""

    updated = replace(contract, digit=digit, order=order)
    return replace(updated, presentation_digest=_presentation_digest(updated))


def attach_contract(
    descriptor: ArtifactsTabDescriptor,
    contract: ArtifactsPaneContract,
) -> ArtifactsTabDescriptor:
    """Attach *contract* without letting envelope fields drift from it."""

    return replace(
        descriptor,
        label=contract.label,
        icon=contract.icon,
        accent=contract.accent,
        digit_shortcut=contract.digit,
        contract=contract,
    )


def _presentation_digest(contract: ArtifactsPaneContract) -> str:
    """Stable digest of host presentation inputs plus later-phase empties."""

    payload = {
        "id": contract.id,
        "label": contract.label,
        "icon": contract.icon,
        "accent": contract.accent,
        "order": contract.order,
        "digit": contract.digit,
        "ref_kind": contract.ref_kind,
        "target_prefix": contract.target_prefix,
        "project_scoping": contract.project_scoping,
        "copy_group": contract.copy_group,
        "copy_targets": list(contract.copy_targets),
        "detail_fields": list(contract.detail_fields),
        "detail_scroll_id": contract.detail_scroll_id,
        "empty_state": {
            "title": contract.empty_state.title,
            "body": contract.empty_state.body,
        },
        "query_profile_digest": contract.query_profile.digest,
        "relations": [item.to_payload() for item in contract.relations],
        "grouping": contract.grouping.to_payload(),
        "status_counters": [
            {"name": item.name, "field": item.field}
            for item in contract.status_counters
        ],
        "capabilities": sorted(item.value for item in contract.capabilities),
        "verdicts": [item.to_payload() for item in contract.verdicts],
        "provider_spec_digest": contract.facts.to_payload().get("source"),
        "facts": contract.facts.to_payload(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _presentation_digest_for(
    *,
    pane_id: str,
    label: str,
    icon: str,
    accent: str,
    order: int,
    digit: str | None,
    ref_kind: str | None,
    target_prefix: str,
    provider_spec_digest: str | None,
    copy_group: str,
    copy_targets: tuple[str, ...],
    detail_fields: tuple[str, ...],
    verdicts: tuple[CapabilityVerdict, ...],
    facts: PaneDeclaredFacts,
    empty_state: PaneEmptyState,
    detail_scroll_id: str | None,
    query_profile: CompiledQueryProfile,
    relations: tuple[PaneRelationDecl, ...],
    grouping: PaneGroupingDecl,
) -> str:
    """Digest host presentation plus the provider spec digest."""

    payload = {
        "id": pane_id,
        "label": label,
        "icon": icon,
        "accent": accent,
        "order": order,
        "digit": digit,
        "ref_kind": ref_kind,
        "target_prefix": target_prefix,
        "copy_group": copy_group,
        "copy_targets": list(copy_targets),
        "detail_fields": list(detail_fields),
        "detail_scroll_id": detail_scroll_id,
        "empty_state": {"title": empty_state.title, "body": empty_state.body},
        "query_profile_digest": query_profile.digest,
        "relations": [item.to_payload() for item in relations],
        "grouping": grouping.to_payload(),
        "status_counters": [],
        "verdicts": [item.to_payload() for item in verdicts],
        "facts": facts.to_payload(),
        "provider_spec_digest": provider_spec_digest or "",
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assemble_contract(
    *,
    pane_id: str,
    label: str,
    icon: str,
    accent: str,
    order: int,
    digit: str | None,
    ref_kind: str | None,
    target_prefix: str,
    facts: PaneDeclaredFacts,
    copy_group: str,
    copy_targets: tuple[str, ...],
    copy_keymap_group: str,
    detail_fields: tuple[str, ...],
    detail_scroll_id: str | None,
    empty_state: PaneEmptyState,
    relations: tuple[PaneRelationDecl, ...],
    grouping: PaneGroupingDecl,
    adapter: str | None,
    provider_spec_digest: str | None,
    query_profile: CompiledQueryProfile,
) -> ArtifactsPaneContract:
    verdicts = derive_capability_verdicts(facts)
    enabled = frozenset(item.capability for item in verdicts if item.enabled)
    digest = _presentation_digest_for(
        pane_id=pane_id,
        label=label,
        icon=icon,
        accent=accent,
        order=order,
        digit=digit,
        ref_kind=ref_kind,
        target_prefix=target_prefix,
        provider_spec_digest=provider_spec_digest,
        copy_group=copy_group,
        copy_targets=copy_targets,
        detail_fields=detail_fields,
        verdicts=verdicts,
        facts=facts,
        empty_state=empty_state,
        detail_scroll_id=detail_scroll_id,
        query_profile=query_profile,
        relations=relations,
        grouping=grouping,
    )
    return ArtifactsPaneContract(
        id=pane_id,
        label=label,
        icon=icon,
        accent=accent,
        order=order,
        digit=digit,
        ref_kind=ref_kind,
        target_prefix=target_prefix,
        project_scoping=PaneCapability.PROJECT_SCOPE in enabled,
        presentation_digest=digest,
        capabilities=enabled,
        verdicts=verdicts,
        query_profile=query_profile,
        relations=relations,
        grouping=grouping,
        detail_fields=detail_fields,
        status_counters=(),
        empty_state=empty_state,
        copy_group=copy_group,
        copy_targets=copy_targets,
        facts=facts,
        detail_scroll_id=detail_scroll_id,
        copy_keymap_group=copy_keymap_group or copy_group,
        adapter=adapter,
    )


__all__ = [
    "BUILTIN_ADAPTERS",
    "GENERIC_DOCUMENT_COPY_KEYMAP_GROUP",
    "GENERIC_DOCUMENT_COPY_TARGETS",
    "PLAN_ADAPTER",
    "PLAN_COPY_TARGETS",
    "PROVIDER_BUNDLE_RELATION",
    "REF_CAPABILITIES_CONFIG_KEY",
    "REF_CAPABILITIES_SUPPRESS_KEY",
    "REF_GROUPING_CONFIG_KEY",
    "REF_RELATIONS_CONFIG_KEY",
    "ContractCompileResult",
    "attach_contract",
    "compile_builtin_contract",
    "compile_provider_contract",
    "contract_with_digit",
]
