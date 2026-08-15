"""Extract Artifacts pane facts from normalized document-provider specs."""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from ._artifact_tab_model import PaneCapability, PaneDeclaredFacts


REF_CAPABILITIES_CONFIG_KEY = "capabilities"
REF_CAPABILITIES_SUPPRESS_KEY = "suppress"

_REVISION_PROPERTY_NAMES = frozenset({"revision", "version", "rev"})


def extract_provider_suppressions(
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


def provider_facts_from_spec(
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


def _ref_mapping(spec: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if spec is None:
        return None
    ref = spec.get("ref")
    return ref if isinstance(ref, Mapping) else None


def provider_detail_fields(spec: Mapping[str, Any] | None) -> tuple[str, ...]:
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


def provider_kind_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
    return slug or "document"


__all__ = [
    "REF_CAPABILITIES_CONFIG_KEY",
    "REF_CAPABILITIES_SUPPRESS_KEY",
    "extract_provider_suppressions",
    "provider_detail_fields",
    "provider_facts_from_spec",
    "provider_kind_slug",
]
