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
import re
from typing import Any

from ._artifact_tab_contract_rules import derive_capability_verdicts
from ._artifact_tab_model import (
    ArtifactsPaneContract,
    ArtifactsTabDescriptor,
    CapabilityVerdict,
    PaneCapability,
    PaneDeclaredFacts,
    PaneEmptyState,
    PaneGroupingDecl,
    PaneQuerySchema,
)


REF_CAPABILITIES_CONFIG_KEY = "capabilities"
REF_CAPABILITIES_SUPPRESS_KEY = "suppress"

GENERIC_DOCUMENT_COPY_TARGETS: tuple[str, ...] = (
    "reference",
    "link",
    "path",
    "title",
    "body",
    "json",
    "handoff",
    "snapshot",
)
PLAN_COPY_TARGETS: tuple[str, ...] = (
    "bead_id",
    "reference",
    "handoff",
    "design",
    "path",
    "title",
    "body",
    "link",
    "json",
    "snapshot",
)
GENERIC_DOCUMENT_COPY_KEYMAP_GROUP = "artifacts_documents"

_REVISION_PROPERTY_NAMES = frozenset({"revision", "version", "rev"})


@dataclass(frozen=True, slots=True)
class _BuiltinAdapter:
    """Host-owned fact table for one built-in Artifacts adapter."""

    adapter: str
    pane_id: str
    ref_kind: str | None
    target_prefix: str
    has_inventory: bool
    has_fields: bool
    has_stable_identity: bool
    has_revisions: bool
    can_mutate: bool
    is_plan_adapter: bool
    project_scoped: bool
    has_detail: bool
    copy_group: str
    copy_targets: tuple[str, ...]
    copy_keymap_group: str
    detail_fields: tuple[str, ...]
    detail_scroll_id: str | None
    empty_state: PaneEmptyState


BUILTIN_ADAPTERS: dict[str, _BuiltinAdapter] = {
    "stitches": _BuiltinAdapter(
        adapter="stitches",
        pane_id="stitches",
        ref_kind=None,
        target_prefix="commit",
        has_inventory=True,
        has_fields=True,
        has_stable_identity=True,
        has_revisions=False,
        can_mutate=False,
        is_plan_adapter=False,
        project_scoped=True,
        has_detail=True,
        copy_group="artifacts_stitches",
        copy_targets=(
            "snapshot",
            "reference",
            "handoff",
            "link",
            "json",
            "sha",
            "message",
            "repo_sha",
            "plan",
        ),
        copy_keymap_group="artifacts_stitches",
        detail_fields=(),
        detail_scroll_id="stitches-detail-scroll",
        empty_state=PaneEmptyState(
            title="No stitches",
            body="No commits match the current project scope and filters.",
        ),
    ),
    "patches": _BuiltinAdapter(
        adapter="patches",
        pane_id="patches",
        ref_kind=None,
        target_prefix="patch",
        has_inventory=True,
        has_fields=True,
        has_stable_identity=True,
        has_revisions=False,
        can_mutate=True,
        is_plan_adapter=False,
        project_scoped=False,
        has_detail=True,
        copy_group="patches",
        copy_targets=(
            "raw",
            "with_snapshot",
            "bug",
            "pr_number",
            "name",
            "link",
            "spec",
            "reference",
            "snapshot",
        ),
        copy_keymap_group="patches",
        detail_fields=(),
        detail_scroll_id="detail-scroll",
        empty_state=PaneEmptyState(
            title="No patches",
            body="No patches match the current query.",
        ),
    ),
    "beads": _BuiltinAdapter(
        adapter="beads",
        pane_id="beads",
        ref_kind=None,
        target_prefix="bead",
        has_inventory=True,
        has_fields=True,
        has_stable_identity=True,
        has_revisions=False,
        can_mutate=True,
        is_plan_adapter=False,
        project_scoped=True,
        has_detail=True,
        copy_group="artifacts_beads",
        copy_targets=(
            "snapshot",
            "reference",
            "handoff",
            "link",
            "json",
            "id",
            "title",
            "body",
            "design",
        ),
        copy_keymap_group="artifacts_beads",
        detail_fields=(),
        detail_scroll_id="beads-detail-scroll",
        empty_state=PaneEmptyState(
            title="No beads",
            body="No beads match the current project scope and filters.",
        ),
    ),
    "files": _BuiltinAdapter(
        adapter="files",
        pane_id="files",
        ref_kind=None,
        target_prefix="file",
        has_inventory=True,
        has_fields=True,
        has_stable_identity=True,
        has_revisions=True,
        can_mutate=False,
        is_plan_adapter=False,
        project_scoped=True,
        has_detail=True,
        copy_group="artifacts_other",
        copy_targets=(
            "snapshot",
            "reference",
            "handoff",
            "link",
            "json",
            "contents",
            "path",
            "source",
            "label",
        ),
        copy_keymap_group="artifacts_other",
        detail_fields=(),
        detail_scroll_id="files-detail-scroll",
        empty_state=PaneEmptyState(
            title="No artifact files",
            body="No artifact files match the current project scope and filters.",
        ),
    ),
}

PLAN_ADAPTER = _BuiltinAdapter(
    adapter="plan",
    pane_id="ref:plan",
    ref_kind="plan",
    target_prefix="plan",
    has_inventory=True,
    has_fields=True,
    has_stable_identity=True,
    has_revisions=False,
    can_mutate=False,
    is_plan_adapter=True,
    project_scoped=True,
    has_detail=True,
    copy_group="artifacts_plans",
    copy_targets=PLAN_COPY_TARGETS,
    copy_keymap_group="artifacts_plans",
    detail_fields=("tier", "title", "status"),
    detail_scroll_id="plans-detail-scroll",
    empty_state=PaneEmptyState(
        title="No plans",
        body="No plans match the current project scope and filters.",
    ),
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
        suppressions={},
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
        adapter=adapter.adapter,
        provider_spec_digest=None,
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
) -> ContractCompileResult:
    """Compile a document-provider contract from a normalized schema-v1 spec."""

    suppressions, compiler_error, compiler_code = _extract_provider_suppressions(spec)
    if compiler_error is not None:
        is_degraded = True
    facts = _provider_facts_from_spec(
        kind,
        spec,
        is_degraded=is_degraded,
        suppressions=suppressions,
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
        copy_group = f"artifacts_{_slug(kind)}"
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
    detail_fields = _detail_fields_from_spec(spec)
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
        adapter=adapter,
        provider_spec_digest=provider_spec_digest,
    )
    return ContractCompileResult(
        contract=contract,
        error=compiler_error,
        error_code=compiler_code,
    )


def _extract_provider_suppressions(
    spec: Mapping[str, Any] | None,
) -> tuple[dict[str, str], str | None, str | None]:
    """Validate ``ref.capabilities`` and return suppressions or a diagnostic."""

    ref = _ref_mapping(spec)
    if ref is None or REF_CAPABILITIES_CONFIG_KEY not in ref:
        return {}, None, None
    raw = ref.get(REF_CAPABILITIES_CONFIG_KEY)
    if not isinstance(raw, Mapping):
        return (
            {},
            "ref.capabilities must be a mapping of suppressions",
            "invalid_ref_capabilities",
        )
    unknown_top = sorted(
        str(key) for key in raw if str(key) != REF_CAPABILITIES_SUPPRESS_KEY
    )
    if unknown_top:
        return (
            {},
            (
                "providers may not assert capabilities; unknown "
                f"ref.capabilities field(s): {', '.join(unknown_top)}"
            ),
            "invalid_ref_capabilities",
        )
    suppress = raw.get(REF_CAPABILITIES_SUPPRESS_KEY, {})
    if not isinstance(suppress, Mapping):
        return (
            {},
            "ref.capabilities.suppress must be a mapping of capability to reason",
            "invalid_ref_capabilities",
        )
    known = {item.value for item in PaneCapability}
    result: dict[str, str] = {}
    for key, reason in suppress.items():
        name = str(key)
        if name not in known:
            return (
                {},
                f"unknown capability {name!r} in ref.capabilities.suppress",
                "invalid_ref_capabilities",
            )
        if not isinstance(reason, str) or not reason.strip():
            return (
                {},
                (
                    f"ref.capabilities.suppress[{name}] must be a "
                    "non-empty reason string"
                ),
                "invalid_ref_capabilities",
            )
        result[name] = reason.strip()
    return result, None, None


def _provider_facts_from_spec(
    kind: str,
    spec: Mapping[str, Any] | None,
    *,
    is_degraded: bool,
    suppressions: Mapping[str, str],
) -> PaneDeclaredFacts:
    """Extract declared facts from a normalized schema-v1 provider spec."""

    ref = _ref_mapping(spec) or {}
    inventory = ref.get("inventory")
    has_inventory = isinstance(inventory, Mapping) and bool(
        _string_list(inventory.get("globs"))
    )
    properties = ref.get("properties")
    has_fields = isinstance(properties, Mapping) and bool(properties)
    identity = ref.get("identity")
    publication = ref.get("publication")
    has_stable_identity = bool(kind) and (
        isinstance(identity, Mapping) or isinstance(publication, Mapping)
    )
    has_revisions = _has_revision_facts(identity, properties)
    is_plan_adapter = kind == "plan"
    if is_degraded:
        has_inventory = False
        has_fields = False
        has_stable_identity = False
        has_revisions = False
        is_plan_adapter = False
    return PaneDeclaredFacts(
        source="provider",
        adapter="plan" if is_plan_adapter else None,
        is_degraded=is_degraded,
        has_inventory=has_inventory,
        has_fields=has_fields,
        has_stable_identity=has_stable_identity,
        has_revisions=has_revisions,
        can_mutate=False,
        is_plan_adapter=is_plan_adapter,
        project_scoped=not is_degraded,
        has_detail=not is_degraded,
        suppressions=dict(suppressions),
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
        "query_schema": {"fields": list(contract.query_schema.fields)},
        "relations": [
            {"name": item.name, "target": item.target} for item in contract.relations
        ],
        "grouping": {"keys": list(contract.grouping.keys)},
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
        "query_schema": {"fields": []},
        "relations": [],
        "grouping": {"keys": []},
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
    adapter: str | None,
    provider_spec_digest: str | None,
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
        query_schema=PaneQuerySchema(),
        relations=(),
        grouping=PaneGroupingDecl(),
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


def _ref_mapping(spec: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if spec is None:
        return None
    ref = spec.get("ref")
    return ref if isinstance(ref, Mapping) else None


def _detail_fields_from_spec(spec: Mapping[str, Any] | None) -> tuple[str, ...]:
    ref = _ref_mapping(spec)
    if ref is None:
        return ()
    detail = ref.get("detail")
    if not isinstance(detail, Mapping):
        return ()
    return tuple(_string_list(detail.get("fields")))


def _has_revision_facts(identity: object, properties: object) -> bool:
    if isinstance(identity, Mapping):
        if any(
            key in identity and identity[key] not in {None, "", False}
            for key in ("revision", "revisions")
        ):
            return True
        identity_property = identity.get("property")
        if isinstance(identity_property, str) and (
            identity_property.casefold() in _REVISION_PROPERTY_NAMES
        ):
            return True
    if isinstance(properties, Mapping):
        return any(
            str(name).casefold() in _REVISION_PROPERTY_NAMES for name in properties
        )
    return False


def _string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
    return slug or "document"


__all__ = [
    "BUILTIN_ADAPTERS",
    "GENERIC_DOCUMENT_COPY_KEYMAP_GROUP",
    "GENERIC_DOCUMENT_COPY_TARGETS",
    "PLAN_ADAPTER",
    "PLAN_COPY_TARGETS",
    "REF_CAPABILITIES_CONFIG_KEY",
    "REF_CAPABILITIES_SUPPRESS_KEY",
    "ContractCompileResult",
    "attach_contract",
    "compile_builtin_contract",
    "compile_provider_contract",
    "contract_with_digit",
]
