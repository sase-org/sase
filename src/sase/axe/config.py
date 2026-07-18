"""Configuration for the lumberjack-based axe architecture.

Loads lumberjack definitions from the ``axe:`` section of the merged config
and validates the section through the shared Rust chop engine before turning
it into Python runtime dataclasses. Invalid configuration is rejected with
path- and source-aware diagnostics instead of being silently defaulted.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from sase.config import load_merged_config
from sase.config.core import ConfigLayer, load_config_layers
from sase.core.axe_chop_facade import parse_chop_duration, validate_axe_config

DEFAULT_LUMBERJACK_LOG_MAX_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True)
class _AxeConfigDiagnostic:
    """One fail-closed axe configuration diagnostic from the Rust core."""

    code: str
    message: str
    path: str | None = None
    layer: str | None = None
    severity: str = "error"

    @classmethod
    def from_wire(cls, payload: dict[str, Any]) -> _AxeConfigDiagnostic:
        return cls(
            code=str(payload["code"]),
            message=str(payload["message"]),
            path=str(payload["path"]) if payload.get("path") else None,
            layer=str(payload["layer"]) if payload.get("layer") else None,
            severity=str(payload.get("severity", "error")),
        )

    def format(self) -> str:
        """Render a compact config-path + provenance diagnostic."""
        location = self.path or "axe"
        source = f" (source: {self.layer})" if self.layer else ""
        return f"[{self.code}] {location}{source}: {self.message}"


class AxeConfigError(ValueError):
    """Raised when the effective ``axe:`` configuration is invalid."""

    def __init__(self, diagnostics: list[_AxeConfigDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        details = "\n".join(f"- {item.format()}" for item in diagnostics)
        super().__init__(f"Invalid axe configuration:\n{details}")


def _parse_duration(value: object) -> int | None:
    """Parse a validated positive compound duration into seconds."""
    if not isinstance(value, str):
        return None
    try:
        return parse_chop_duration(value)
    except (RuntimeError, ValueError):
        return None


@dataclass
class ChopConfig:
    """Configuration for a single script chop."""

    name: str
    description: str
    script: str | None = None
    run_every: int | None = None
    timeout: int | None = None
    env: dict[str, str] = field(default_factory=dict)
    inhibit_if: list[dict[str, Any]] = field(default_factory=list)
    trigger: dict[str, Any] = field(default_factory=lambda: {"provider": "always"})
    once_per: dict[str, Any] | None = None

    @property
    def script_name(self) -> str:
        """Return the exact executable name configured for this chop."""
        return self.script or self.name


@dataclass
class LumberjackConfig:
    """Configuration for a single lumberjack."""

    name: str
    interval: int
    chop_timeout: int | None = None
    chops: list[ChopConfig] = field(default_factory=list)

    @property
    def chop_names(self) -> list[str]:
        """Return just the chop names as strings."""
        return [c.name for c in self.chops]


@dataclass
class AxeConfig:
    """Top-level axe configuration with lumberjack definitions."""

    max_hook_runners: int = 3
    max_agent_runners: int = 3
    zombie_timeout_seconds: int = 7200
    lumberjack_log_max_bytes: int = DEFAULT_LUMBERJACK_LOG_MAX_BYTES
    verbose_lumberjack_diagnostics: bool = False
    query: str = ""
    chop_script_dirs: list[str] = field(default_factory=list)
    lumberjacks: dict[str, LumberjackConfig] = field(default_factory=dict)


def _normalize_guards(value: object) -> list[dict[str, Any]]:
    """Normalize validated keyed/tagged guard config for the Rust facade."""
    if isinstance(value, list):
        return [deepcopy(item) for item in value if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []

    guards: list[dict[str, Any]] = []
    for provider, raw_settings in value.items():
        settings_rows = (
            raw_settings if isinstance(raw_settings, list) else [raw_settings]
        )
        for raw_setting in settings_rows:
            if not isinstance(raw_setting, dict):
                continue
            guards.append({"provider": str(provider), **deepcopy(raw_setting)})
    return guards


def _normalize_trigger(value: object) -> dict[str, Any]:
    """Normalize validated string/keyed/tagged trigger config."""
    if value is None:
        return {"provider": "always"}
    if isinstance(value, str):
        return {"provider": value}
    if not isinstance(value, dict):
        return {"provider": "always"}
    if "provider" in value:
        return deepcopy(value)
    if len(value) != 1:
        return {"provider": "always"}
    provider, raw_settings = next(iter(value.items()))
    settings = raw_settings if isinstance(raw_settings, dict) else {}
    normalized = {"provider": str(provider), **deepcopy(settings)}
    if "checkpoint" in normalized and "checkpoint_policy" not in normalized:
        normalized["checkpoint_policy"] = normalized.pop("checkpoint")
    return normalized


def _normalize_once_per(value: object) -> dict[str, Any] | None:
    """Normalize validated once-per shorthand into its wire-shaped object."""
    if isinstance(value, str):
        return {"key": value, "capacity": 1024}
    if isinstance(value, dict):
        normalized = deepcopy(value)
        normalized.setdefault("capacity", 1024)
        return normalized
    return None


def _parse_lumberjacks(raw: dict[str, Any]) -> dict[str, LumberjackConfig]:
    """Turn a core-validated ``lumberjacks:`` mapping into dataclasses."""
    result: dict[str, LumberjackConfig] = {}
    for name, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue
        raw_chops = cfg.get("chops", [])
        chops: list[ChopConfig] = []
        if isinstance(raw_chops, list):
            for entry in raw_chops:
                if isinstance(entry, dict):
                    chop_name = str(entry["name"])
                    raw_env = entry.get("env", {})
                    env = (
                        {str(k): str(v) for k, v in raw_env.items()}
                        if isinstance(raw_env, dict)
                        else {}
                    )
                    chops.append(
                        ChopConfig(
                            name=chop_name,
                            description=str(entry.get("description", "")),
                            script=str(entry.get("script") or chop_name),
                            run_every=_parse_duration(entry.get("run_every")),
                            timeout=_parse_duration(entry.get("timeout")),
                            env=env,
                            inhibit_if=_normalize_guards(entry.get("inhibit_if")),
                            trigger=_normalize_trigger(entry.get("trigger")),
                            once_per=_normalize_once_per(entry.get("once_per")),
                        )
                    )
                elif isinstance(entry, str):
                    chops.append(ChopConfig(name=entry, description="", script=entry))
        chop_timeout = _parse_duration(cfg.get("chop_timeout"))
        result[name] = LumberjackConfig(
            name=name,
            interval=int(cfg.get("interval", 1)),
            chop_timeout=chop_timeout,
            chops=chops,
        )
    return result


def _layer_label(layer: ConfigLayer) -> str:
    if layer.path:
        return f"{layer.name}:{layer.path}"
    return layer.name


def _clear_provenance_subtree(provenance: dict[str, str], path: str) -> None:
    prefix_dot = f"{path}." if path else ""
    prefix_index = f"{path}[" if path else "["
    for key in tuple(provenance):
        if key == path or key.startswith(prefix_dot) or key.startswith(prefix_index):
            provenance.pop(key, None)


def _record_provenance_tree(
    value: object,
    *,
    path: str,
    label: str,
    provenance: dict[str, str],
) -> None:
    provenance[path] = label
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            _record_provenance_tree(
                child,
                path=child_path,
                label=label,
                provenance=provenance,
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _record_provenance_tree(
                child,
                path=f"{path}[{index}]",
                label=label,
                provenance=provenance,
            )


def _merge_with_provenance(
    base: object,
    override: object,
    *,
    path: str,
    label: str,
    list_strategy: str,
    provenance: dict[str, str],
) -> object:
    """Mirror config merge semantics while retaining exact source paths."""
    if isinstance(base, dict) and isinstance(override, dict):
        dict_result = deepcopy(base)
        provenance[path] = label
        for key, value in override.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in dict_result:
                dict_result[key] = _merge_with_provenance(
                    dict_result[key],
                    value,
                    path=child_path,
                    label=label,
                    list_strategy=list_strategy,
                    provenance=provenance,
                )
            else:
                dict_result[key] = deepcopy(value)
                _record_provenance_tree(
                    value,
                    path=child_path,
                    label=label,
                    provenance=provenance,
                )
        return dict_result

    if isinstance(base, list) and isinstance(override, list):
        if list_strategy == "replace":
            _clear_provenance_subtree(provenance, path)
            list_result = deepcopy(override)
            _record_provenance_tree(
                list_result,
                path=path,
                label=label,
                provenance=provenance,
            )
            return list_result
        list_result = deepcopy(base)
        provenance[path] = label
        offset = len(list_result)
        list_result.extend(deepcopy(override))
        for index, child in enumerate(override, start=offset):
            _record_provenance_tree(
                child,
                path=f"{path}[{index}]",
                label=label,
                provenance=provenance,
            )
        return list_result

    _clear_provenance_subtree(provenance, path)
    scalar_result = deepcopy(override)
    _record_provenance_tree(
        scalar_result,
        path=path,
        label=label,
        provenance=provenance,
    )
    return scalar_result


def _axe_config_provenance() -> dict[str, str]:
    """Build dotted-path provenance for the effective ``axe:`` section."""
    merged: object = {}
    provenance: dict[str, str] = {}
    for layer in load_config_layers():
        if not isinstance(layer.data, dict) or "axe" not in layer.data:
            continue
        merged = _merge_with_provenance(
            merged,
            {"axe": layer.data["axe"]},
            path="",
            label=_layer_label(layer),
            list_strategy=layer.list_strategy,
            provenance=provenance,
        )
    return provenance


def _validate_effective_axe_config(data: dict[str, Any]) -> None:
    request: dict[str, Any]
    if "axe" in data:
        request = {"axe": data["axe"]}
    else:
        request = {}
    diagnostics = validate_axe_config(request)
    if not diagnostics:
        return
    # Provenance discovery performs file/plugin IO, so only pay for it on the
    # error path. The second core pass attaches source labels authoritatively.
    diagnostics = validate_axe_config(request, provenance=_axe_config_provenance())
    raise AxeConfigError([_AxeConfigDiagnostic.from_wire(item) for item in diagnostics])


def load_axe_config() -> AxeConfig:
    """Load and fail-closed validate the effective axe configuration."""
    data = load_merged_config()
    _validate_effective_axe_config(data)

    axe_data = data.get("axe")
    if not isinstance(axe_data, dict):
        return AxeConfig()

    raw_lumberjacks = axe_data.get("lumberjacks")
    lumberjacks = (
        _parse_lumberjacks(raw_lumberjacks) if isinstance(raw_lumberjacks, dict) else {}
    )

    return AxeConfig(
        max_hook_runners=int(axe_data.get("max_hook_runners", 3)),
        max_agent_runners=int(axe_data.get("max_agent_runners", 3)),
        zombie_timeout_seconds=int(axe_data.get("zombie_timeout_seconds", 7200)),
        lumberjack_log_max_bytes=int(
            axe_data.get(
                "lumberjack_log_max_bytes",
                DEFAULT_LUMBERJACK_LOG_MAX_BYTES,
            )
        ),
        verbose_lumberjack_diagnostics=bool(
            axe_data.get("verbose_lumberjack_diagnostics", False)
        ),
        query=str(axe_data.get("query", "")),
        chop_script_dirs=[str(item) for item in axe_data.get("chop_script_dirs", [])],
        lumberjacks=lumberjacks,
    )
