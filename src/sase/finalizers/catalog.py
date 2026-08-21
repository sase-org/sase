"""Side-effect-free finalizer completion catalog for ACE and editor helpers.

Rows come from effective trusted configuration only. Building a catalog never
imports or executes a finalizer provider.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from sase.config.core import current_config_token
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
    load_finalizer_config,
)

FINALIZER_CATALOG_SCHEMA_VERSION = 1

_CatalogCache = tuple[tuple[object, ...], "_FinalizerCatalogBuild"]
_CATALOG_CACHE: _CatalogCache | None = None


@dataclass(frozen=True, slots=True)
class _FinalizerCatalogEntry:
    """One configured finalizer instance as a completion-catalog row."""

    value: str
    provider_ref: str
    required: bool = False
    is_default: bool = False
    after: tuple[str, ...] = ()
    max_attempts: int = 1
    documentation: str = ""
    provenance_id: str | None = None

    def to_wire(self) -> dict[str, object]:
        """Return a compact, mixed-version-safe helper/LSP inventory dict."""
        payload: dict[str, object] = {
            "value": self.value,
            "display": self.value,
            "documentation": self.documentation,
            "provider_ref": self.provider_ref,
            "max_attempts": self.max_attempts,
        }
        if self.provider_ref:
            payload["detail"] = self.provider_ref
        if self.required:
            payload["required"] = True
        if self.is_default:
            payload["default"] = True
        if self.after:
            payload["after"] = list(self.after)
        if self.provenance_id:
            payload["provenance_id"] = self.provenance_id
        return payload


@dataclass(frozen=True, slots=True)
class _FinalizerCatalogBuild:
    """Result of replaying effective finalizer configuration into catalog rows."""

    status: str
    message: str = ""
    entries: tuple[_FinalizerCatalogEntry, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def wire_entries(self) -> tuple[dict[str, object], ...]:
        return tuple(entry.to_wire() for entry in self.entries)


def build_finalizer_completion_catalog(
    *,
    use_cache: bool = True,
    config: FinalizerConfig | None = None,
) -> _FinalizerCatalogBuild:
    """Return ordered catalog rows for ``%final`` completion.

    The effective config is replayed once per config token. Callers that already
    hold a :class:`FinalizerConfig` may pass it to skip loading.
    """
    global _CATALOG_CACHE  # noqa: PLW0603

    if config is not None:
        return _catalog_from_config(config)

    token = current_config_token() if use_cache else None
    if use_cache and _CATALOG_CACHE is not None and _CATALOG_CACHE[0] == token:
        return _CATALOG_CACHE[1]

    built = _catalog_from_config(load_finalizer_config())
    if use_cache:
        assert token is not None
        _CATALOG_CACHE = (token, built)
    return built


def _catalog_from_config(config: FinalizerConfig) -> _FinalizerCatalogBuild:
    """Build catalog rows from an already-loaded effective config."""
    fatals = config.fatal_diagnostics()
    if fatals:
        message = "; ".join(item.message for item in fatals)
        return _FinalizerCatalogBuild(status="error", message=message)

    required = {
        instance_id
        for instance_id in config.required
        if instance_id in config.instances
    }
    defaults = {
        instance_id
        for instance_id in config.defaults
        if instance_id in config.instances
    }

    def _rank(instance_id: str) -> tuple[int, str]:
        if instance_id in required:
            group = 0
        elif instance_id in defaults:
            group = 1
        else:
            group = 2
        return (group, instance_id.casefold())

    entries = tuple(
        _entry_for(config.instances[instance_id], required=required, defaults=defaults)
        for instance_id in sorted(config.instances, key=_rank)
    )
    return _FinalizerCatalogBuild(status="ok", entries=entries)


def _entry_for(
    instance: ConfiguredFinalizerInstance,
    *,
    required: set[str],
    defaults: set[str],
) -> _FinalizerCatalogEntry:
    is_required = instance.instance_id in required
    is_default = instance.instance_id in defaults
    return _FinalizerCatalogEntry(
        value=instance.instance_id,
        provider_ref=instance.provider_ref,
        required=is_required,
        is_default=is_default,
        after=instance.after,
        max_attempts=instance.max_attempts,
        documentation=_entry_documentation(
            instance,
            required=is_required,
            is_default=is_default,
        ),
        provenance_id=_provenance_id(instance.provenance),
    )


def _entry_documentation(
    instance: ConfiguredFinalizerInstance,
    *,
    required: bool,
    is_default: bool,
) -> str:
    if required:
        policy = "Required for this launch."
    elif is_default:
        policy = "Selected by default."
    else:
        policy = "Optional."

    sections = [policy, f"Provider: `{instance.provider_ref}`"]
    if instance.after:
        depends = "`, `".join(instance.after)
        sections.append(f"Depends on: `{depends}`")
    attempts = instance.max_attempts
    noun = "attempt" if attempts == 1 else "attempts"
    sections.append(f"Retry policy: {attempts} {noun}")
    provenance = _provenance_id(instance.provenance)
    if provenance:
        sections.append(f"Configured from `{provenance}`.")
    return "\n\n".join(sections)


def _provenance_id(
    provenance: Mapping[str, FinalizerFieldProvenance] | object,
) -> str | None:
    if not isinstance(provenance, Mapping):
        return None
    item = provenance.get("use")
    if not isinstance(item, FinalizerFieldProvenance):
        return None
    return item.layer if item.path is None else f"{item.layer}:{item.path}"


__all__ = [
    "FINALIZER_CATALOG_SCHEMA_VERSION",
    "build_finalizer_completion_catalog",
]
