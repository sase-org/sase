"""Configuration loading for host-owned finalizer instances."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
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
from sase.plugins.qualified_id import (
    PluginQualifiedIdError,
    canonical_plugin_qualified_id,
)


_INSTANCE_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
_FINALIZER_KEYS = frozenset({"defaults", "required", "instances"})
_INSTANCE_KEYS = frozenset({"use", "after", "max_attempts", "refusal", "config"})
_BUILTIN_PROVIDER_REFS = frozenset({"builtin@command", "builtin@commit"})


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


def _configured_instance_to_json(
    instance: ConfiguredFinalizerInstance,
) -> dict[str, Any]:
    """Serialize a configured instance, including field provenance, to JSON."""

    return {
        "instance_id": instance.instance_id,
        "provider_ref": instance.provider_ref,
        "after": list(instance.after),
        "max_attempts": instance.max_attempts,
        "refusal": instance.refusal,
        "config": dict(instance.config),
        "provenance": _provenance_to_json(instance.provenance),
    }


def _configured_instance_from_json(payload: object) -> ConfiguredFinalizerInstance:
    """Strictly rebuild a configured instance from its JSON snapshot.

    A missing or malformed field is a tamper signal, not a fallback: this never
    defaults a field the way live config merging does.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("configured finalizer instance snapshot must be a mapping")
    try:
        instance_id = payload["instance_id"]
        provider_ref = payload["provider_ref"]
        after = payload["after"]
        max_attempts = payload["max_attempts"]
        refusal = payload["refusal"]
        config = payload["config"]
        provenance_raw = payload["provenance"]
    except KeyError as exc:
        raise ValueError(
            f"configured finalizer instance snapshot is missing {exc}"
        ) from exc
    if not (
        isinstance(instance_id, str)
        and isinstance(provider_ref, str)
        and isinstance(after, list)
        and all(isinstance(item, str) for item in after)
        and isinstance(max_attempts, int)
        and not isinstance(max_attempts, bool)
        and refusal in ("fail", "defer")
        and isinstance(config, Mapping)
        and isinstance(provenance_raw, Mapping)
    ):
        raise ValueError(
            f"configured finalizer instance snapshot for {instance_id!r} is malformed"
        )
    return ConfiguredFinalizerInstance(
        instance_id=instance_id,
        provider_ref=provider_ref,
        after=tuple(after),
        max_attempts=max_attempts,
        refusal=refusal,
        config=dict(config),
        provenance=_provenance_from_json(provenance_raw),
    )


def finalizer_config_to_json(config: FinalizerConfig) -> dict[str, Any]:
    """Serialize the effective finalizer config, including provenance, to JSON."""

    return {
        "defaults": list(config.defaults),
        "required": list(config.required),
        "instances": {
            instance_id: _configured_instance_to_json(instance)
            for instance_id, instance in config.instances.items()
        },
        "provenance": _provenance_to_json(config.provenance),
    }


def finalizer_config_from_json(payload: object) -> FinalizerConfig:
    """Strictly rebuild the effective finalizer config from its JSON snapshot."""

    if not isinstance(payload, Mapping):
        raise ValueError("finalizer config snapshot must be a mapping")
    try:
        defaults = payload["defaults"]
        required = payload["required"]
        instances_raw = payload["instances"]
        provenance_raw = payload["provenance"]
    except KeyError as exc:
        raise ValueError(f"finalizer config snapshot is missing {exc}") from exc
    if not (
        isinstance(defaults, list)
        and all(isinstance(item, str) for item in defaults)
        and isinstance(required, list)
        and all(isinstance(item, str) for item in required)
        and isinstance(instances_raw, Mapping)
        and isinstance(provenance_raw, Mapping)
    ):
        raise ValueError("finalizer config snapshot is malformed")
    instances: dict[str, ConfiguredFinalizerInstance] = {}
    for instance_id, raw_instance in instances_raw.items():
        if not isinstance(instance_id, str) or not isinstance(raw_instance, Mapping):
            raise ValueError("finalizer config snapshot instance entry is malformed")
        instances[instance_id] = _configured_instance_from_json(raw_instance)
    return FinalizerConfig(
        defaults=tuple(defaults),
        required=tuple(required),
        instances=instances,
        provenance=_provenance_from_json(provenance_raw),
        diagnostics=(),
    )


def _provenance_to_json(
    provenance: Mapping[str, FinalizerFieldProvenance],
) -> dict[str, dict[str, Any]]:
    return {
        key: {"layer": value.layer, "path": value.path}
        for key, value in provenance.items()
    }


def _provenance_from_json(
    payload: Mapping[str, Any],
) -> dict[str, FinalizerFieldProvenance]:
    provenance: dict[str, FinalizerFieldProvenance] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, Mapping):
            raise ValueError("finalizer config snapshot provenance entry is malformed")
        layer = value.get("layer")
        path = value.get("path")
        if not isinstance(layer, str) or not (path is None or isinstance(path, str)):
            raise ValueError("finalizer config snapshot provenance entry is malformed")
        provenance[key] = FinalizerFieldProvenance(layer, path)
    return provenance


def load_finalizer_config() -> FinalizerConfig:
    """Replay config layers and retain source provenance for finalizers."""

    layers = load_config_layers()
    state = _MutableFinalizerConfig()
    for layer in layers:
        _merge_layer(state, layer)
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
        if value in ("fail", "defer"):
            return value
        state.diagnostics.append(_type_error(layer, path, "'fail' or 'defer'"))
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
            try:
                provider_ref = canonical_plugin_qualified_id(provider_ref)
            except PluginQualifiedIdError:
                pass
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
    "finalizer_config_from_json",
    "finalizer_config_to_json",
    "load_finalizer_config",
]
