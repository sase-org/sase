"""Pure feature-flag resolution over explicit inputs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sase.feature_flags.env import (
    SASE_FEATURE_FLAGS_ENV,
    collect_legacy_env_values,
    parse_feature_flags_env,
)
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
        if source == "local":
            diagnostics.append(
                _diagnostic(
                    code="scope_violation",
                    message=(
                        f"feature flag {key_text!r} cannot be set from local config"
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
    legacy_env: Mapping[str, str] | None = None,
    cli: Mapping[str, bool] | None = None,
) -> FeatureFlagSnapshot:
    """Resolve feature flags through config layers, overrides, env, and CLI."""
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

    if legacy_env is not None:
        for key, (enabled, env_name) in collect_legacy_env_values(legacy_env).items():
            if key not in definitions:
                continue
            diagnostics.append(
                _diagnostic(
                    code="deprecated_env",
                    message=(
                        f"{env_name} is deprecated; set feature flag {key!r} "
                        f"via {SASE_FEATURE_FLAGS_ENV} or config instead"
                    ),
                    source=env_name,
                )
            )
            _apply_values(
                decisions=decisions,
                definitions=definitions,
                values={key: enabled},
                source="env",
                source_detail=env_name,
                diagnostic_source=env_name,
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

    if cli:
        cli_enabled = {key: True for key, value in cli.items() if value}
        cli_disabled = {key: False for key, value in cli.items() if not value}
        if cli_enabled:
            _apply_values(
                decisions=decisions,
                definitions=definitions,
                values=cli_enabled,
                source="cli",
                source_detail="--enable-feature",
                diagnostic_source="cli",
                diagnostics=diagnostics,
            )
        if cli_disabled:
            _apply_values(
                decisions=decisions,
                definitions=definitions,
                values=cli_disabled,
                source="cli",
                source_detail="--disable-feature",
                diagnostic_source="cli",
                diagnostics=diagnostics,
            )

    return FeatureFlagSnapshot(decisions=decisions, diagnostics=tuple(diagnostics))
