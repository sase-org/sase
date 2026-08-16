"""Helpers for feature-flag tests."""

from __future__ import annotations

from typing import Any, cast

from sase.feature_flags import FeatureFlag, FeatureFlagDefinition
from sase.feature_flags.models import FlagKind, FlagScope
from sase.feature_flags.resolver import FeatureFlagLayerInput


def demo_flag(
    key: str = "demo_flag",
    *,
    default: bool = False,
    scope: FlagScope = "project",
    kind: FlagKind = "beta",
    description: str | None = None,
) -> FeatureFlagDefinition:
    return FeatureFlagDefinition(
        key=cast(FeatureFlag, key),
        kind=kind,
        description=description or f"Description for {key}",
        default=default,
        scope=scope,
        bead=None if kind == "ops" else "sase-nb.test",
        rationale="Operational escape hatch" if kind == "ops" else "",
    )


def definitions(
    *flags: FeatureFlagDefinition,
) -> dict[str, FeatureFlagDefinition]:
    return {str(flag.key): flag for flag in flags}


def layer(
    name: str,
    values: dict[str, Any],
    *,
    detail: str = "",
) -> FeatureFlagLayerInput:
    return FeatureFlagLayerInput(name=name, detail=detail, values=values)
