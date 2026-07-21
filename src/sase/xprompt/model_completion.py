"""Completion catalog for ``%model`` directive values.

The Python LLM registry owns model/provider metadata. This module builds the
JSON-serializable catalog shared by the ACE prompt input and the Rust xprompt
LSP launcher materialization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sase.llm_provider.config import (
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME,
    CHEAPEST_MODEL_ALIAS_NAME,
    CODER_MODEL_ALIAS_NAME,
    DEFAULT_MODEL_ALIAS_NAME,
    EPIC_LANDER_MODEL_ALIAS_NAME,
    LARGE_PHASE_WORKER_MODEL_ALIAS_NAME,
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME,
    PHASE_WORKER_MODEL_ALIAS_NAME,
    SMALL_PHASE_WORKER_MODEL_ALIAS_NAME,
    SMARTEST_MODEL_ALIAS_NAME,
    coder_model_alias_for_provider,
    get_model_aliases,
    model_alias_config_source,
    model_alias_description,
)
from sase.llm_provider.registry import get_llm_metadata_payload

MODEL_COMPLETION_CATALOG_SCHEMA_VERSION = 1

_INLINE_MODEL_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-=./@]+$")

# Implicit role aliases surfaced as ``%model`` completions, in display order.
# The ``<provider>_coder`` aliases are generated per registered provider and slot
# in between ``@coder`` and the epic/phase roles (see the catalog builder). These
# are the migration replacements for the retired reserved ``@worker``/``@other``
# aliases (epic sase-5d phase 2).
_LEADING_IMPLICIT_ALIASES: tuple[tuple[str, str], ...] = (
    (DEFAULT_MODEL_ALIAS_NAME, "default model when a prompt has no %model"),
    (CODER_MODEL_ALIAS_NAME, "coder follow-up model"),
)
_TRAILING_IMPLICIT_ALIASES: tuple[tuple[str, str], ...] = (
    (EPIC_LANDER_MODEL_ALIAS_NAME, "epic land follow-up model"),
    (
        BIG_EPIC_LANDER_MODEL_ALIAS_NAME,
        "threshold-selected large-epic land follow-up model",
    ),
    (PHASE_WORKER_MODEL_ALIAS_NAME, "shared bead phase fallback model"),
    (SMALL_PHASE_WORKER_MODEL_ALIAS_NAME, "small bead phase agent model"),
    (MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME, "medium bead phase agent model"),
    (LARGE_PHASE_WORKER_MODEL_ALIAS_NAME, "large bead phase agent model"),
    (SMARTEST_MODEL_ALIAS_NAME, "highest-capability model for large phase agents"),
    (CHEAPEST_MODEL_ALIAS_NAME, "cheap load-balanced high-volume agent pool"),
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
    completion values. The implicit role aliases (``@default``, ``@coder``, each
    registered ``@<provider>_coder``, ``@epic_lander``,
    ``@big_epic_lander``, ``@phase_worker``, the three size-specific phase
    aliases, ``@smartest``, and ``@cheapest``) and user-configured aliases are
    inserted with their ``@`` form because those values resolve through the
    normal ``%model`` path.
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

    user_aliases = get_model_aliases()
    _append_implicit_alias_entries(
        entries,
        seen,
        provider_order=provider_order,
        providers=providers,
        user_aliases=user_aliases,
    )

    for alias, target in sorted(user_aliases.items()):
        if alias in seen:
            continue
        description = f"alias for {target}"
        if model_alias_config_source(alias) == "custom":
            configured_description = model_alias_description(alias)
            if configured_description:
                description = f"{configured_description} (alias for {target})"
        _append_alias_entry(
            entries,
            seen,
            value=alias,
            description=description,
            kind="user_alias",
        )

    return entries


def _append_implicit_alias_entries(
    entries: list[_ModelCompletionEntry],
    seen: set[str],
    *,
    provider_order: list[str],
    providers: dict[str, object],
    user_aliases: dict[str, str],
) -> None:
    """Append the implicit role aliases (``@default``, ``@coder``, etc.).

    Provider-specific ``@<provider>_coder`` aliases are generated for every
    registered provider, slotted between ``@coder`` and the epic/phase roles.
    An implicit alias the user has shadowed via ``model_aliases`` is skipped here
    so the user-configured target is surfaced once, with its real
    description, by the caller's user-alias loop.
    """
    implicit: list[tuple[str, str]] = [*_LEADING_IMPLICIT_ALIASES]
    for provider in provider_order:
        provider_display = _provider_display(provider, _dict(providers.get(provider)))
        implicit.append(
            (
                coder_model_alias_for_provider(provider),
                f"{provider_display} coder follow-up model",
            )
        )
    implicit.extend(_TRAILING_IMPLICIT_ALIASES)

    for value, description in implicit:
        if value in user_aliases:
            continue
        _append_alias_entry(
            entries,
            seen,
            value=value,
            description=description,
            kind="implicit_alias",
        )


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
    display_value = f"@{value}" if not value.startswith("@") else value
    bare_alias = display_value[1:] if display_value.startswith("@") else display_value
    if display_value in seen or not _is_inline_completable(display_value):
        return
    entries.append(
        _ModelCompletionEntry(
            value=display_value,
            display=display_value,
            description=description,
            kind=kind,
            provider="",
            aliases=(bare_alias,),
        )
    )
    seen.add(display_value)


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
