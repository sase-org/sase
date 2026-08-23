"""Task-type registry assembly and public API."""

from __future__ import annotations

import importlib.metadata
import os
from typing import Any

from sase.config.core import current_config_token

from ._discovery import (
    TASK_TYPE_ENTRY_POINT_GROUP,
    discover_task_type_specs,
)
from ._models import (
    TaskTypeDiagnostic,
    TaskTypeProvenance,
    TaskTypeRecord,
    TaskTypeRegistry,
)
from ._project_config import apply_project_task_type_config
from ._validation import (
    resolve_task_type_presentation,
    validate_task_type_candidates,
    validate_task_type_spec,
)

_registry_cache_token: tuple[Any, ...] | None = None
_registry_cache_value: TaskTypeRegistry | None = None


def get_task_type_registry() -> TaskTypeRegistry:
    """Return the memoized task-type registry for the current config."""

    global _registry_cache_token, _registry_cache_value
    token = _task_type_registry_token()
    if _registry_cache_value is not None and _registry_cache_token == token:
        return _registry_cache_value
    registry = assemble_task_type_registry()
    _registry_cache_token = token
    _registry_cache_value = registry
    return registry


def reset_task_type_registry_cache() -> None:
    """Clear the process-local task-type registry cache."""

    global _registry_cache_token, _registry_cache_value
    _registry_cache_token = None
    _registry_cache_value = None


def assemble_task_type_registry(
    *,
    entry_points_fn: Any = importlib.metadata.entry_points,
) -> TaskTypeRegistry:
    """Discover, validate, and present the effective task-type catalog."""

    discovery = discover_task_type_specs(entry_points_fn=entry_points_fn)
    diagnostics = list(discovery.diagnostics)
    records = validate_task_type_candidates(discovery.candidates, diagnostics)
    records = apply_project_task_type_config(records, diagnostics)
    records = resolve_task_type_presentation(records, diagnostics)
    return TaskTypeRegistry(
        records=records,
        diagnostics=tuple(diagnostics),
        disabled_env=discovery.disabled_env,
    )


def _task_type_registry_token() -> tuple[Any, ...]:
    return (
        current_config_token(),
        os.environ.get("SASE_DISABLE_PLUGINS"),
        os.environ.get("SASE_DISABLE_PLUGIN_TASK_TYPES"),
    )


__all__ = [
    "TASK_TYPE_ENTRY_POINT_GROUP",
    "TaskTypeDiagnostic",
    "TaskTypeProvenance",
    "TaskTypeRecord",
    "TaskTypeRegistry",
    "assemble_task_type_registry",
    "get_task_type_registry",
    "reset_task_type_registry_cache",
    "validate_task_type_spec",
]
