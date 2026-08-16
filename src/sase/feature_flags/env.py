"""Environment transport for resolved feature flags."""

from __future__ import annotations

import json
import os
from collections.abc import MutableMapping
from typing import Any

from sase.feature_flags.models import FeatureFlagEnvError, FeatureFlagSnapshot


SASE_FEATURE_FLAGS_ENV = "SASE_FEATURE_FLAGS"


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
