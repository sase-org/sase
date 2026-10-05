"""Validity snapshot for macro ``model`` inputs.

Built from the LLM registry without resolving alias targets, consuming
cursors, or checking availability. The promise is "accepted without
fallback", not "executable right now".
"""

from __future__ import annotations

from sase.config.core import current_config_token
from sase.macro.effort import EFFORT_LEVELS_ORDERED

_SnapshotCache = tuple[tuple[object, ...], dict[str, object]]
_SNAPSHOT_CACHE: _SnapshotCache | None = None


def model_validity_snapshot(*, use_cache: bool = True) -> dict[str, object]:
    """Return the routing snapshot consumed by the Rust classifier.

    Includes hidden providers and hidden models. Never calls
    ``resolve_model_provider`` and never reads the load-balance cursor.
    """
    global _SNAPSHOT_CACHE  # noqa: PLW0603

    token = current_config_token() if use_cache else None
    if use_cache and _SNAPSHOT_CACHE is not None and _SNAPSHOT_CACHE[0] == token:
        return dict(_SNAPSHOT_CACHE[1])
    snapshot = _build_snapshot()
    if use_cache:
        assert token is not None
        _SNAPSHOT_CACHE = (token, dict(snapshot))
    return snapshot


def clear_model_validity_snapshot_cache() -> None:
    """Clear the cached validity snapshot (tests that patch the registry)."""
    global _SNAPSHOT_CACHE  # noqa: PLW0603
    _SNAPSHOT_CACHE = None


def _build_snapshot() -> dict[str, object]:
    from sase.llm_provider.model_alias_config import model_alias_names
    from sase.llm_provider.registry import (
        model_to_provider_map,
        registered_provider_names,
    )

    providers = sorted(set(registered_provider_names()))
    models = dict(sorted(model_to_provider_map().items()))
    aliases = sorted({name.lstrip("@") for name in model_alias_names() if name})
    return {
        "schema_version": 1,
        "providers": providers,
        "models": models,
        "aliases": aliases,
        "effort_levels": list(EFFORT_LEVELS_ORDERED),
    }
