"""Bundled manifest for built-in provider model catalogs and size aliases.

Shipped catalog data (ordered model IDs, short aliases, tier defaults,
``supersedes`` links, and advisories) lives in the bundled ``models.yml``
sibling file, not in provider modules. Editing that YAML is the single change
needed for routine built-in model maintenance; this module only owns the lazy
cached loader that turns the YAML into immutable accessor mappings, plus the
strict structural validation that turns a malformed bundle into a loud
installation defect instead of silently rerouted launches.

Provider modules answer their ``llm_known_model_names``,
``llm_model_short_aliases``, ``llm_model_advisories``, and
``llm_resolve_model_name`` hooks from the accessors here. Third-party
providers keep publishing models through the pluggy hooks directly and never
touch this manifest.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase._yaml_safe import yaml_safe_load

_MANIFEST_RESOURCE_NAME = "models.yml"
_MANIFEST_SCHEMA_VERSION = 1

_PROVIDER_ENTRY_KEYS = frozenset(
    {"models", "short_aliases", "tiers", "supersedes", "advisories"}
)
_ADVISORY_ENTRY_KEYS = frozenset({"severity", "label", "detail"})
_ADVISORY_SEVERITIES = frozenset({"warn", "info"})
_MODEL_TIERS = ("large", "small")


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    """Immutable per-provider catalog slice from the bundled manifest."""

    models: tuple[str, ...]
    short_aliases: Mapping[str, str]
    tiers: Mapping[str, str]
    supersedes: Mapping[str, str]
    advisories: Mapping[str, Mapping[str, str]]


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """Immutable views over the bundled ``models.yml`` file."""

    providers: Mapping[str, ProviderRecord]
    alias_targets: Mapping[str, str]
    alias_fallbacks: Mapping[str, str]
    alias_descriptions: Mapping[str, str]


def _manifest_error(resource: object, problem: str) -> RuntimeError:
    return RuntimeError(
        f"bundled model manifest ({resource}) {problem}; this is a SASE "
        "installation defect"
    )


def _require_mapping(resource: object, value: Any, *, what: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise _manifest_error(resource, f"{what} must be a mapping")
    return value


def _require_nonempty_str(resource: object, value: Any, *, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _manifest_error(resource, f"{what} must be a non-empty string")
    return value.strip()


def _parse_provider_entry(resource: object, *, name: str, entry: Any) -> ProviderRecord:
    data = _require_mapping(resource, entry, what=f"provider {name!r}")
    unknown = sorted(set(data) - _PROVIDER_ENTRY_KEYS)
    if unknown:
        raise _manifest_error(
            resource, f"provider {name!r} has unknown keys: {unknown}"
        )

    raw_models = data.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise _manifest_error(
            resource, f"provider {name!r} must list a non-empty 'models' array"
        )
    models = tuple(
        _require_nonempty_str(resource, model, what=f"provider {name!r} model entry")
        for model in raw_models
    )
    seen = set()
    for model in models:
        if model in seen:
            raise _manifest_error(
                resource, f"provider {name!r} declares model {model!r} twice"
            )
        seen.add(model)
    catalog = set(models)

    raw_short_aliases = data.get("short_aliases", {})
    short_mapping = _require_mapping(
        resource, raw_short_aliases, what=f"provider {name!r} 'short_aliases'"
    )
    short_aliases: dict[str, str] = {}
    for model, alias in short_mapping.items():
        clean_model = _require_nonempty_str(
            resource, model, what=f"provider {name!r} short-alias model"
        )
        clean_alias = _require_nonempty_str(
            resource, alias, what=f"provider {name!r} short alias"
        )
        if clean_model in short_aliases:
            raise _manifest_error(
                resource,
                f"provider {name!r} declares short alias for {clean_model!r} twice",
            )
        if clean_model not in catalog:
            raise _manifest_error(
                resource,
                f"provider {name!r} short alias for unknown model {clean_model!r}",
            )
        short_aliases[clean_model] = clean_alias
    seen_alias_values = set()
    for alias in short_aliases.values():
        if alias in seen_alias_values:
            raise _manifest_error(
                resource,
                f"provider {name!r} assigns short alias {alias!r} to two models",
            )
        seen_alias_values.add(alias)

    raw_tiers = data.get("tiers")
    tier_mapping = _require_mapping(
        resource, raw_tiers, what=f"provider {name!r} 'tiers'"
    )
    if set(tier_mapping) != set(_MODEL_TIERS):
        raise _manifest_error(
            resource,
            f"provider {name!r} 'tiers' must define exactly {sorted(_MODEL_TIERS)}",
        )
    tiers: dict[str, str] = {}
    for tier in _MODEL_TIERS:
        tier_model = _require_nonempty_str(
            resource, tier_mapping[tier], what=f"provider {name!r} {tier!r} tier"
        )
        if tier_model not in catalog:
            raise _manifest_error(
                resource,
                f"provider {name!r} {tier!r} tier names unknown model {tier_model!r}",
            )
        tiers[tier] = tier_model

    raw_supersedes = data.get("supersedes", {})
    supersedes_mapping = _require_mapping(
        resource, raw_supersedes, what=f"provider {name!r} 'supersedes'"
    )
    supersedes: dict[str, str] = {}
    for successor, predecessor in supersedes_mapping.items():
        clean_successor = _require_nonempty_str(
            resource, successor, what=f"provider {name!r} supersedes successor"
        )
        clean_predecessor = _require_nonempty_str(
            resource,
            predecessor,
            what=f"provider {name!r} supersedes predecessor",
        )
        if clean_successor not in catalog:
            raise _manifest_error(
                resource,
                f"provider {name!r} supersedes unknown model {clean_successor!r}",
            )
        if clean_predecessor not in catalog:
            raise _manifest_error(
                resource,
                f"provider {name!r} supersedes unknown model {clean_predecessor!r}",
            )
        if clean_successor == clean_predecessor:
            raise _manifest_error(
                resource,
                f"provider {name!r} model {clean_successor!r} supersedes itself",
            )
        if clean_successor in supersedes:
            raise _manifest_error(
                resource,
                f"provider {name!r} declares supersedes for {clean_successor!r} twice",
            )
        supersedes[clean_successor] = clean_predecessor
    for start in supersedes:
        path = [start]
        seen_links = {start}
        current = start
        while True:
            predecessor = supersedes[current]
            if predecessor not in supersedes:
                break
            if predecessor in seen_links:
                cycle_start = path.index(predecessor)
                cycle = [*path[cycle_start:], predecessor]
                rendered = " -> ".join(cycle)
                raise _manifest_error(
                    resource,
                    f"provider {name!r} supersedes chain creates a cycle: {rendered}",
                )
            seen_links.add(predecessor)
            path.append(predecessor)
            current = predecessor

    raw_advisories = data.get("advisories", {})
    advisories_mapping = _require_mapping(
        resource, raw_advisories, what=f"provider {name!r} 'advisories'"
    )
    advisories: dict[str, dict[str, str]] = {}
    for model, advisory in advisories_mapping.items():
        clean_model = _require_nonempty_str(
            resource, model, what=f"provider {name!r} advisory model"
        )
        if clean_model not in catalog:
            raise _manifest_error(
                resource,
                f"provider {name!r} advisory for unknown model {clean_model!r}",
            )
        advisory_data = _require_mapping(
            resource,
            advisory,
            what=f"provider {name!r} advisory for {clean_model!r}",
        )
        unknown_advisory = sorted(set(advisory_data) - _ADVISORY_ENTRY_KEYS)
        if unknown_advisory:
            raise _manifest_error(
                resource,
                f"provider {name!r} advisory for {clean_model!r} has unknown "
                f"keys: {unknown_advisory}",
            )
        severity = advisory_data.get("severity", "info")
        if not isinstance(severity, str) or severity not in _ADVISORY_SEVERITIES:
            raise _manifest_error(
                resource,
                f"provider {name!r} advisory for {clean_model!r} has invalid "
                f"severity {severity!r}; expected one of: "
                f"{sorted(_ADVISORY_SEVERITIES)}",
            )
        label = _require_nonempty_str(
            resource,
            advisory_data.get("label"),
            what=f"provider {name!r} advisory for {clean_model!r} 'label'",
        )
        detail_value = advisory_data.get("detail", "")
        if not isinstance(detail_value, str):
            raise _manifest_error(
                resource,
                f"provider {name!r} advisory for {clean_model!r} 'detail' "
                "must be a string",
            )
        advisories[clean_model] = {
            "severity": severity,
            "label": label,
            "detail": detail_value.strip(),
        }

    return ProviderRecord(
        models=models,
        short_aliases=MappingProxyType(short_aliases),
        tiers=MappingProxyType(tiers),
        supersedes=MappingProxyType(supersedes),
        advisories=MappingProxyType(
            {
                model: MappingProxyType(advisory)
                for model, advisory in advisories.items()
            }
        ),
    )


def _parse_model_manifest(text: str, *, source: object) -> ModelManifest:
    """Parse and validate model-manifest YAML from *text*."""
    try:
        data = yaml_safe_load(text)
    except yaml.YAMLError as exc:
        raise _manifest_error(source, f"is not valid YAML: {exc}") from exc

    top = _require_mapping(source, data, what="manifest")
    unknown_top = sorted(set(top) - {"schema_version", "providers", "aliases"})
    if unknown_top:
        raise _manifest_error(
            source, f"manifest has unknown top-level keys: {unknown_top}"
        )
    if top.get("schema_version") != _MANIFEST_SCHEMA_VERSION:
        raise _manifest_error(
            source,
            f"manifest schema_version must be {_MANIFEST_SCHEMA_VERSION}, got "
            f"{top.get('schema_version')!r}",
        )

    raw_providers = _require_mapping(
        source, top.get("providers"), what="manifest 'providers'"
    )
    if not raw_providers:
        raise _manifest_error(source, "manifest 'providers' must not be empty")
    providers: dict[str, ProviderRecord] = {}
    for name, entry in raw_providers.items():
        clean_name = _require_nonempty_str(source, name, what="manifest provider name")
        if clean_name in providers:
            raise _manifest_error(
                source, f"manifest declares provider {clean_name!r} twice"
            )
        providers[clean_name] = _parse_provider_entry(
            source, name=clean_name, entry=entry
        )

    claimed: dict[str, str] = {}
    for provider_name, record in providers.items():
        for model in record.models:
            owner = claimed.get(model)
            if owner is not None:
                raise _manifest_error(
                    source,
                    f"model {model!r} is claimed by both {owner!r} and "
                    f"{provider_name!r}; bare model names must be globally "
                    "unique so implicit resolution stays unambiguous",
                )
            claimed[model] = provider_name
    for provider_name, record in providers.items():
        for model, alias in record.short_aliases.items():
            owner = claimed.get(alias)
            if owner is not None:
                raise _manifest_error(
                    source,
                    f"provider {provider_name!r} short alias {alias!r} for "
                    f"{model!r} is ambiguous with a bare model name; short "
                    "aliases must not shadow model names",
                )

    # The five size aliases keep the exact grammar the alias policy enforces;
    # reuse its parser so user-config overrides and alias resolution retain
    # their behavior.
    from .model_alias_policy import parse_model_alias_defaults

    import yaml as _pyyaml

    aliases_text = _pyyaml.safe_dump(
        {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "aliases": top.get("aliases"),
        },
        sort_keys=False,
    )
    alias_defaults = parse_model_alias_defaults(aliases_text, source=source)

    return ModelManifest(
        providers=MappingProxyType(providers),
        alias_targets=alias_defaults.implicit_alias_targets,
        alias_fallbacks=alias_defaults.role_alias_fallbacks,
        alias_descriptions=alias_defaults.role_alias_descriptions,
    )


@cache
def _load_model_manifest() -> ModelManifest:
    """Load and validate the bundled model manifest.

    A missing or malformed file ships with the package, so it is an
    installation defect rather than user error: raise loudly instead of
    silently degrading to empty catalogs, which would reroute every launch.
    """
    resource = files("sase.llm_provider").joinpath(_MANIFEST_RESOURCE_NAME)

    try:
        text = resource.read_text(encoding="utf-8")
    except OSError as exc:
        raise _manifest_error(resource, f"could not be read: {exc}") from exc

    return _parse_model_manifest(text, source=resource)


def get_model_manifest() -> ModelManifest:
    """Return the cached bundled model manifest."""
    return _load_model_manifest()


def manifest_provider_names() -> tuple[str, ...]:
    """Return every built-in provider name declared by the manifest."""
    return tuple(get_model_manifest().providers)


def _provider_record(name: str) -> ProviderRecord:
    record = get_model_manifest().providers.get(name)
    if record is None:
        raise _manifest_error(
            _MANIFEST_RESOURCE_NAME,
            f"provider {name!r} is not declared in the manifest",
        )
    return record


def provider_model_names(name: str) -> tuple[str, ...]:
    """Return the ordered model IDs the manifest declares for *name*."""
    return _provider_record(name).models


def provider_short_aliases(name: str) -> dict[str, str]:
    """Return the long-model-ID to short-alias map for *name*."""
    return dict(_provider_record(name).short_aliases)


def provider_model_advisories(name: str) -> dict[str, dict[str, str]]:
    """Return the per-model advisories the manifest declares for *name*."""
    return {
        model: dict(advisory)
        for model, advisory in _provider_record(name).advisories.items()
    }


def provider_tier_model(name: str, tier: str) -> str:
    """Return the manifest's ``large``/``small`` invocation default for *name*."""
    tiers = _provider_record(name).tiers
    try:
        return tiers[tier]
    except KeyError:
        raise _manifest_error(
            _MANIFEST_RESOURCE_NAME,
            f"provider {name!r} has no {tier!r} tier default",
        ) from None


def provider_model_supersedes(name: str) -> dict[str, str]:
    """Return the successor-to-predecessor links declared for *name*."""
    return dict(_provider_record(name).supersedes)
