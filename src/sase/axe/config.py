"""Configuration for the lumberjack-based axe architecture.

Loads lumberjack definitions from the ``axe:`` section of the merged config
and validates the section through the shared Rust chop engine before turning
it into Python runtime dataclasses. Invalid configuration is rejected with
path- and source-aware diagnostics instead of being silently defaulted.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import json
import threading
import time
from typing import Any

from sase.config import load_merged_config
from sase.config.core import ConfigLayer, current_config_token, load_config_layers
from sase.core.axe_chop_facade import (
    CHOP_ENGINE_SCHEMA_VERSION,
    expand_chop_targets,
    parse_chop_duration,
    validate_axe_config,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name

from .chop_env import ChopEnvValue

DEFAULT_LUMBERJACK_LOG_MAX_BYTES = 50 * 1024 * 1024
_PROJECT_TARGET_CACHE_SECONDS = 30.0
_project_target_cache_lock = threading.RLock()
_project_target_cache_deadline = 0.0
_project_target_cache_rows: list[dict[str, Any]] | None = None
_keyed_config_cache_lock = threading.RLock()
_keyed_config_cache_token: tuple[Any, ...] | None = None
_keyed_config_cache_value: tuple[dict[str, Any], dict[str, str]] | None = None


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
    enabled: bool = True
    run_every: int | None = None
    timeout: int | None = None
    env: dict[str, ChopEnvValue] = field(default_factory=dict)
    inhibit_if: list[dict[str, Any]] = field(default_factory=list)
    trigger: dict[str, Any] = field(default_factory=lambda: {"provider": "always"})
    once_per: dict[str, Any] | None = None
    base_name: str | None = None
    target_key: str = ""
    target: dict[str, Any] = field(default_factory=dict)
    vars: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, str] = field(default_factory=dict)

    @property
    def script_name(self) -> str:
        """Return the exact executable name configured for this chop."""
        return self.script or self.name

    @property
    def parent_name(self) -> str | None:
        """Return the unexpanded parent identity for a target instance."""
        if not self.target_key:
            return None
        return self.base_name or self.name


@dataclass
class LumberjackConfig:
    """Configuration for a single lumberjack."""

    name: str
    interval: int
    chop_timeout: int | None = None
    env: dict[str, ChopEnvValue] = field(default_factory=dict)
    chops: list[ChopConfig] = field(default_factory=list)

    @property
    def chop_names(self) -> list[str]:
        """Return just the chop names as strings."""
        return [c.name for c in self.chops if c.enabled]


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


def _normalize_env(value: object) -> dict[str, ChopEnvValue]:
    """Copy a core-validated env mapping without resolving its secrets."""
    if not isinstance(value, dict):
        return {}
    result: dict[str, ChopEnvValue] = {}
    for raw_name, raw_value in value.items():
        name = str(raw_name)
        if isinstance(raw_value, str):
            result[name] = raw_value
        elif isinstance(raw_value, dict):
            result[name] = {
                str(provider): str(reference)
                for provider, reference in raw_value.items()
            }
    return result


def _deep_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Deep-patch one validated chop config with target overrides."""
    result = deepcopy(base)
    for key, value in patch.items():
        if isinstance(result.get(key), dict) and isinstance(value, dict):
            result[key] = _deep_patch(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _project_workspace_ref(record: ProjectRecordWire) -> str:
    """Return a launchable VCS ref for one project-source target."""
    if record.vcs_kind == "gh" and record.project_name.startswith("gh_"):
        encoded = record.project_name.removeprefix("gh_")
        owner, separator, repo = encoded.partition("__")
        if separator and owner and repo:
            return f"gh:{owner}/{repo}"
    return f"git:{record.project_name}"


def _load_project_target_rows() -> list[dict[str, Any]]:
    """Discover enabled project-source rows through the lifecycle facade."""
    records = list_project_records(
        sase_projects_dir(),
        "enabled",
        include_home=False,
        projects_only=True,
    )
    return [
        {
            "name": effective_project_name(record),
            "project": record.project_name,
            "vcs": record.vcs_kind or "",
            "workspace": _project_workspace_ref(record),
            "workspace_dir": record.workspace_dir or "",
            "enabled": record.state == "enabled",
            "launchable": record.launchable,
        }
        for record in records
        if record.is_project
    ]


def _project_target_rows() -> list[dict[str, Any]]:
    """Return cached project rows on a cadence longer than ACE refresh ticks."""
    global _project_target_cache_deadline, _project_target_cache_rows
    now = time.monotonic()
    with _project_target_cache_lock:
        if (
            _project_target_cache_rows is not None
            and now < _project_target_cache_deadline
        ):
            return deepcopy(_project_target_cache_rows)
        rows = _load_project_target_rows()
        _project_target_cache_rows = deepcopy(rows)
        _project_target_cache_deadline = now + _PROJECT_TARGET_CACHE_SECONDS
        return rows


def _target_source_rows(for_each: object) -> list[dict[str, Any]]:
    if not isinstance(for_each, dict) or for_each.get("source") != "projects":
        return []
    try:
        return _project_target_rows()
    except Exception as exc:
        raise AxeConfigError(
            [
                _AxeConfigDiagnostic(
                    code="target_source_unavailable",
                    path="for_each.source",
                    message=f"could not load enabled projects: {exc}",
                )
            ]
        ) from exc


def _chop_provenance(
    provenance: dict[str, str],
    *,
    path: str,
) -> dict[str, str]:
    """Project dotted config provenance onto one chop's top-level fields."""
    result: dict[str, str] = {}
    prefix = f"{path}."
    for field_path, source in provenance.items():
        if field_path == path:
            result.setdefault("*", source)
        elif field_path.startswith(prefix):
            field_name = field_path[len(prefix) :]
            result[field_name] = source
    return result


def _validate_target_config(
    lumberjack_name: str,
    instance_id: str,
    config: dict[str, Any],
) -> None:
    """Fail closed when target overrides produce an invalid chop config."""
    validation_config = deepcopy(config)
    validation_config.pop("name", None)
    validation_config.pop("for_each", None)
    diagnostics = validate_axe_config(
        {
            "lumberjacks": {
                lumberjack_name: {
                    "interval": 1,
                    "chops": {instance_id: validation_config},
                }
            }
        }
    )
    if diagnostics:
        raise AxeConfigError(
            [_AxeConfigDiagnostic.from_wire(item) for item in diagnostics]
        )


def _render_target_project(value: object, target: dict[str, Any]) -> object:
    """Render ``{target.<field>}`` in per-target trigger project refs."""
    if not isinstance(value, str) or "{target." not in value:
        return value

    class _TargetFields(dict[str, Any]):
        def __getattr__(self, name: str) -> Any:
            try:
                return self[name]
            except KeyError as exc:
                raise AttributeError(name) from exc

    try:
        return value.format_map({"target": _TargetFields(target)})
    except (AttributeError, KeyError, ValueError) as exc:
        raise ValueError(
            f"could not render target project template {value!r}: {exc}"
        ) from exc


def _chop_from_raw(
    *,
    lumberjack_name: str,
    base_name: str,
    instance: dict[str, Any],
    base_config: dict[str, Any],
    lumberjack_env: dict[str, ChopEnvValue],
    provenance: dict[str, str],
) -> ChopConfig:
    overrides = dict(instance.get("overrides") or {})
    prohibited_overrides = sorted({"name", "for_each"}.intersection(overrides))
    if prohibited_overrides:
        joined = ", ".join(prohibited_overrides)
        raise AxeConfigError(
            [
                _AxeConfigDiagnostic(
                    code="invalid_target_override",
                    path=str(instance.get("instance_id") or base_name),
                    message=(
                        "target overrides cannot change stable composition fields: "
                        f"{joined}"
                    ),
                )
            ]
        )
    merged = _deep_patch(base_config, overrides)
    merged.pop("for_each", None)
    target = dict(instance.get("target") or {})
    raw_trigger = merged.get("trigger")
    try:
        if isinstance(raw_trigger, dict):
            raw_trigger = deepcopy(raw_trigger)
            if "project" in raw_trigger:
                raw_trigger["project"] = _render_target_project(
                    raw_trigger["project"], target
                )
            keyed_git = raw_trigger.get("git.commits_since")
            if isinstance(keyed_git, dict) and "project" in keyed_git:
                keyed_git["project"] = _render_target_project(
                    keyed_git["project"], target
                )
            merged["trigger"] = raw_trigger
    except ValueError as exc:
        raise AxeConfigError(
            [
                _AxeConfigDiagnostic(
                    code="invalid_target_template",
                    path=str(instance.get("instance_id") or base_name),
                    message=str(exc),
                )
            ]
        ) from exc
    if overrides or target:
        _validate_target_config(
            lumberjack_name,
            str(instance["instance_id"]),
            merged,
        )

    env = dict(lumberjack_env)
    env.update(_normalize_env(merged.get("env")))
    instance_provenance = dict(provenance)
    for field_name in overrides:
        instance_provenance[field_name] = "for_each target override"
    raw_vars = merged.get("vars")
    return ChopConfig(
        name=str(instance["instance_id"]),
        base_name=base_name,
        description=str(merged.get("description", "")),
        script=str(merged.get("script") or base_name),
        enabled=bool(merged.get("enabled", True)),
        run_every=_parse_duration(merged.get("run_every")),
        timeout=_parse_duration(merged.get("timeout")),
        env=env,
        inhibit_if=_normalize_guards(merged.get("inhibit_if")),
        trigger=_normalize_trigger(merged.get("trigger")),
        once_per=_normalize_once_per(merged.get("once_per")),
        target_key=str(instance.get("target_key") or ""),
        target=target,
        vars=deepcopy(raw_vars) if isinstance(raw_vars, dict) else {},
        provenance=instance_provenance,
    )


def _parse_lumberjacks(
    raw: dict[str, Any],
    *,
    provenance: dict[str, str] | None = None,
) -> dict[str, LumberjackConfig]:
    """Turn a core-validated ``lumberjacks:`` mapping into dataclasses."""
    provenance = provenance or {}
    result: dict[str, LumberjackConfig] = {}
    for name, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue
        raw_chops = cfg.get("chops", [])
        chops: list[ChopConfig] = []
        lumberjack_env = _normalize_env(cfg.get("env"))
        entries: list[tuple[str, dict[str, Any], str]] = []
        if isinstance(raw_chops, list):
            for index, entry in enumerate(raw_chops):
                if isinstance(entry, dict):
                    chop_name = str(entry["name"])
                    entries.append(
                        (
                            chop_name,
                            deepcopy(entry),
                            f"axe.lumberjacks.{name}.chops[{index}]",
                        )
                    )
                elif isinstance(entry, str):
                    entries.append(
                        (
                            entry,
                            {"name": entry},
                            f"axe.lumberjacks.{name}.chops[{index}]",
                        )
                    )
        elif isinstance(raw_chops, dict):
            entries.extend(
                (
                    str(chop_name),
                    deepcopy(entry),
                    f"axe.lumberjacks.{name}.chops.{chop_name}",
                )
                for chop_name, entry in raw_chops.items()
                if isinstance(entry, dict)
            )

        for chop_name, entry, path in entries:
            entry_provenance = _chop_provenance(provenance, path=path)
            if not bool(entry.get("enabled", True)):
                chops.append(
                    _chop_from_raw(
                        lumberjack_name=name,
                        base_name=chop_name,
                        instance={
                            "instance_id": chop_name,
                            "target_key": "",
                            "target": {},
                            "overrides": {},
                        },
                        base_config=entry,
                        lumberjack_env=lumberjack_env,
                        provenance=entry_provenance,
                    )
                )
                continue

            for_each = entry.get("for_each")
            if for_each is None:
                expansion = {
                    "instances": [
                        {
                            "instance_id": chop_name,
                            "target_key": "",
                            "target": {},
                            "overrides": {},
                        }
                    ]
                }
            else:
                try:
                    expansion = expand_chop_targets(
                        {
                            "schema_version": CHOP_ENGINE_SCHEMA_VERSION,
                            "chop_name": chop_name,
                            "for_each": deepcopy(for_each),
                            "source_rows": _target_source_rows(for_each),
                        }
                    )
                except AxeConfigError:
                    raise
                except Exception as exc:
                    layer = next(
                        (
                            source
                            for field_name, source in entry_provenance.items()
                            if field_name == "for_each"
                            or field_name.startswith("for_each.")
                        ),
                        None,
                    )
                    raise AxeConfigError(
                        [
                            _AxeConfigDiagnostic(
                                code="target_expansion_failed",
                                path=f"{path}.for_each",
                                message=str(exc),
                                layer=layer,
                            )
                        ]
                    ) from exc
            for instance in expansion.get("instances", []):
                if not isinstance(instance, dict):
                    continue
                chops.append(
                    _chop_from_raw(
                        lumberjack_name=name,
                        base_name=chop_name,
                        instance=instance,
                        base_config=entry,
                        lumberjack_env=lumberjack_env,
                        provenance=entry_provenance,
                    )
                )
        chop_timeout = _parse_duration(cfg.get("chop_timeout"))
        result[name] = LumberjackConfig(
            name=name,
            interval=int(cfg.get("interval", 1)),
            chop_timeout=chop_timeout,
            env=lumberjack_env,
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


def _map_form_chop_layers(layers: list[ConfigLayer]) -> bool:
    """Return whether any raw layer needs keyed chop composition."""
    for layer in layers:
        axe = layer.data.get("axe") if isinstance(layer.data, dict) else None
        lumberjacks = axe.get("lumberjacks") if isinstance(axe, dict) else None
        if not isinstance(lumberjacks, dict):
            continue
        for config in lumberjacks.values():
            if isinstance(config, dict) and isinstance(config.get("chops"), dict):
                return True
    return False


def _has_map_form_chops(data: dict[str, Any]) -> bool:
    axe = data.get("axe")
    lumberjacks = axe.get("lumberjacks") if isinstance(axe, dict) else None
    if not isinstance(lumberjacks, dict):
        return False
    return any(
        isinstance(config, dict) and isinstance(config.get("chops"), dict)
        for config in lumberjacks.values()
    )


def _normalize_layer_chop_lists(
    layer: ConfigLayer,
) -> tuple[dict[str, Any], set[str], list[_AxeConfigDiagnostic]]:
    """Normalize one layer's legacy chop lists into keyed maps for merging."""
    data = deepcopy(layer.data)
    replacement_paths: set[str] = set()
    diagnostics: list[_AxeConfigDiagnostic] = []
    axe = data.get("axe") if isinstance(data, dict) else None
    lumberjacks = axe.get("lumberjacks") if isinstance(axe, dict) else None
    if not isinstance(lumberjacks, dict):
        return data, replacement_paths, diagnostics

    for lumberjack_name, config in lumberjacks.items():
        if not isinstance(config, dict):
            continue
        raw_chops = config.get("chops")
        if not isinstance(raw_chops, list):
            continue
        keyed: dict[str, dict[str, Any]] = {}
        for index, entry in enumerate(raw_chops):
            if isinstance(entry, str):
                chop_name = entry
                chop_config: dict[str, Any] = {}
            elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
                chop_name = str(entry["name"])
                chop_config = deepcopy(entry)
            else:
                # The shared validator emits the authoritative shape error.
                continue
            if chop_name in keyed:
                # The raw-layer core validation emits the authoritative
                # duplicate diagnostic with the original list index.
                continue
            keyed[chop_name] = chop_config
        config["chops"] = keyed
        if layer.list_strategy == "replace":
            replacement_paths.add(f"axe.lumberjacks.{lumberjack_name}.chops")
    return data, replacement_paths, diagnostics


def _clear_mapping_path(data: dict[str, Any], path: str) -> None:
    components = path.split(".")
    cursor: dict[str, Any] = data
    for component in components[:-1]:
        child = cursor.get(component)
        if not isinstance(child, dict):
            return
        cursor = child
    cursor.pop(components[-1], None)


def _compose_keyed_axe_layers(
    layers: list[ConfigLayer],
) -> tuple[dict[str, Any], dict[str, str], list[_AxeConfigDiagnostic]]:
    """Compose keyed chops across raw layers with per-field provenance."""
    merged: object = {}
    provenance: dict[str, str] = {}
    diagnostics: list[_AxeConfigDiagnostic] = []
    for layer in layers:
        if not isinstance(layer.data, dict) or "axe" not in layer.data:
            continue
        label = _layer_label(layer)
        raw_diagnostics = validate_axe_config(
            {"axe": layer.data["axe"]},
            provenance={"axe": label},
        )
        diagnostics.extend(
            _AxeConfigDiagnostic.from_wire(item) for item in raw_diagnostics
        )
        raw_axe = layer.data["axe"]
        raw_lumberjacks = (
            raw_axe.get("lumberjacks") if isinstance(raw_axe, dict) else None
        )
        if isinstance(raw_lumberjacks, dict) and layer.list_strategy != "replace":
            merged_axe = merged.get("axe") if isinstance(merged, dict) else None
            merged_lumberjacks = (
                merged_axe.get("lumberjacks") if isinstance(merged_axe, dict) else None
            )
            for lumberjack_name, raw_config in raw_lumberjacks.items():
                raw_chops = (
                    raw_config.get("chops") if isinstance(raw_config, dict) else None
                )
                if not isinstance(raw_chops, list):
                    continue
                existing_config = (
                    merged_lumberjacks.get(lumberjack_name)
                    if isinstance(merged_lumberjacks, dict)
                    else None
                )
                existing_chops = (
                    existing_config.get("chops")
                    if isinstance(existing_config, dict)
                    else None
                )
                existing_names = (
                    set(existing_chops) if isinstance(existing_chops, dict) else set()
                )
                for index, raw_chop in enumerate(raw_chops):
                    identity = (
                        raw_chop
                        if isinstance(raw_chop, str)
                        else raw_chop.get("name")
                        if isinstance(raw_chop, dict)
                        else None
                    )
                    if isinstance(identity, str) and identity in existing_names:
                        diagnostics.append(
                            _AxeConfigDiagnostic(
                                code="duplicate_chop_identity",
                                message=f"duplicate chop identity `{identity}`",
                                path=(
                                    f"axe.lumberjacks.{lumberjack_name}.chops[{index}]"
                                ),
                                layer=label,
                            )
                        )
        normalized, replacement_paths, layer_diagnostics = _normalize_layer_chop_lists(
            layer
        )
        diagnostics.extend(layer_diagnostics)
        if isinstance(merged, dict):
            for path in replacement_paths:
                _clear_mapping_path(merged, path)
                _clear_provenance_subtree(provenance, path)
        merged = _merge_with_provenance(
            merged,
            {"axe": normalized["axe"]},
            path="",
            label=label,
            list_strategy=layer.list_strategy,
            provenance=provenance,
        )
    unique_diagnostics = list(
        {
            (item.code, item.path, item.layer, item.message): item
            for item in diagnostics
        }.values()
    )
    unique_diagnostics.sort(
        key=lambda item: (item.path or "", item.code, item.layer or "")
    )
    return (
        merged if isinstance(merged, dict) else {},
        provenance,
        unique_diagnostics,
    )


def _axe_config_provenance(
    layers: list[ConfigLayer] | None = None,
) -> dict[str, str]:
    """Build dotted-path provenance for the effective ``axe:`` section."""
    merged: object = {}
    provenance: dict[str, str] = {}
    for layer in layers or load_config_layers():
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


def _effective_axe_config_data(
    data: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Apply keyed chop composition when any source layer uses map form."""
    global _keyed_config_cache_token, _keyed_config_cache_value
    if not _has_map_form_chops(data):
        return data, {}

    token = (
        *current_config_token(),
        json.dumps(data.get("axe"), sort_keys=True, separators=(",", ":")),
    )
    with _keyed_config_cache_lock:
        if _keyed_config_cache_token == token and _keyed_config_cache_value is not None:
            return _keyed_config_cache_value

    layers = load_config_layers()
    if not _map_form_chop_layers(layers):
        return data, _axe_config_provenance(layers)
    composed, provenance, diagnostics = _compose_keyed_axe_layers(layers)
    if diagnostics:
        raise AxeConfigError(diagnostics)
    with _keyed_config_cache_lock:
        _keyed_config_cache_token = token
        _keyed_config_cache_value = (composed, provenance)
    return composed, provenance


def _validate_effective_axe_config(
    data: dict[str, Any],
    *,
    provenance: dict[str, str] | None = None,
) -> None:
    request: dict[str, Any]
    if "axe" in data:
        request = {"axe": data["axe"]}
    else:
        request = {}
    diagnostics = validate_axe_config(request, provenance=provenance)
    if not diagnostics:
        return
    if provenance is None:
        # Provenance discovery performs file/plugin IO, so only pay for it on
        # the error path when callers did not already compose keyed layers.
        diagnostics = validate_axe_config(
            request,
            provenance=_axe_config_provenance(),
        )
    raise AxeConfigError([_AxeConfigDiagnostic.from_wire(item) for item in diagnostics])


def load_axe_config() -> AxeConfig:
    """Load and fail-closed validate the effective axe configuration."""
    data, provenance = _effective_axe_config_data(load_merged_config())
    _validate_effective_axe_config(data, provenance=provenance or None)

    axe_data = data.get("axe")
    if not isinstance(axe_data, dict):
        return AxeConfig()

    raw_lumberjacks = axe_data.get("lumberjacks")
    lumberjacks = (
        _parse_lumberjacks(raw_lumberjacks, provenance=provenance)
        if isinstance(raw_lumberjacks, dict)
        else {}
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
