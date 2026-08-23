"""Declarative task-type discovery, catalog assembly, and diagnostics."""

from ._builtin import BuiltinTaskTypes
from ._hookspec import TaskTypeHookSpec, hookimpl, hookspec
from .body import TASK_TYPE_BODY_SEPARATOR, render_task_type_display_block
from .fields import (
    UNTYPED_TASK_TYPE,
    TaskTypeCreateError,
    format_agent_creatable_type_listing,
    issue_matches_task_types,
    issue_task_type_slug,
    parse_field_args,
    required_task_type_field_names,
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
from .snapshot import (
    build_committed_task_type_snapshot_entries,
    build_task_type_snapshot_entries,
    committed_task_type_records,
    describe_task_type_snapshot_drift,
    render_task_type_snapshot_json,
    task_type_snapshot_entry,
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
    "build_committed_task_type_snapshot_entries",
    "build_task_type_snapshot_entries",
    "committed_task_type_records",
    "describe_task_type_snapshot_drift",
    "format_agent_creatable_type_listing",
    "get_task_type_registry",
    "hookimpl",
    "hookspec",
    "issue_matches_task_types",
    "issue_task_type_slug",
    "parse_field_args",
    "render_task_type_display_block",
    "render_task_type_snapshot_json",
    "required_task_type_field_names",
    "reset_task_type_registry_cache",
    "resolve_created_task_type",
    "task_type_snapshot_entry",
    "validate_task_type_spec",
]
