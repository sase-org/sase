"""Pure feature-flag resolution over explicit inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV, parse_feature_flags_env
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDefinition,
    FeatureFlagDiagnostic,
    FeatureFlagSnapshot,
    FlagSource,
)


@dataclass(frozen=True)
class FeatureFlagLayerInput:
    """Raw ``feature_flags`` values from a single config layer."""

    name: str
    detail: str
    values: Mapping[str, Any]


def _diagnostic(
    *,
    code: str,
    message: str,
    source: str,
) -> FeatureFlagDiagnostic:
    return FeatureFlagDiagnostic(
        severity="warning",
        code=code,
        message=message,
        source=source,
    )


def _layer_source(name: str) -> FlagSource | None:
    if name == "user":
        return "user"
    if name == "local":
        return "local"
    if name.startswith("overlay:"):
        return "overlay"
    return None


def _source_detail(layer: FeatureFlagLayerInput) -> str:
    if layer.detail:
        return layer.detail
    if layer.name.startswith("overlay:"):
        return layer.name
    return ""


def _apply_values(
    *,
    decisions: dict[str, FeatureFlagDecision],
    definitions: Mapping[str, FeatureFlagDefinition],
    values: Mapping[str, Any],
    source: FlagSource,
    source_detail: str,
    diagnostic_source: str,
    diagnostics: list[FeatureFlagDiagnostic],
) -> None:
    for key, value in values.items():
        key_text = str(key)
        definition = definitions.get(key_text)
        if definition is None:
            diagnostics.append(
                _diagnostic(
                    code="unknown_key",
                    message=f"unknown feature flag {key_text!r} ignored",
                    source=diagnostic_source,
                )
            )
            continue
        if type(value) is not bool:
            diagnostics.append(
                _diagnostic(
                    code="not_boolean",
                    message=f"feature flag {key_text!r} must be boolean",
                    source=diagnostic_source,
                )
            )
            continue
        if source == "local" and definition.scope == "global":
            diagnostics.append(
                _diagnostic(
                    code="scope_violation",
                    message=(
                        f"global feature flag {key_text!r} cannot be overridden "
                        "by local config"
                    ),
                    source=diagnostic_source,
                )
            )
            continue

        decisions[key_text] = FeatureFlagDecision(
            key=key_text,
            enabled=value,
            default=definition.default,
            source=source,
            source_detail=source_detail,
            overridden=True,
        )


def resolve_feature_flags(
    *,
    definitions: Mapping[str, FeatureFlagDefinition],
    layers: Sequence[FeatureFlagLayerInput],
    overrides: Mapping[str, bool] | None = None,
    env_value: str | None = None,
) -> FeatureFlagSnapshot:
    """Resolve feature flags through config layers, overrides, and env."""
    decisions = {
        key: FeatureFlagDecision(
            key=key,
            enabled=definition.default,
            default=definition.default,
            source="default",
            source_detail="",
            overridden=False,
        )
        for key, definition in sorted(definitions.items())
    }
    diagnostics: list[FeatureFlagDiagnostic] = []

    for layer in layers:
        if layer.name == "default":
            if layer.values:
                diagnostics.append(
                    _diagnostic(
                        code="default_layer_ignored",
                        message=(
                            "default config must not define feature_flags; "
                            "registry defaults are authoritative"
                        ),
                        source=layer.name,
                    )
                )
            continue
        if layer.name.startswith("plugin:"):
            continue

        source = _layer_source(layer.name)
        if source is None:
            continue
        _apply_values(
            decisions=decisions,
            definitions=definitions,
            values=layer.values,
            source=source,
            source_detail=_source_detail(layer),
            diagnostic_source=layer.name,
            diagnostics=diagnostics,
        )

    if overrides:
        _apply_values(
            decisions=decisions,
            definitions=definitions,
            values=overrides,
            source="override",
            source_detail="",
            diagnostic_source="override",
            diagnostics=diagnostics,
        )

    if env_value is not None:
        _apply_values(
            decisions=decisions,
            definitions=definitions,
            values=parse_feature_flags_env(env_value),
            source="env",
            source_detail=SASE_FEATURE_FLAGS_ENV,
            diagnostic_source="env",
            diagnostics=diagnostics,
        )

    return FeatureFlagSnapshot(decisions=decisions, diagnostics=tuple(diagnostics))
