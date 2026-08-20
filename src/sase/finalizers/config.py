"""Configuration loading for host-owned finalizer instances."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
import re
from typing import Any

from sase.config.core import ConfigLayer, load_config_layers
from sase.core.finalizer_facade import finalizer_json_digest
from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerInstancePolicyWire,
    FinalizerInstanceSpecWire,
    FinalizerPlanInputWire,
    FinalizerSelectorOpWire,
)


_INSTANCE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_FINALIZER_KEYS = frozenset({"defaults", "required", "instances"})
_INSTANCE_KEYS = frozenset({"use", "after", "max_attempts", "refusal", "config"})
_BUILTIN_PROVIDER_REFS = frozenset({"builtin@command", "builtin@commit"})
_DISABLE_COMMIT_STOP_HOOK_ENV = "SASE_DISABLE_COMMIT_STOP_HOOK"


@dataclass(frozen=True)
class FinalizerConfigDiagnostic:
    """One non-fatal or fatal finalizer config diagnostic."""

    severity: str
    code: str
    message: str
    layer: str
    path: str


@dataclass(frozen=True)
class FinalizerFieldProvenance:
    """Layer provenance for one configured finalizer field."""

    layer: str
    path: str | None


@dataclass(frozen=True)
class _LegacyCommitFinalizerField:
    """Effective legacy commit-finalizer setting from one config layer."""

    value: object
    layer: str
    layer_path: str | None
    config_path: str


@dataclass(frozen=True)
class ConfiguredFinalizerInstance:
    """A configured finalizer instance plus field provenance."""

    instance_id: str
    provider_ref: str
    after: tuple[str, ...] = ()
    max_attempts: int = 1
    refusal: str = "fail"
    config: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, FinalizerFieldProvenance] = field(default_factory=dict)

    def to_wire(self) -> FinalizerInstanceSpecWire:
        return FinalizerInstanceSpecWire(
            schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
            instance_id=self.instance_id,
            provider_ref=self.provider_ref,
            after=list(self.after),
            policy=FinalizerInstancePolicyWire(
                max_attempts=self.max_attempts,
                refusal=self.refusal,
            ),
            config_digest=finalizer_json_digest(dict(self.config)),
            provenance_id=_primary_provenance_id(self.provenance),
        )


@dataclass(frozen=True)
class FinalizerConfig:
    """Effective finalizer configuration and provenance."""

    defaults: tuple[str, ...]
    required: tuple[str, ...]
    instances: Mapping[str, ConfiguredFinalizerInstance]
    provenance: Mapping[str, FinalizerFieldProvenance]
    diagnostics: tuple[FinalizerConfigDiagnostic, ...] = ()

    def fatal_diagnostics(self) -> tuple[FinalizerConfigDiagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity == "error")

    def to_plan_input(
        self,
        selectors: list[FinalizerSelectorOpWire],
    ) -> FinalizerPlanInputWire:
        return FinalizerPlanInputWire(
            schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
            instances=[self.instances[key].to_wire() for key in sorted(self.instances)],
            defaults=list(self.defaults),
            required=list(self.required),
            selectors=selectors,
        )


def load_finalizer_config() -> FinalizerConfig:
    """Replay config layers and retain source provenance for finalizers."""

    layers = load_config_layers()
    state = _MutableFinalizerConfig()
    for layer in layers:
        _merge_layer(state, layer)
    _apply_legacy_commit_finalizer_adapter(
        state,
        layers,
        explicit_new_finalizers=_explicit_new_finalizers_configured(layers),
    )
    return state.freeze()


def _merge_layer(state: _MutableFinalizerConfig, layer: ConfigLayer) -> None:
    raw = layer.data.get("finalizers")
    if raw is None:
        return
    path = layer.path
    if layer.name.startswith("plugin:"):
        state.diagnostics.append(
            FinalizerConfigDiagnostic(
                severity="error",
                code="plugin_config_activation",
                message=(
                    "plugin config layers cannot activate finalizer defaults, "
                    "requirements, or instances"
                ),
                layer=layer.name,
                path="finalizers",
            )
        )
        return
    if not isinstance(raw, Mapping):
        state.diagnostics.append(
            FinalizerConfigDiagnostic(
                severity="error",
                code="not_a_mapping",
                message="finalizers must be a mapping",
                layer=layer.name,
                path="finalizers",
            )
        )
        return
    for key in sorted(set(raw) - _FINALIZER_KEYS):
        state.diagnostics.append(
            FinalizerConfigDiagnostic(
                severity="error",
                code="unknown_key",
                message=f"unknown finalizers key {key!r}",
                layer=layer.name,
                path=f"finalizers.{key}",
            )
        )
    if "defaults" in raw:
        state.defaults = _string_list(raw["defaults"], state, layer, "defaults")
        state.provenance["defaults"] = FinalizerFieldProvenance(layer.name, path)
    if "required" in raw:
        state.required = _string_list(raw["required"], state, layer, "required")
        state.provenance["required"] = FinalizerFieldProvenance(layer.name, path)
    if "instances" in raw:
        _merge_instances(state, raw["instances"], layer)


def _merge_instances(
    state: _MutableFinalizerConfig,
    raw: object,
    layer: ConfigLayer,
) -> None:
    if not isinstance(raw, Mapping):
        state.diagnostics.append(
            FinalizerConfigDiagnostic(
                severity="error",
                code="instances_not_mapping",
                message="finalizers.instances must be a mapping",
                layer=layer.name,
                path="finalizers.instances",
            )
        )
        return
    for instance_id, value in raw.items():
        if (
            not isinstance(instance_id, str)
            or _INSTANCE_RE.fullmatch(instance_id) is None
        ):
            state.diagnostics.append(
                FinalizerConfigDiagnostic(
                    severity="error",
                    code="invalid_instance_id",
                    message=f"invalid finalizer instance ID {instance_id!r}",
                    layer=layer.name,
                    path="finalizers.instances",
                )
            )
            continue
        if not isinstance(value, Mapping):
            state.diagnostics.append(
                FinalizerConfigDiagnostic(
                    severity="error",
                    code="instance_not_mapping",
                    message=f"finalizer instance {instance_id!r} must be a mapping",
                    layer=layer.name,
                    path=f"finalizers.instances.{instance_id}",
                )
            )
            continue
        _merge_instance_fields(state, instance_id, value, layer)


def _merge_instance_fields(
    state: _MutableFinalizerConfig,
    instance_id: str,
    raw: Mapping[str, object],
    layer: ConfigLayer,
) -> None:
    current = state.instances.get(instance_id, {})
    provenance = dict(state.instance_provenance.get(instance_id, {}))
    for key in sorted(set(raw) - _INSTANCE_KEYS):
        state.diagnostics.append(
            FinalizerConfigDiagnostic(
                severity="error",
                code="unknown_instance_key",
                message=f"unknown finalizer instance key {key!r}",
                layer=layer.name,
                path=f"finalizers.instances.{instance_id}.{key}",
            )
        )
    for key in _INSTANCE_KEYS:
        if key not in raw:
            continue
        current[key] = _normalize_instance_field(
            state,
            layer,
            instance_id,
            key,
            raw[key],
        )
        provenance[key] = FinalizerFieldProvenance(layer.name, layer.path)
    state.instances[instance_id] = current
    state.instance_provenance[instance_id] = provenance


def _normalize_instance_field(
    state: _MutableFinalizerConfig,
    layer: ConfigLayer,
    instance_id: str,
    key: str,
    value: object,
) -> object:
    path = f"finalizers.instances.{instance_id}.{key}"
    if key == "use":
        if isinstance(value, str) and value.strip():
            return value.strip()
        state.diagnostics.append(_type_error(layer, path, "a non-empty string"))
        return ""
    if key == "after":
        return _string_list(value, state, layer, f"instances.{instance_id}.after")
    if key == "max_attempts":
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
        state.diagnostics.append(_type_error(layer, path, "an integer >= 1"))
        return 1
    if key == "refusal":
        if value == "fail":
            return "fail"
        state.diagnostics.append(_type_error(layer, path, "'fail'"))
        return "fail"
    if key == "config":
        if isinstance(value, Mapping):
            return dict(value)
        state.diagnostics.append(_type_error(layer, path, "a mapping"))
        return {}
    raise AssertionError(key)


def _string_list(
    value: object,
    state: _MutableFinalizerConfig,
    layer: ConfigLayer,
    field_name: str,
) -> tuple[str, ...]:
    path = f"finalizers.{field_name}"
    if not isinstance(value, list):
        state.diagnostics.append(_type_error(layer, path, "a list of strings"))
        return ()
    strings: list[str] = []
    for index, item in enumerate(value):
        if isinstance(item, str) and item.strip():
            strings.append(item.strip())
            continue
        state.diagnostics.append(
            _type_error(layer, f"{path}[{index}]", "a non-empty string")
        )
    return tuple(strings)


def _type_error(
    layer: ConfigLayer,
    path: str,
    expected: str,
) -> FinalizerConfigDiagnostic:
    return FinalizerConfigDiagnostic(
        severity="error",
        code="invalid_value",
        message=f"{path} must be {expected}",
        layer=layer.name,
        path=path,
    )


def _explicit_new_finalizers_configured(layers: list[ConfigLayer]) -> bool:
    return any(
        layer.name != "default"
        and not layer.name.startswith("plugin:")
        and isinstance(layer.data.get("finalizers"), Mapping)
        for layer in layers
    )


def _apply_legacy_commit_finalizer_adapter(
    state: _MutableFinalizerConfig,
    layers: list[ConfigLayer],
    *,
    explicit_new_finalizers: bool,
) -> None:
    enabled = _effective_legacy_field(layers, "enabled")
    max_passes = _effective_legacy_field(layers, "max_passes")
    disable_env = bool(os.environ.get(_DISABLE_COMMIT_STOP_HOOK_ENV))

    if explicit_new_finalizers:
        for field in (enabled, max_passes):
            if field is not None:
                state.diagnostics.append(
                    FinalizerConfigDiagnostic(
                        severity="warning",
                        code="legacy_commit_finalizer_ignored",
                        message=(
                            f"legacy {field.config_path} is ignored because this "
                            "configuration also defines finalizers"
                        ),
                        layer=field.layer,
                        path=field.config_path,
                    )
                )
        if disable_env:
            state.diagnostics.append(
                FinalizerConfigDiagnostic(
                    severity="warning",
                    code="legacy_commit_finalizer_env_ignored",
                    message=(
                        f"{_DISABLE_COMMIT_STOP_HOOK_ENV} is ignored because "
                        "finalizers is explicitly configured"
                    ),
                    layer="environment",
                    path=_DISABLE_COMMIT_STOP_HOOK_ENV,
                )
            )
        return

    if max_passes is not None:
        normalized = _normalize_legacy_max_passes(max_passes.value)
        _ensure_commit_instance_defaults(state)
        state.instances.setdefault("commit", {})["max_attempts"] = normalized
        state.instance_provenance.setdefault("commit", {})["max_attempts"] = (
            FinalizerFieldProvenance(max_passes.layer, max_passes.layer_path)
        )
        state.diagnostics.append(
            FinalizerConfigDiagnostic(
                severity="warning",
                code="legacy_commit_finalizer_mapped",
                message=(
                    "legacy commit.finalizer.max_passes maps to "
                    "finalizers.instances.commit.max_attempts during the "
                    "pluggable finalizers beta"
                ),
                layer=max_passes.layer,
                path=max_passes.config_path,
            )
        )

    if enabled is not None:
        mapped_enabled = enabled.value if isinstance(enabled.value, bool) else True
        if not isinstance(enabled.value, bool):
            state.diagnostics.append(
                FinalizerConfigDiagnostic(
                    severity="warning",
                    code="legacy_commit_finalizer_invalid",
                    message="legacy commit.finalizer.enabled must be a boolean",
                    layer=enabled.layer,
                    path=enabled.config_path,
                )
            )
        _map_legacy_enabled(state, mapped_enabled, enabled)

    if disable_env:
        state.defaults = ()
        state.provenance["defaults"] = FinalizerFieldProvenance("environment", None)
        state.diagnostics.append(
            FinalizerConfigDiagnostic(
                severity="warning",
                code="legacy_commit_finalizer_env_mapped",
                message=(
                    f"{_DISABLE_COMMIT_STOP_HOOK_ENV} disables default finalizers "
                    "only because no explicit finalizers policy is configured"
                ),
                layer="environment",
                path=_DISABLE_COMMIT_STOP_HOOK_ENV,
            )
        )


def _effective_legacy_field(
    layers: list[ConfigLayer],
    key: str,
) -> _LegacyCommitFinalizerField | None:
    effective: _LegacyCommitFinalizerField | None = None
    for layer in layers:
        if layer.name == "default" or layer.name.startswith("plugin:"):
            continue
        finalizer = _legacy_commit_finalizer_mapping(layer.data)
        if finalizer is None or key not in finalizer:
            continue
        effective = _LegacyCommitFinalizerField(
            value=finalizer[key],
            layer=layer.name,
            layer_path=layer.path,
            config_path=f"commit.finalizer.{key}",
        )
    return effective


def _legacy_commit_finalizer_mapping(
    data: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    commit = data.get("commit")
    if not isinstance(commit, Mapping):
        return None
    finalizer = commit.get("finalizer")
    return finalizer if isinstance(finalizer, Mapping) else None


def _normalize_legacy_max_passes(value: object) -> int:
    if isinstance(value, bool):
        return 2
    if isinstance(value, int):
        return max(1, value)
    if not isinstance(value, str):
        return 2
    try:
        return max(1, int(value))
    except ValueError:
        return 2


def _ensure_commit_instance_defaults(state: _MutableFinalizerConfig) -> None:
    fields = state.instances.setdefault("commit", {})
    fields.setdefault("use", "builtin@commit")
    fields.setdefault("after", ())
    fields.setdefault("refusal", "fail")


def _map_legacy_enabled(
    state: _MutableFinalizerConfig,
    enabled: bool,
    field: _LegacyCommitFinalizerField,
) -> None:
    if enabled:
        _ensure_commit_instance_defaults(state)
    state.defaults = ("commit",) if enabled else ()
    state.provenance["defaults"] = FinalizerFieldProvenance(
        field.layer,
        field.layer_path,
    )
    state.diagnostics.append(
        FinalizerConfigDiagnostic(
            severity="warning",
            code="legacy_commit_finalizer_mapped",
            message=(
                "legacy commit.finalizer.enabled maps to finalizers.defaults "
                "during the pluggable finalizers beta"
            ),
            layer=field.layer,
            path=field.config_path,
        )
    )


def _primary_provenance_id(
    provenance: Mapping[str, FinalizerFieldProvenance],
) -> str | None:
    item = provenance.get("use")
    if item is None:
        return None
    return item.layer if item.path is None else f"{item.layer}:{item.path}"


@dataclass
class _MutableFinalizerConfig:
    defaults: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    instances: dict[str, dict[str, object]] = field(default_factory=dict)
    provenance: dict[str, FinalizerFieldProvenance] = field(default_factory=dict)
    instance_provenance: dict[str, dict[str, FinalizerFieldProvenance]] = field(
        default_factory=dict
    )
    diagnostics: list[FinalizerConfigDiagnostic] = field(default_factory=list)

    def freeze(self) -> FinalizerConfig:
        instances: dict[str, ConfiguredFinalizerInstance] = {}
        for instance_id, fields in self.instances.items():
            provider_ref = fields.get("use")
            if not isinstance(provider_ref, str) or not provider_ref:
                self.diagnostics.append(
                    FinalizerConfigDiagnostic(
                        severity="error",
                        code="missing_provider",
                        message=f"finalizer instance {instance_id!r} requires use",
                        layer="merged",
                        path=f"finalizers.instances.{instance_id}.use",
                    )
                )
                continue
            if provider_ref not in _BUILTIN_PROVIDER_REFS and "@" not in provider_ref:
                self.diagnostics.append(
                    FinalizerConfigDiagnostic(
                        severity="error",
                        code="invalid_provider_ref",
                        message=(
                            f"finalizer instance {instance_id!r} has invalid "
                            f"provider ref {provider_ref!r}"
                        ),
                        layer="merged",
                        path=f"finalizers.instances.{instance_id}.use",
                    )
                )
            after_value = fields.get("after", ())
            after = after_value if isinstance(after_value, tuple) else ()
            max_attempts_value = fields.get("max_attempts", 1)
            max_attempts = (
                max_attempts_value if isinstance(max_attempts_value, int) else 1
            )
            config_value = fields.get("config")
            config = dict(config_value) if isinstance(config_value, Mapping) else {}
            instances[instance_id] = ConfiguredFinalizerInstance(
                instance_id=instance_id,
                provider_ref=provider_ref,
                after=after,
                max_attempts=max_attempts,
                refusal=str(fields.get("refusal", "fail")),
                config=config,
                provenance=dict(self.instance_provenance.get(instance_id, {})),
            )
        return FinalizerConfig(
            defaults=self.defaults,
            required=self.required,
            instances=instances,
            provenance=dict(self.provenance),
            diagnostics=tuple(self.diagnostics),
        )


__all__ = [
    "ConfiguredFinalizerInstance",
    "FinalizerConfig",
    "FinalizerConfigDiagnostic",
    "FinalizerFieldProvenance",
    "load_finalizer_config",
]
