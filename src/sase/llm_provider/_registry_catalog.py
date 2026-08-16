"""Metadata catalog assembly and read helpers for the LLM registry."""

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from ._registry_metadata import normalize_str_dict

_PROVIDER_FAMILY_COLORS: dict[str, str] = {
    "claude": "#D97757",
    "anthropic": "#D97757",
    "codex": "#10A37F",
    "openai": "#10A37F",
    "meta": "#0064E0",
}

_ProviderMetadataLoader = Callable[[str, object], dict[str, Any]]


def build_llm_metadata_payload(
    plugins: Iterable[tuple[str, object]],
    load_provider_metadata: _ProviderMetadataLoader,
    cache_policy: dict[str, Any],
) -> dict[str, Any]:
    """Collect and index normalized metadata from registered providers."""
    providers: dict[str, dict[str, Any]] = {}
    model_to_provider: dict[str, str] = {}
    provider_short_names: dict[str, str] = {}
    model_short_aliases: dict[str, str] = {}
    model_advisories: dict[str, dict[str, str]] = {}
    provider_colors = dict(_PROVIDER_FAMILY_COLORS)
    autodetect_candidates: list[dict[str, Any]] = []
    default_retry_configs: dict[str, dict[str, Any]] = {}

    for name, plugin in plugins:
        metadata = load_provider_metadata(name, plugin)
        providers[name] = metadata

        for model in metadata["known_model_names"]:
            model_to_provider[model] = name

        provider_short_names[name] = metadata["short_name"] or name
        model_short_aliases.update(metadata["model_short_aliases"])
        model_advisories.update(metadata["model_advisories"])
        color = metadata["cli_status_color"]
        if color:
            provider_colors[name] = color

        priority = metadata["autodetect_priority"]
        if priority is not None:
            autodetect_candidates.append(
                {
                    "priority": priority,
                    "provider": name,
                    "cli_name": metadata["autodetect_cli_name"],
                }
            )

        retry_config = metadata["default_retry_config"]
        if retry_config is not None:
            default_retry_configs[name] = retry_config

    autodetect_candidates.sort(
        key=lambda item: (int(item["priority"]), str(item["provider"]))
    )
    return {
        "schema_version": 1,
        "providers": providers,
        "provider_names": sorted(providers),
        "model_to_provider": model_to_provider,
        "provider_short_names": provider_short_names,
        "model_short_aliases": model_short_aliases,
        "model_advisories": model_advisories,
        "provider_cli_status_colors": provider_colors,
        "autodetect_candidates": autodetect_candidates,
        "default_retry_configs": default_retry_configs,
        "cache_invalidation": cache_policy,
    }


def string_map(payload: Mapping[str, Any], key: str) -> dict[str, str]:
    """Return a normalized string map stored under *key* in *payload*."""
    return normalize_str_dict(payload.get(key))


def model_advisory_map(
    payload: Mapping[str, Any],
) -> dict[str, dict[str, str]]:
    """Return normalized model advisories from a metadata payload."""
    advisories = payload.get("model_advisories")
    if not isinstance(advisories, dict):
        return {}
    return {
        str(model): normalize_str_dict(advisory)
        for model, advisory in advisories.items()
        if isinstance(advisory, dict)
    }


def hidden_provider_names(payload: Mapping[str, Any]) -> frozenset[str]:
    """Return providers hidden from user-facing model pickers."""
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        return frozenset()
    return frozenset(
        name
        for name, metadata in providers.items()
        if isinstance(metadata, dict)
        and metadata.get("hidden_from_model_pickers") is True
    )


def provider_names(payload: Mapping[str, Any]) -> list[str]:
    """Return registered provider names from a metadata payload."""
    names = payload.get("provider_names")
    if not isinstance(names, list):
        return []
    return [str(name) for name in names]


def model_advisory_marker(severity: str | None) -> str:
    """Return the inline glyph marking an advisory of *severity*."""
    return "ⓘ" if severity == "info" else "⚠"


def model_advisory_color(severity: str | None) -> str:
    """Return the hex color paired with :func:`model_advisory_marker`."""
    return "#5FAFD7" if severity == "info" else "#FF8700"
