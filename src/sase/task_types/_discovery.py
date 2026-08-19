"""Entry-point discovery for task-type plugins."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import importlib.metadata
import os
from typing import Any

import pluggy

from ._builtin import BuiltinTaskTypes
from ._hookspec import TaskTypeHookSpec
from ._models import TaskTypeDiagnostic, TaskTypeProvenance

TASK_TYPE_ENTRY_POINT_GROUP = "sase_task_types"

TaskTypeCandidate = tuple[Mapping[str, Any], TaskTypeProvenance]


@dataclass(frozen=True)
class _TaskTypeDiscovery:
    """Unvalidated task-type specs and diagnostics collected from plugins."""

    candidates: tuple[TaskTypeCandidate, ...]
    diagnostics: tuple[TaskTypeDiagnostic, ...]
    disabled_env: tuple[str, ...]


def discover_task_type_specs(*, entry_points_fn: Any) -> _TaskTypeDiscovery:
    """Collect builtin and installed task-type specs."""

    diagnostics: list[TaskTypeDiagnostic] = []
    disabled_env: set[str] = set()
    candidates: list[TaskTypeCandidate] = []

    builtin = builtin_task_type_provenance()
    _collect_plugin_specs(
        BuiltinTaskTypes(),
        builtin,
        candidates=candidates,
        diagnostics=diagnostics,
    )

    disabled_by = _disabled_env_for_group(TASK_TYPE_ENTRY_POINT_GROUP)
    disabled_env.update(disabled_by)
    if not disabled_by:
        for ep in _entry_points_for_group(
            TASK_TYPE_ENTRY_POINT_GROUP, entry_points_fn=entry_points_fn
        ):
            provenance = TaskTypeProvenance(
                source="plugin",
                name=_safe_str(getattr(ep, "name", None), "<unknown>"),
                package=_entry_point_package(ep),
                version=_entry_point_version(ep),
            )
            try:
                loaded = ep.load()
                plugin = loaded() if isinstance(loaded, type) else loaded
            except Exception as exc:
                diagnostics.append(
                    TaskTypeDiagnostic(
                        code="entry_point_load_failed",
                        message=(
                            "Failed to load task type entry point "
                            f"{provenance.label}: {type(exc).__name__}: {exc}"
                        ),
                        severity="error",
                        source=provenance.label,
                        package=provenance.package,
                        version=provenance.version,
                    )
                )
                continue
            _collect_plugin_specs(
                plugin,
                provenance,
                candidates=candidates,
                diagnostics=diagnostics,
            )

    return _TaskTypeDiscovery(
        candidates=tuple(candidates),
        diagnostics=tuple(diagnostics),
        disabled_env=tuple(sorted(disabled_env)),
    )


def builtin_task_type_provenance() -> TaskTypeProvenance:
    """Return the provenance stamp shared by every builtin task-type spec."""

    return TaskTypeProvenance(
        source="builtin",
        name="sase",
        package="sase",
        version=_distribution_version("sase"),
        builtin=True,
    )


def _collect_plugin_specs(
    plugin: object,
    provenance: TaskTypeProvenance,
    *,
    candidates: list[TaskTypeCandidate],
    diagnostics: list[TaskTypeDiagnostic],
) -> None:
    pm = pluggy.PluginManager("sase_task_type")
    pm.add_hookspecs(TaskTypeHookSpec)
    try:
        pm.register(plugin, name=provenance.label)
    except Exception as exc:
        diagnostics.append(
            TaskTypeDiagnostic(
                code="plugin_registration_failed",
                message=(
                    f"Failed to register task type plugin {provenance.label}: "
                    f"{type(exc).__name__}: {exc}"
                ),
                severity="error",
                source=provenance.label,
                package=provenance.package,
                version=provenance.version,
            )
        )
        return

    try:
        results = pm.hook.task_type_specs()
    except Exception as exc:
        diagnostics.append(
            TaskTypeDiagnostic(
                code="task_type_hook_failed",
                message=(
                    f"Task type plugin {provenance.label} failed while "
                    f"returning specs: {type(exc).__name__}: {exc}"
                ),
                severity="error",
                source=provenance.label,
                package=provenance.package,
                version=provenance.version,
            )
        )
        return

    for result in results:
        for spec in _iter_mapping_specs(result):
            candidates.append((spec, provenance))


def _iter_mapping_specs(result: object) -> Iterable[Mapping[str, Any]]:
    if result is None:
        return ()
    if isinstance(result, Mapping):
        return (result,)
    if isinstance(result, Iterable) and not isinstance(result, (str, bytes)):
        return tuple(item for item in result if isinstance(item, Mapping))
    return ()


def _entry_points_for_group(
    group: str,
    *,
    entry_points_fn: Any,
) -> list[importlib.metadata.EntryPoint]:
    eps = entry_points_fn(group=group)
    return sorted(eps, key=lambda ep: getattr(ep, "name", ""))


def _disabled_env_for_group(group: str) -> tuple[str, ...]:
    disabled: list[str] = []
    if os.environ.get("SASE_DISABLE_PLUGINS"):
        disabled.append("SASE_DISABLE_PLUGINS")
    suffix = group.removeprefix("sase_").upper()
    env_key = f"SASE_DISABLE_PLUGIN_{suffix}"
    if os.environ.get(env_key):
        disabled.append(env_key)
    return tuple(disabled)


def _entry_point_package(ep: importlib.metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    metadata = getattr(dist, "metadata", None)
    name = _metadata_value(metadata, "Name")
    if name:
        return name
    direct_name = getattr(dist, "name", None)
    if isinstance(direct_name, str) and direct_name:
        return direct_name
    return "<unknown>"


def _entry_point_version(ep: importlib.metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    version = getattr(dist, "version", None)
    if isinstance(version, str) and version:
        return version
    metadata = getattr(dist, "metadata", None)
    return _metadata_value(metadata, "Version") or "<unknown>"


def _distribution_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "<unknown>"


def _metadata_value(metadata: object, key: str) -> str | None:
    getter = getattr(metadata, "get", None)
    if not callable(getter):
        return None
    value = getter(key)
    return value if isinstance(value, str) and value else None


def _safe_str(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


__all__ = [
    "TASK_TYPE_ENTRY_POINT_GROUP",
    "builtin_task_type_provenance",
    "discover_task_type_specs",
]
