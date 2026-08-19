"""The ``bead.task_types`` project-config task-type source.

An entry with ``use: <plugin>@<slug>`` deep-merges its sibling keys onto the
referenced catalog member and replaces that slug. The prefix names the type's
original provider (``builtin`` for a builtin) and stays correct across layers,
even after an earlier layer already overrode the slug. An entry without
``use:`` defines a new slug and may not shadow a builtin or reserved slug (D4).
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
from types import MappingProxyType
from typing import Any

from sase.config.core import load_config_layers
from sase.plugins.qualified_id import (
    PluginQualifiedIdError,
    parse_plugin_qualified_id,
    plugin_qualified_id_matches,
)

from ._models import TaskTypeDiagnostic, TaskTypeProvenance, TaskTypeRecord
from ._validation import validate_task_type_spec

logger = logging.getLogger(__name__)

_PROJECT_PROVENANCE_VERSION = "<unknown>"


def apply_project_task_type_config(
    records: tuple[TaskTypeRecord, ...],
    diagnostics: list[TaskTypeDiagnostic],
    *,
    include_local_layer: bool = True,
) -> tuple[TaskTypeRecord, ...]:
    """Apply ``bead.task_types`` overrides and additions to *records*."""

    by_slug: dict[str, TaskTypeRecord] = {
        record.task_type: record for record in records
    }
    order: list[str] = [record.task_type for record in records]
    origin_by_slug: dict[str, TaskTypeProvenance] = {
        record.task_type: record.provenance for record in records
    }

    for item, source_layer in _effective_raw_task_type_entries(
        include_local_layer=include_local_layer
    ):
        if not isinstance(item, Mapping):
            diagnostics.append(
                TaskTypeDiagnostic(
                    code="invalid_task_type",
                    message="bead.task_types entries must be mappings",
                    severity="error",
                    source=f"project:{source_layer}",
                )
            )
            continue
        raw_use = item.get("use")
        if raw_use is not None:
            _apply_use_override(
                item,
                raw_use,
                source_layer,
                by_slug=by_slug,
                origin_by_slug=origin_by_slug,
                diagnostics=diagnostics,
            )
            continue
        _apply_new_project_type(
            item,
            source_layer,
            by_slug=by_slug,
            origin_by_slug=origin_by_slug,
            order=order,
            diagnostics=diagnostics,
        )

    return tuple(by_slug[slug] for slug in order if slug in by_slug)


def _apply_use_override(
    item: Mapping[str, Any],
    raw_use: object,
    source_layer: str,
    *,
    by_slug: dict[str, TaskTypeRecord],
    origin_by_slug: dict[str, TaskTypeProvenance],
    diagnostics: list[TaskTypeDiagnostic],
) -> None:
    if not isinstance(raw_use, str) or not raw_use.strip():
        diagnostics.append(
            TaskTypeDiagnostic(
                code="invalid_task_type",
                message="bead.task_types[].use must be a nonempty string",
                severity="error",
                source=f"project:{source_layer}",
            )
        )
        return
    raw_use_value = raw_use.strip()
    try:
        plugin, slug = parse_plugin_qualified_id(raw_use_value)
    except PluginQualifiedIdError as exc:
        diagnostics.append(
            TaskTypeDiagnostic(
                code="missing_use_prefix",
                message=f"bead.task_types[].use: {exc}",
                severity="error",
                source=f"project:{source_layer}",
            )
        )
        return
    base = by_slug.get(slug)
    if base is None:
        diagnostics.append(
            TaskTypeDiagnostic(
                code="unknown_task_type_use",
                message=(
                    "bead.task_types[].use references unknown task type "
                    f"'{slug}'; install the plugin providing it or remove 'use'"
                ),
                severity="error",
                task_type=slug,
                source=f"project:{source_layer}",
            )
        )
        return
    origin = origin_by_slug.get(slug, base.provenance)
    if not plugin_qualified_id_matches(
        plugin, builtin=origin.builtin, package=origin.package
    ):
        actual = _use_prefix_for(origin)
        diagnostics.append(
            TaskTypeDiagnostic(
                code="mismatched_use_prefix",
                message=(
                    f"task type '{slug}' is provided by {actual!r}, not "
                    f"{plugin!r}; use {f'{actual}@{slug}'!r}"
                ),
                severity="error",
                task_type=slug,
                source=f"project:{source_layer}",
            )
        )
        return
    overrides = {str(key): value for key, value in item.items() if str(key) != "use"}
    merged = _deep_merge(base.spec, overrides)
    try:
        digest = validate_task_type_spec(merged)
    except Exception as exc:
        diagnostics.append(
            TaskTypeDiagnostic(
                code="invalid_task_type",
                message=(
                    f"Skipping bead.task_types override of '{slug}' from "
                    f"{source_layer}: {type(exc).__name__}: {exc}"
                ),
                severity="error",
                task_type=slug,
                source=f"project:{source_layer}",
            )
        )
        return
    by_slug[slug] = TaskTypeRecord(
        task_type=slug,
        spec=MappingProxyType(merged),
        digest=digest,
        provenance=TaskTypeProvenance(
            source="project",
            name=source_layer,
            package="project",
            version=_PROJECT_PROVENANCE_VERSION,
        ),
    )


def _apply_new_project_type(
    item: Mapping[str, Any],
    source_layer: str,
    *,
    by_slug: dict[str, TaskTypeRecord],
    origin_by_slug: dict[str, TaskTypeProvenance],
    order: list[str],
    diagnostics: list[TaskTypeDiagnostic],
) -> None:
    raw_slug = item.get("task_type")
    if not isinstance(raw_slug, str) or not raw_slug.strip():
        diagnostics.append(
            TaskTypeDiagnostic(
                code="invalid_task_type",
                message="bead.task_types entries need 'use' or a 'task_type' slug",
                severity="error",
                source=f"project:{source_layer}",
            )
        )
        return
    slug = raw_slug.strip()
    existing = by_slug.get(slug)
    if existing is not None:
        if existing.provenance.source == "builtin":
            code = "builtin_task_type_shadowed"
        else:
            code = "duplicate_task_type"
        diagnostics.append(
            TaskTypeDiagnostic(
                code=code,
                message=(
                    f"bead.task_types entry '{slug}' from {source_layer} duplicates "
                    f"{existing.provenance.label}; use "
                    f"'use: {_use_prefix_for(existing.provenance)}@{slug}' to "
                    "override it or pick a different slug"
                ),
                severity="error",
                task_type=slug,
                source=f"project:{source_layer}",
            )
        )
        return
    spec = _plain_mapping(item)
    try:
        digest = validate_task_type_spec(spec)
    except Exception as exc:
        diagnostics.append(
            TaskTypeDiagnostic(
                code="invalid_task_type",
                message=(
                    f"Skipping bead.task_types entry '{slug}' from {source_layer}: "
                    f"{type(exc).__name__}: {exc}"
                ),
                severity="error",
                task_type=slug,
                source=f"project:{source_layer}",
            )
        )
        return
    provenance = TaskTypeProvenance(
        source="project",
        name=source_layer,
        package="sase",
        version=_PROJECT_PROVENANCE_VERSION,
    )
    by_slug[slug] = TaskTypeRecord(
        task_type=slug,
        spec=MappingProxyType(spec),
        digest=digest,
        provenance=provenance,
    )
    order.append(slug)
    origin_by_slug.setdefault(slug, provenance)


def _use_prefix_for(provenance: TaskTypeProvenance) -> str:
    return "builtin" if provenance.builtin else provenance.package


def _effective_raw_task_type_entries(
    *, include_local_layer: bool = True
) -> list[tuple[object, str]]:
    """Replay config-list merge semantics for ``bead.task_types`` with provenance."""
    effective: list[tuple[object, str]] = []
    for layer in load_config_layers():
        if not include_local_layer and layer.name == "local":
            continue
        if not layer.exists:
            continue
        bead_config = layer.data.get("bead")
        if not isinstance(bead_config, Mapping) or "task_types" not in bead_config:
            continue
        raw_items = bead_config["task_types"]
        if layer.list_strategy == "replace":
            effective = []
        if not isinstance(raw_items, list):
            logger.warning(
                "Skipping invalid bead.task_types value from config layer "
                "'%s': expected a list",
                layer.name,
            )
            continue
        effective.extend((item, layer.name) for item in raw_items)
    return effective


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = _plain_mapping(base)
    for key, value in override.items():
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = _deep_merge(current, value)
        else:
            result[key] = _plain_value(value)
    return result


def _plain_mapping(value: Mapping[Any, Any]) -> dict[str, Any]:
    return {str(key): _plain_value(item) for key, item in value.items()}


def _plain_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _plain_mapping(value)
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    return value


__all__ = [
    "apply_project_task_type_config",
]
