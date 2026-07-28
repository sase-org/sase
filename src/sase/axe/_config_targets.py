"""Target discovery, expansion, and runtime parsing for axe configuration."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import threading
import time
from typing import Any

from sase.core.axe_chop_facade import (
    CHOP_ENGINE_SCHEMA_VERSION,
    expand_chop_targets,
    parse_chop_duration,
    split_axe_description,
    validate_axe_config,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import ProjectRecordWire, effective_project_name

from ._config_types import (
    AxeConfigError,
    AxeConfigDiagnostic,
    ChopConfig,
    LumberjackConfig,
)
from .chop_env import ChopEnvValue

_PROJECT_TARGET_CACHE_SECONDS = 30.0
_project_target_cache_lock = threading.RLock()
_project_target_cache_deadline = 0.0
_project_target_cache_rows: list[dict[str, Any]] | None = None

ProjectTargetRowsLoader = Callable[[], list[dict[str, Any]]]


def parse_duration(value: object) -> int | None:
    """Parse a validated positive compound duration into seconds."""
    if not isinstance(value, str):
        return None
    try:
        return parse_chop_duration(value)
    except (RuntimeError, ValueError):
        return None


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


def project_target_rows() -> list[dict[str, Any]]:
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


def _target_source_rows(
    for_each: object,
    *,
    project_target_rows: ProjectTargetRowsLoader,
) -> list[dict[str, Any]]:
    if not isinstance(for_each, dict) or for_each.get("source") != "projects":
        return []
    try:
        return project_target_rows()
    except Exception as exc:
        raise AxeConfigError(
            [
                AxeConfigDiagnostic(
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
            [AxeConfigDiagnostic.from_wire(item) for item in diagnostics]
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
                AxeConfigDiagnostic(
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
                AxeConfigDiagnostic(
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
    description = str(merged.get("description", ""))
    description_summary, description_body = split_axe_description(description)
    return ChopConfig(
        name=str(instance["instance_id"]),
        base_name=base_name,
        description=description,
        description_summary=description_summary,
        description_body=description_body,
        script=str(merged.get("script") or base_name),
        enabled=bool(merged.get("enabled", True)),
        run_every=parse_duration(merged.get("run_every")),
        timeout=parse_duration(merged.get("timeout")),
        env=env,
        inhibit_if=_normalize_guards(merged.get("inhibit_if")),
        trigger=_normalize_trigger(merged.get("trigger")),
        once_per=_normalize_once_per(merged.get("once_per")),
        target_key=str(instance.get("target_key") or ""),
        target=target,
        vars=deepcopy(raw_vars) if isinstance(raw_vars, dict) else {},
        provenance=instance_provenance,
    )


def parse_lumberjacks(
    raw: dict[str, Any],
    *,
    provenance: dict[str, str] | None = None,
    exact_chop_provenance: dict[tuple[str, str], dict[str, str]] | None = None,
    project_target_rows: ProjectTargetRowsLoader = project_target_rows,
) -> dict[str, LumberjackConfig]:
    """Turn a core-validated ``lumberjacks:`` mapping into dataclasses."""
    provenance = provenance or {}
    exact_chop_provenance = exact_chop_provenance or {}
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
            entry_provenance = exact_chop_provenance.get(
                (name, chop_name),
                _chop_provenance(provenance, path=path),
            )
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
                            "source_rows": _target_source_rows(
                                for_each,
                                project_target_rows=project_target_rows,
                            ),
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
                            AxeConfigDiagnostic(
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
        chop_timeout = parse_duration(cfg.get("chop_timeout"))
        raw_wait_runners = cfg.get("wait_runners")
        wait_runners = int(raw_wait_runners) if raw_wait_runners is not None else None
        description = str(cfg["description"])
        description_summary, description_body = split_axe_description(description)
        result[name] = LumberjackConfig(
            name=name,
            description=description,
            description_summary=description_summary,
            description_body=description_body,
            interval=int(cfg.get("interval", 1)),
            chop_timeout=chop_timeout,
            wait_runners=wait_runners,
            env=lumberjack_env,
            chops=chops,
        )
    return result
