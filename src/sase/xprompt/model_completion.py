"""Completion catalog for ``%model`` directive values.

The Python LLM registry owns model/provider metadata. This module builds the
JSON-serializable catalog shared by the ACE prompt input and the Rust xprompt
LSP launcher materialization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sase.llm_provider.config import get_model_aliases
from sase.llm_provider.registry import get_llm_metadata_payload

MODEL_COMPLETION_CATALOG_SCHEMA_VERSION = 1

_INLINE_MODEL_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-=./@]+$")
_RESERVED_MODEL_ALIASES: tuple[tuple[str, str], ...] = (
    ("worker", "reserved alias: current worker-lane model"),
    ("other", "reserved alias: model active before a temporary override"),
)


@dataclass(frozen=True, slots=True)
class _ModelCompletionEntry:
    """One inline-completable ``%model`` value."""

    value: str
    display: str
    description: str = ""
    kind: str = "model"
    provider: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)


_CATALOG_CACHE: tuple[_ModelCompletionEntry, ...] | None = None


def build_model_completion_catalog(
    *, use_cache: bool = True
) -> list[_ModelCompletionEntry]:
    """Return ordered inline-completable ``%model`` values.

    Canonical model names come from the cached LLM metadata payload. Short
    aliases are kept as match/display hints only; they are not inserted as
    completion values. Reserved and user-configured aliases are inserted as
    aliases because those values resolve through the normal ``%model`` path.
    """
    global _CATALOG_CACHE  # noqa: PLW0603

    if use_cache and _CATALOG_CACHE is not None:
        return list(_CATALOG_CACHE)

    entries = _build_model_completion_catalog()
    if use_cache:
        _CATALOG_CACHE = tuple(entries)
    return entries


def model_completion_catalog_payload() -> dict[str, object]:
    """Return the JSON payload materialized for the Rust xprompt LSP."""
    return {
        "schema_version": MODEL_COMPLETION_CATALOG_SCHEMA_VERSION,
        "entries": [
            {
                "value": entry.value,
                "display": entry.display,
                "description": entry.description,
                "kind": entry.kind,
                "provider": entry.provider,
                "aliases": list(entry.aliases),
            }
            for entry in build_model_completion_catalog()
        ],
    }


def filter_model_completion_entries(
    entries: list[_ModelCompletionEntry],
    partial: str,
) -> list[_ModelCompletionEntry]:
    """Return entries whose value or alias hint prefix-matches ``partial``."""
    needle = partial.lower()
    if not needle:
        return list(entries)
    return [
        entry
        for entry in entries
        if entry.value.lower().startswith(needle)
        or any(alias.lower().startswith(needle) for alias in entry.aliases)
    ]


def _build_model_completion_catalog() -> list[_ModelCompletionEntry]:
    payload = get_llm_metadata_payload()
    providers = _dict(payload.get("providers"))
    model_to_provider = _str_dict(payload.get("model_to_provider"))
    short_aliases = _str_dict(payload.get("model_short_aliases"))
    provider_order = _provider_order(payload, providers)

    entries: list[_ModelCompletionEntry] = []
    seen: set[str] = set()
    for provider in provider_order:
        provider_metadata = _dict(providers.get(provider))
        known_models = _str_list(provider_metadata.get("known_model_names"))
        provider_display = _provider_display(provider, provider_metadata)
        for model in known_models:
            if model_to_provider.get(model) != provider:
                continue
            _append_model_entry(
                entries,
                seen,
                model=model,
                provider=provider,
                provider_display=provider_display,
                short_alias=short_aliases.get(model, ""),
            )

    # Include any model_to_provider entries missing from provider metadata so
    # the catalog follows the actual resolution map even if plugin metadata is
    # partial.
    for model, provider in sorted(model_to_provider.items()):
        if model in seen:
            continue
        provider_metadata = _dict(providers.get(provider))
        _append_model_entry(
            entries,
            seen,
            model=model,
            provider=provider,
            provider_display=_provider_display(provider, provider_metadata),
            short_alias=short_aliases.get(model, ""),
        )

    for value, description in _RESERVED_MODEL_ALIASES:
        _append_alias_entry(
            entries,
            seen,
            value=value,
            description=description,
            kind="reserved_alias",
        )

    for alias, target in sorted(get_model_aliases().items()):
        if alias in seen:
            continue
        _append_alias_entry(
            entries,
            seen,
            value=alias,
            description=f"alias for {target}",
            kind="user_alias",
        )

    return entries


def _append_model_entry(
    entries: list[_ModelCompletionEntry],
    seen: set[str],
    *,
    model: str,
    provider: str,
    provider_display: str,
    short_alias: str,
) -> None:
    if model in seen or not _is_inline_completable(model):
        return
    aliases = (short_alias,) if short_alias else ()
    description = provider_display
    if short_alias:
        description = f"{provider_display} ({short_alias})"
    entries.append(
        _ModelCompletionEntry(
            value=model,
            display=model,
            description=description,
            kind="model",
            provider=provider,
            aliases=aliases,
        )
    )
    seen.add(model)


def _append_alias_entry(
    entries: list[_ModelCompletionEntry],
    seen: set[str],
    *,
    value: str,
    description: str,
    kind: str,
) -> None:
    if value in seen or not _is_inline_completable(value):
        return
    entries.append(
        _ModelCompletionEntry(
            value=value,
            display=value,
            description=description,
            kind=kind,
            provider="",
            aliases=(),
        )
    )
    seen.add(value)


def _provider_order(
    payload: dict[str, object],
    providers: dict[str, object],
) -> list[str]:
    ordered: list[str] = []
    for item in _dict_list(payload.get("autodetect_candidates")):
        provider = item.get("provider")
        if (
            isinstance(provider, str)
            and provider in providers
            and provider not in ordered
        ):
            ordered.append(provider)
    ordered.extend(
        sorted(provider for provider in providers if provider not in ordered)
    )
    return ordered


def _provider_display(provider: str, metadata: dict[str, object]) -> str:
    provider_name = metadata.get("provider_name")
    if isinstance(provider_name, str) and provider_name:
        return provider_name
    return provider


def _is_inline_completable(value: str) -> bool:
    return _INLINE_MODEL_VALUE_RE.fullmatch(value) is not None


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _str_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


__all__ = [
    "MODEL_COMPLETION_CATALOG_SCHEMA_VERSION",
    "build_model_completion_catalog",
    "filter_model_completion_entries",
    "model_completion_catalog_payload",
]
