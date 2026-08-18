"""Declarative task-type discovery, catalog assembly, and diagnostics."""

from ._builtin import BuiltinTaskTypes
from ._hookspec import TaskTypeHookSpec, hookimpl, hookspec
from .body import TASK_TYPE_BODY_SEPARATOR, render_task_type_display_block
from .fields import (
    UNTYPED_TASK_TYPE,
    TaskTypeCreateError,
    issue_matches_task_types,
    issue_task_type_slug,
    parse_field_args,
    resolve_created_task_type,
)
from .registry import (
    TASK_TYPE_ENTRY_POINT_GROUP,
    TaskTypeDiagnostic,
    TaskTypeProvenance,
    TaskTypeRecord,
    TaskTypeRegistry,
    assemble_task_type_registry,
    get_task_type_registry,
    reset_task_type_registry_cache,
    validate_task_type_spec,
)

__all__ = [
    "TASK_TYPE_BODY_SEPARATOR",
    "TASK_TYPE_ENTRY_POINT_GROUP",
    "BuiltinTaskTypes",
    "TaskTypeCreateError",
    "TaskTypeDiagnostic",
    "TaskTypeHookSpec",
    "TaskTypeProvenance",
    "TaskTypeRecord",
    "TaskTypeRegistry",
    "UNTYPED_TASK_TYPE",
    "assemble_task_type_registry",
    "get_task_type_registry",
    "hookimpl",
    "hookspec",
    "issue_matches_task_types",
    "issue_task_type_slug",
    "parse_field_args",
    "render_task_type_display_block",
    "reset_task_type_registry_cache",
    "resolve_created_task_type",
    "validate_task_type_spec",
]
