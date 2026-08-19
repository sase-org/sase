"""Helpers for feature-flag tests."""

from __future__ import annotations

from typing import Any, cast

from sase.feature_flags import FeatureFlag, FeatureFlagDefinition
from sase.feature_flags.models import FlagKind, FlagSource
from sase.feature_flags.beads import FlagBeadSnapshot
from sase.feature_flags.models import FeatureFlagDecision, FeatureFlagSnapshot
from sase.feature_flags.resolver import FeatureFlagLayerInput


def demo_flag(
    key: str = "demo_flag",
    *,
    kind: FlagKind = "beta",
    description: str | None = None,
    bead: str | None = "sase-nb.test",
) -> FeatureFlagDefinition:
    return FeatureFlagDefinition(
        key=cast(FeatureFlag, key),
        kind=kind,
        description=description or f"Description for {key}",
        bead=bead,
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


def snapshot_for(
    *flags: FeatureFlagDefinition,
    enabled: dict[str, bool] | None = None,
    source: FlagSource = "default",
    source_detail: str = "",
    diagnostics: tuple[Any, ...] = (),
) -> FeatureFlagSnapshot:
    overrides = enabled or {}
    decisions = {}
    for flag in flags:
        key = str(flag.key)
        value = overrides.get(key, flag.default)
        decisions[key] = FeatureFlagDecision(
            key=key,
            enabled=value,
            default=flag.default,
            source=source if key in overrides or source != "default" else "default",
            source_detail=source_detail,
            overridden=value != flag.default or source != "default",
        )
    return FeatureFlagSnapshot(decisions=decisions, diagnostics=diagnostics)


def flag_bead(
    key: str = "demo_flag",
    *,
    bead_id: str = "sase-nb.test",
    status: str = "open",
    remove_by_date: str = "2026-12-01",
    remove_by_release: str = "0.19.0",
    task_type: str = "flag",
    kind: str | None = None,
    title: str = "Retire demo_flag",
    created_at: str = "",
    created_by: str = "",
) -> FlagBeadSnapshot:
    return FlagBeadSnapshot(
        id=bead_id,
        status=status,
        key=key,
        remove_by_date=remove_by_date,
        remove_by_release=remove_by_release,
        task_type=task_type,
        kind=kind,
        title=title,
        created_at=created_at,
        created_by=created_by,
    )
