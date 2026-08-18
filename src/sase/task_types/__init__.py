"""Declarative task-type discovery, catalog assembly, and diagnostics."""

from ._builtin import BuiltinTaskTypes
from ._hookspec import TaskTypeHookSpec, hookimpl, hookspec
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
    "TASK_TYPE_ENTRY_POINT_GROUP",
    "BuiltinTaskTypes",
    "TaskTypeDiagnostic",
    "TaskTypeHookSpec",
    "TaskTypeProvenance",
    "TaskTypeRecord",
    "TaskTypeRegistry",
    "assemble_task_type_registry",
    "get_task_type_registry",
    "hookimpl",
    "hookspec",
    "reset_task_type_registry_cache",
    "validate_task_type_spec",
]
