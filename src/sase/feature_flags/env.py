"""Environment transport for resolved feature flags."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any

from sase.feature_flags.models import FeatureFlagEnvError, FeatureFlagSnapshot


SASE_FEATURE_FLAGS_ENV = "SASE_FEATURE_FLAGS"


@dataclass(frozen=True)
class _LegacyEnvMapping:
    """A retired env var that still maps into one registered flag."""

    name: str
    key: str
    invert: bool = False


_LEGACY_ENV_MAPPINGS: tuple[_LegacyEnvMapping, ...] = (
    _LegacyEnvMapping(
        name="SASE_DISABLE_PRETTIER",
        key="prettier_enabled",
        invert=True,
    ),
)


def collect_legacy_env_values(
    environ: Mapping[str, str],
) -> dict[str, tuple[bool, str]]:
    """Return ``{flag_key: (enabled, env_name)}`` for set legacy env vars.

    A non-empty value is treated as set, matching the historical
    ``os.environ.get(name)`` truthiness of ``SASE_DISABLE_PRETTIER``.
    """
    values: dict[str, tuple[bool, str]] = {}
    for mapping in _LEGACY_ENV_MAPPINGS:
        raw = environ.get(mapping.name)
        if not raw:
            continue
        values[mapping.key] = (not mapping.invert, mapping.name)
    return values


def parse_feature_flags_env(raw: str) -> dict[str, bool]:
    """Parse the strict ``SASE_FEATURE_FLAGS`` JSON transport."""
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeatureFlagEnvError(
            f"{SASE_FEATURE_FLAGS_ENV} must be JSON object of booleans: {raw!r}"
        ) from exc

    if not isinstance(payload, dict):
        raise FeatureFlagEnvError(
            f"{SASE_FEATURE_FLAGS_ENV} must be JSON object of booleans: {raw!r}"
        )

    values: dict[str, bool] = {}
    for key, value in payload.items():
        if type(value) is not bool:
            raise FeatureFlagEnvError(
                f"{SASE_FEATURE_FLAGS_ENV} value for {key!r} must be boolean: {raw!r}"
            )
        values[str(key)] = value
    return values


def encode_feature_flags_env(snapshot: FeatureFlagSnapshot) -> str:
    """Encode every resolved flag value into stable JSON."""
    values = {
        key: snapshot.decisions[key].enabled for key in sorted(snapshot.decisions)
    }
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


def apply_feature_flags_env(
    snapshot: FeatureFlagSnapshot,
    env: MutableMapping[str, str] = os.environ,
) -> None:
    """Write the resolved feature-flag transport into *env*."""
    env[SASE_FEATURE_FLAGS_ENV] = encode_feature_flags_env(snapshot)


__all__ = [
    "SASE_FEATURE_FLAGS_ENV",
    "apply_feature_flags_env",
    "collect_legacy_env_values",
    "encode_feature_flags_env",
    "parse_feature_flags_env",
]
