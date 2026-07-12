"""Launch-family-scoped model alias override environment handling."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType
from typing import Any

SASE_MODEL_ALIAS_OVERRIDES_ENV = "SASE_MODEL_ALIAS_OVERRIDES"


def active_launch_alias_overrides(
    explicit: Mapping[str, str] | None = None,
) -> Mapping[str, str]:
    """Return explicit overrides, or the validated map inherited via the env."""
    if explicit is not None:
        return MappingProxyType(_clean_mapping(explicit))
    return _parse_env_value(os.environ.get(SASE_MODEL_ALIAS_OVERRIDES_ENV, ""))


def encode_launch_alias_overrides(overrides: Mapping[str, str]) -> str:
    """Serialize an override mapping for a child-process environment."""
    return json.dumps(_clean_mapping(overrides), sort_keys=True)


def export_launch_alias_overrides(overrides: Mapping[str, str]) -> None:
    """Export non-empty overrides for in-process family follow-ups."""
    cleaned = _clean_mapping(overrides)
    if cleaned:
        os.environ[SASE_MODEL_ALIAS_OVERRIDES_ENV] = json.dumps(
            cleaned,
            sort_keys=True,
        )


@lru_cache(maxsize=16)
def _parse_env_value(raw: str) -> Mapping[str, str]:
    if not raw:
        return MappingProxyType({})
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return MappingProxyType({})
    if not isinstance(value, dict):
        return MappingProxyType({})
    return MappingProxyType(_clean_mapping(value))


def _clean_mapping(value: Mapping[Any, Any]) -> dict[str, str]:
    return {
        key.strip(): item.strip()
        for key, item in value.items()
        if isinstance(key, str)
        and isinstance(item, str)
        and key.strip()
        and item.strip()
    }


__all__ = [
    "SASE_MODEL_ALIAS_OVERRIDES_ENV",
    "active_launch_alias_overrides",
    "encode_launch_alias_overrides",
    "export_launch_alias_overrides",
]
