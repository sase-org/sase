"""Background eligibility for subscription-usage refresh.

Names that tests patch on the public :mod:`sase.llm_provider.usage.refresh`
namespace are resolved with late imports so the facade stays the single patch
point.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.llm_provider.usage.config import get_usage_metrics_settings

log = logging.getLogger(__name__)


def eligible_usage_providers(*, include_hidden: bool = False) -> tuple[str, ...]:
    """Return background-eligible registered providers, sorted."""
    from sase.llm_provider.registry import (
        get_llm_metadata_payload,
        model_picker_hidden_provider_names,
        registered_provider_names,
    )
    from sase.llm_provider.usage.refresh import _referenced_provider_ids

    payload = get_llm_metadata_payload()
    hidden = set() if include_hidden else set(model_picker_hidden_provider_names())
    referenced = _referenced_provider_ids()
    settings = get_usage_metrics_settings()
    eligible: list[str] = []
    for name in registered_provider_names():
        if name in hidden:
            continue
        metadata = payload.get("providers", {}).get(name) or {}
        capabilities = metadata.get("usage_capabilities") or {}
        if capabilities.get("probe") is not True:
            continue
        if not _provider_cli_ready(name, metadata):
            continue
        explicit_enable = settings.providers.get(name) is True
        if name not in referenced and not explicit_enable:
            continue
        if not settings.provider_enabled(name):
            continue
        eligible.append(name)
    return tuple(eligible)


def _resolve_requested_providers(
    providers: Sequence[str] | None,
) -> tuple[str, ...]:
    from sase.llm_provider.usage.refresh import eligible_usage_providers as _eligible

    if providers is None:
        return _eligible()
    return tuple(
        dict.fromkeys(str(name).strip() for name in providers if str(name).strip())
    )


def _provider_has_probe_capability(provider: str) -> bool:
    """Return whether *provider* declares usage probe capability."""
    try:
        from sase.llm_provider.registry import get_llm_metadata_payload

        payload = get_llm_metadata_payload()
        providers = payload.get("providers")
        if not isinstance(providers, dict):
            return False
        metadata = providers.get(provider)
        if not isinstance(metadata, dict):
            return False
        capabilities = metadata.get("usage_capabilities")
        return isinstance(capabilities, dict) and capabilities.get("probe") is True
    except Exception:
        log.debug("usage probe-capability lookup failed for %r", provider)
        return False


def _referenced_provider_ids() -> set[str]:
    from sase.llm_provider.config import (
        get_big_epic_lander_model,
        get_builtin_model_aliases,
        get_custom_model_aliases,
        get_default_model,
        get_epic_lander_model,
    )
    from sase.llm_provider.model_alias_policy import implicit_alias_targets
    from sase.llm_provider.model_alias_resolution_types import (
        provider_for_resolved_target,
    )

    # A provider that appears only in a shipped size-alias pool is still one
    # SASE launches agents on, so scan the effective built-in aliases: the
    # shipped defaults with the user's overrides replacing them by alias name.
    builtin_targets = {**implicit_alias_targets(), **get_builtin_model_aliases()}
    targets: list[str] = [
        get_default_model(),
        get_epic_lander_model(),
        get_big_epic_lander_model(),
        *builtin_targets.values(),
        *get_custom_model_aliases().values(),
    ]
    names: set[str] = set()
    for target in targets:
        for part in str(target).replace("|", " ").split():
            token = part.split("@", 1)[0].strip("() \t")
            if not token:
                continue
            provider = provider_for_resolved_target(token)
            if provider:
                names.add(provider)
    return names


def _provider_cli_ready(provider: str, metadata: Mapping[str, Any]) -> bool:
    from sase.llm_provider.usage._probe_meta import resolve_provider_cli_command

    # Resolve exactly as admission readiness does, including the Codex
    # NVM-aware resolver, so an NVM-only install (no ``codex`` on PATH)
    # still counts as ready.
    command = resolve_provider_cli_command(provider, metadata)
    if not command:
        return True
    path = Path(command)
    return path.is_file() or shutil.which(command) is not None
