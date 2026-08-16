"""Extract Artifacts pane facts from normalized document-provider specs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import re
from typing import Any

from sase.ace.tui._artifact_tab_model import (
    FIXED_ARTIFACTS_SUBTAB_ORDER,
    PaneCapability,
    PaneDeclaredFacts,
    PaneGroupingDecl,
    PaneGroupingModeDecl,
    PaneRelationDecl,
    RelationKind,
)
from sase.ace.query_profile import (
    ArtifactQuerySchema,
    CompiledQueryProfile,
    QueryProfileError,
    compile_query_profile,
    provider_query_schema,
)


REF_CAPABILITIES_CONFIG_KEY = "capabilities"
REF_CAPABILITIES_SUPPRESS_KEY = "suppress"
REF_RELATIONS_CONFIG_KEY = "relations"
REF_GROUPING_CONFIG_KEY = "grouping"

_REVISION_PROPERTY_NAMES = frozenset({"revision", "version", "rev"})
_RELATION_KEYS = frozenset(
    {
        "name",
        "kind",
        "label",
        "source",
        "target_pane",
        "inverse",
        "directed",
        "transitive",
    }
)
_GROUPING_KEYS = frozenset({"default_mode", "modes"})
_GROUPING_MODE_KEYS = frozenset({"id", "label", "keys"})


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
    relations: tuple[PaneRelationDecl, ...] = (),
    grouping: PaneGroupingDecl | None = None,
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
        relations = ()
        grouping = PaneGroupingDecl()
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
        relations=relations,
        grouping=grouping or PaneGroupingDecl(),
        suppressions=dict(suppressions),
    )


def _ref_mapping(spec: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if spec is None:
        return None
    ref = spec.get("ref")
    return ref if isinstance(ref, Mapping) else None


def extract_provider_relations(
    kind: str,
    spec: Mapping[str, Any] | None,
    *,
    configured_pane_ids: Iterable[str] = (),
) -> tuple[tuple[PaneRelationDecl, ...], str | None, str | None]:
    """Validate ``ref.relations`` and return declared relation facts."""

    ref = _ref_mapping(spec)
    if ref is None or REF_RELATIONS_CONFIG_KEY not in ref:
        return (), None, None
    raw = ref.get(REF_RELATIONS_CONFIG_KEY)
    if not isinstance(raw, list):
        return (
            (),
            "ref.relations must be a list of relation declarations",
            "invalid_ref_relations",
        )
    properties = _declared_property_names(ref)
    allowed_panes = _allowed_target_panes(kind, configured_pane_ids)
    relations: list[PaneRelationDecl] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            return (
                (),
                f"ref.relations[{index}] must be a mapping",
                "invalid_ref_relations",
            )
        unknown = sorted(str(key) for key in item if str(key) not in _RELATION_KEYS)
        if unknown:
            return (
                (),
                (f"unknown ref.relations[{index}] field(s): {', '.join(unknown)}"),
                "invalid_ref_relations",
            )
        name = _required_text(item, "name")
        label = _required_text(item, "label")
        source = _required_text(item, "source")
        if not name or not label or not source:
            return (
                (),
                (
                    f"ref.relations[{index}] requires non-empty "
                    "name, label, and source fields"
                ),
                "invalid_ref_relations",
            )
        if name in seen:
            return (
                (),
                f"duplicate ref.relations name {name!r}",
                "invalid_ref_relations",
            )
        seen.add(name)
        if source not in properties:
            return (
                (),
                (
                    f"ref.relations[{index}].source {source!r} is not a "
                    "declared ref.properties key"
                ),
                "invalid_ref_relations",
            )
        kind_value = _relation_kind(item.get("kind"))
        if kind_value is None:
            return (
                (),
                (
                    f"ref.relations[{index}].kind must be one of "
                    f"{', '.join(item.value for item in RelationKind)}"
                ),
                "invalid_ref_relations",
            )
        target_pane = _optional_text(item, "target_pane")
        if target_pane is not None and target_pane not in allowed_panes:
            return (
                (),
                (
                    f"ref.relations[{index}].target_pane {target_pane!r} "
                    "is not a configured Artifacts pane id"
                ),
                "invalid_ref_relations",
            )
        inverse = _optional_text(item, "inverse")
        directed = item.get("directed")
        transitive = item.get("transitive")
        if not isinstance(directed, bool) or not isinstance(transitive, bool):
            return (
                (),
                (
                    f"ref.relations[{index}] requires boolean directed "
                    "and transitive fields"
                ),
                "invalid_ref_relations",
            )
        relations.append(
            PaneRelationDecl(
                name=name,
                kind=kind_value,
                label=label,
                source=source,
                target_pane=target_pane,
                inverse=inverse,
                directed=directed,
                transitive=transitive,
            )
        )
    return tuple(relations), None, None


def extract_provider_grouping(
    spec: Mapping[str, Any] | None,
) -> tuple[PaneGroupingDecl, str | None, str | None]:
    """Validate ``ref.grouping`` and return declared grouping facts."""

    ref = _ref_mapping(spec)
    if ref is None or REF_GROUPING_CONFIG_KEY not in ref:
        return PaneGroupingDecl(), None, None
    raw = ref.get(REF_GROUPING_CONFIG_KEY)
    if not isinstance(raw, Mapping):
        return (
            PaneGroupingDecl(),
            "ref.grouping must be a mapping",
            "invalid_ref_grouping",
        )
    unknown = sorted(str(key) for key in raw if str(key) not in _GROUPING_KEYS)
    if unknown:
        return (
            PaneGroupingDecl(),
            f"unknown ref.grouping field(s): {', '.join(unknown)}",
            "invalid_ref_grouping",
        )
    raw_modes = raw.get("modes", ())
    if not isinstance(raw_modes, list):
        return (
            PaneGroupingDecl(),
            "ref.grouping.modes must be a list of grouping mode declarations",
            "invalid_ref_grouping",
        )
    properties = _declared_property_names(ref)
    modes: list[PaneGroupingModeDecl] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_modes):
        if not isinstance(item, Mapping):
            return (
                PaneGroupingDecl(),
                f"ref.grouping.modes[{index}] must be a mapping",
                "invalid_ref_grouping",
            )
        mode_unknown = sorted(
            str(key) for key in item if str(key) not in _GROUPING_MODE_KEYS
        )
        if mode_unknown:
            return (
                PaneGroupingDecl(),
                (
                    f"unknown ref.grouping.modes[{index}] field(s): "
                    f"{', '.join(mode_unknown)}"
                ),
                "invalid_ref_grouping",
            )
        mode_id = _required_text(item, "id")
        label = _required_text(item, "label")
        if not mode_id or not label:
            return (
                PaneGroupingDecl(),
                (f"ref.grouping.modes[{index}] requires non-empty id and label fields"),
                "invalid_ref_grouping",
            )
        if mode_id in seen:
            return (
                PaneGroupingDecl(),
                f"duplicate ref.grouping mode id {mode_id!r}",
                "invalid_ref_grouping",
            )
        seen.add(mode_id)
        keys = _string_list(item.get("keys"))
        if not keys:
            return (
                PaneGroupingDecl(),
                f"ref.grouping.modes[{index}].keys must be a non-empty string list",
                "invalid_ref_grouping",
            )
        unknown_keys = [key for key in keys if key not in properties]
        if unknown_keys:
            return (
                PaneGroupingDecl(),
                (
                    f"ref.grouping.modes[{index}].keys include undeclared "
                    f"ref.properties key(s): {', '.join(unknown_keys)}"
                ),
                "invalid_ref_grouping",
            )
        modes.append(PaneGroupingModeDecl(id=mode_id, label=label, keys=keys))
    default_mode = _optional_text(raw, "default_mode")
    if modes:
        if default_mode is None:
            return (
                PaneGroupingDecl(),
                "ref.grouping.default_mode is required when modes are declared",
                "invalid_ref_grouping",
            )
        if default_mode not in {mode.id for mode in modes}:
            return (
                PaneGroupingDecl(),
                (
                    f"ref.grouping.default_mode {default_mode!r} does not "
                    "match a declared mode id"
                ),
                "invalid_ref_grouping",
            )
    elif default_mode is not None:
        return (
            PaneGroupingDecl(),
            "ref.grouping.default_mode requires at least one mode",
            "invalid_ref_grouping",
        )
    return PaneGroupingDecl(modes=tuple(modes), default_mode=default_mode), None, None


def provider_query_profile(
    kind: str,
    spec: Mapping[str, Any] | None,
) -> tuple[CompiledQueryProfile, str | None]:
    """Compile *kind*'s query profile from its declared ``ref.properties``.

    A schema derived only from a Mapping's own keys cannot fail host
    validation in practice, but a provider's declared properties are
    external input, so this stays defensive: on
    :class:`~sase.ace.query_profile.QueryProfileError`, fall back to an
    empty (fieldless) profile and return the error message so the caller
    can surface it as a visible pane diagnostic instead of crashing
    contract compilation.
    """

    try:
        return compile_query_profile(provider_query_schema(kind, spec)), None
    except QueryProfileError as error:
        empty = ArtifactQuerySchema(pane_id=f"ref:{kind}", boolean=False, fields=())
        return compile_query_profile(empty), str(error)


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


def _declared_property_names(ref: Mapping[str, Any]) -> frozenset[str]:
    properties = ref.get("properties")
    if not isinstance(properties, Mapping):
        return frozenset()
    return frozenset(str(key) for key in properties if str(key))


def _allowed_target_panes(
    kind: str,
    configured_pane_ids: Iterable[str],
) -> frozenset[str]:
    pane_ids = set(FIXED_ARTIFACTS_SUBTAB_ORDER)
    pane_ids.add(f"ref:{kind}")
    pane_ids.update(str(item) for item in configured_pane_ids if str(item))
    return frozenset(pane_ids)


def _relation_kind(value: object) -> RelationKind | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return RelationKind(value.strip().casefold())
    except ValueError:
        return None


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    return value.strip() if isinstance(value, str) else ""


def _optional_text(raw: Mapping[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def provider_kind_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
    return slug or "document"


__all__ = [
    "REF_CAPABILITIES_CONFIG_KEY",
    "REF_CAPABILITIES_SUPPRESS_KEY",
    "REF_GROUPING_CONFIG_KEY",
    "REF_RELATIONS_CONFIG_KEY",
    "extract_provider_grouping",
    "extract_provider_relations",
    "extract_provider_suppressions",
    "provider_detail_fields",
    "provider_facts_from_spec",
    "provider_kind_slug",
    "provider_query_profile",
]
