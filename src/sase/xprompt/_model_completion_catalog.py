"""Static ``%model`` completion catalog construction."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection

from sase.llm_provider.alias_view import AliasView
from sase.xprompt._model_completion_entry import ModelCompletionEntry

_INLINE_MODEL_VALUE_RE = re.compile(r"^[A-Za-z0-9_\-=./@]+$")


def build_static_model_completion_catalog(
    *,
    metadata_payload: dict[str, object],
    user_aliases: dict[str, str],
    alias_views: dict[str, AliasView],
    hidden_providers: Collection[str],
    implicit_aliases: tuple[str, ...],
    advisory_marker: Callable[[str], str],
) -> list[ModelCompletionEntry]:
    providers = _dict(metadata_payload.get("providers"))
    model_to_provider = _str_dict(metadata_payload.get("model_to_provider"))
    short_aliases = _str_dict(metadata_payload.get("model_short_aliases"))
    advisories = _advisory_labels(metadata_payload.get("model_advisories"))
    provider_order = [
        provider
        for provider in _provider_order(metadata_payload, providers)
        if provider not in hidden_providers
    ]

    entries: list[ModelCompletionEntry] = []
    seen: set[str] = set()
    contributing_providers: dict[str, tuple[str, int]] = {}
    for provider in provider_order:
        provider_metadata = _dict(providers.get(provider))
        known_models = _str_list(provider_metadata.get("known_model_names"))
        provider_display = _provider_display(provider, provider_metadata)
        for model in known_models:
            if model_to_provider.get(model) != provider:
                continue
            if _append_model_entry(
                entries,
                seen,
                model=model,
                provider=provider,
                provider_display=provider_display,
                short_alias=short_aliases.get(model, ""),
                advisory=advisories.get(model, ("", "")),
                advisory_marker=advisory_marker,
            ):
                _, count = contributing_providers.get(provider, (provider_display, 0))
                contributing_providers[provider] = (provider_display, count + 1)

    # Include any model_to_provider entries missing from provider metadata so
    # the catalog follows the actual resolution map even if plugin metadata is
    # partial.
    for model, provider in sorted(model_to_provider.items()):
        if model in seen or provider in hidden_providers:
            continue
        provider_metadata = _dict(providers.get(provider))
        provider_display = _provider_display(provider, provider_metadata)
        if _append_model_entry(
            entries,
            seen,
            model=model,
            provider=provider,
            provider_display=provider_display,
            short_alias=short_aliases.get(model, ""),
            advisory=advisories.get(model, ("", "")),
            advisory_marker=advisory_marker,
        ):
            _, count = contributing_providers.get(provider, (provider_display, 0))
            contributing_providers[provider] = (provider_display, count + 1)

    _append_implicit_alias_entries(
        entries,
        seen,
        implicit_aliases=implicit_aliases,
        user_aliases=user_aliases,
        alias_views=alias_views,
    )

    for alias in sorted(user_aliases):
        if alias in seen:
            continue
        _append_alias_entry(
            entries,
            seen,
            value=alias,
            view=alias_views.get(alias),
            kind="user_alias",
        )

    provider_row_order = [
        *provider_order,
        *sorted(
            provider
            for provider in contributing_providers
            if provider not in provider_order
        ),
    ]
    for provider in provider_row_order:
        provider_contribution = contributing_providers.get(provider)
        if provider_contribution is None:
            continue
        provider_display, model_count = provider_contribution
        _append_provider_entry(
            entries,
            seen,
            provider=provider,
            provider_display=provider_display,
            model_count=model_count,
        )

    return entries


def _append_implicit_alias_entries(
    entries: list[ModelCompletionEntry],
    seen: set[str],
    *,
    implicit_aliases: tuple[str, ...],
    user_aliases: dict[str, str],
    alias_views: dict[str, AliasView],
) -> None:
    """Append the implicit built-in size aliases.

    An implicit alias the user has shadowed via ``model_aliases`` is skipped here
    so the user-configured target is surfaced once, with its real description,
    by the caller's user-alias loop.
    """
    for value in implicit_aliases:
        if value in user_aliases:
            continue
        view = alias_views.get(value)
        _append_alias_entry(
            entries,
            seen,
            value=value,
            view=view,
            kind="implicit_alias",
        )


def _append_model_entry(
    entries: list[ModelCompletionEntry],
    seen: set[str],
    *,
    model: str,
    provider: str,
    provider_display: str,
    short_alias: str,
    advisory_marker: Callable[[str], str],
    advisory: tuple[str, str] = ("", ""),
) -> bool:
    if model in seen or not _is_inline_completable(model):
        return False
    aliases = (short_alias,) if short_alias else ()
    description = provider_display
    if short_alias:
        description = f"{provider_display} ({short_alias})"
    advisory_label, advisory_severity = advisory
    if advisory_label:
        # The completion detail is the only thing a user sees while typing
        # `%model:...`, so the advisory has to ride along with it.
        glyph = advisory_marker(advisory_severity)
        description = f"{description} \u2014 {glyph} {advisory_label}"
    entries.append(
        ModelCompletionEntry(
            value=model,
            display=model,
            description=description,
            kind="model",
            provider=provider,
            aliases=aliases,
            advisory_label=advisory_label,
            advisory_severity=advisory_severity if advisory_label else "",
        )
    )
    seen.add(model)
    return True


def _append_provider_entry(
    entries: list[ModelCompletionEntry],
    seen: set[str],
    *,
    provider: str,
    provider_display: str,
    model_count: int,
) -> None:
    value = f"{provider}/"
    if value in seen or not _is_inline_completable(value):
        return
    entries.append(
        ModelCompletionEntry(
            value=value,
            display=value,
            description=provider_display,
            kind="provider",
            provider=provider,
            provider_model_count=model_count,
        )
    )
    seen.add(value)


def _advisory_labels(value: object) -> dict[str, tuple[str, str]]:
    """Return ``{model: (label, severity)}`` from the registry payload."""
    labels: dict[str, tuple[str, str]] = {}
    for model, advisory in _dict(value).items():
        entry = _str_dict(advisory)
        if label := entry.get("label", ""):
            labels[model] = (label, entry.get("severity", ""))
    return labels


def _append_alias_entry(
    entries: list[ModelCompletionEntry],
    seen: set[str],
    *,
    value: str,
    view: AliasView | None,
    kind: str,
    description: str = "",
) -> None:
    display_value = f"@{value}" if not value.startswith("@") else value
    bare_alias = display_value[1:] if display_value.startswith("@") else display_value
    if display_value in seen or not _is_inline_completable(display_value):
        return
    if view is not None:
        description = description or view.description or ""
        reference = view.references or view.implicit_fallback or ""
        selector_members = tuple(
            member for member in view.selector_members if not member.last_resort
        )
        entry = ModelCompletionEntry(
            value=display_value,
            display=display_value,
            description=description,
            kind=kind,
            provider="",
            aliases=(bare_alias,),
            alias_kind=view.kind,
            target_provider=view.provider or "",
            target_model=view.model,
            target_effort=view.effort or "",
            provenance="configured" if view.configured else "implicit",
            reference=reference,
            reference_effort=view.reference_effort or "",
            selector_mode=view.selector_mode or "",
            pool_available=sum(member.available for member in selector_members),
            pool_total=len(selector_members),
            config_source=view.configured_source or "",
            bucket=view.bucket or "",
        )
    else:
        entry = ModelCompletionEntry(
            value=display_value,
            display=display_value,
            description=description,
            kind=kind,
            provider="",
            aliases=(bare_alias,),
        )
    entries.append(entry)
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
    for key in ("display_name", "provider_name"):
        provider_name = metadata.get(key)
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


__all__ = ["build_static_model_completion_catalog"]
