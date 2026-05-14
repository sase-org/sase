"""Workspace operation handlers for the provider host runtime."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from sase.host.runtime_shared import (
    OperationContext,
    ProviderHostRuntimeError,
    payload_str,
)


def workspace_metadata(context: OperationContext) -> Mapping[str, Any]:
    import sase.workspace_provider as workspace_registry

    payload = dict(context.request.payload)
    query = str(payload.get("query", ""))
    context.logs.append(
        "info",
        f"workspace metadata query dispatched: {query}",
        target="sase.host.workspace",
    )
    value: Any
    if query == "workflow_metadata":
        value = [
            asdict(item) if is_dataclass(item) else dict(item)
            for item in workspace_registry.get_all_workflow_metadata()
        ]
    elif query == "workflow_names":
        value = sorted(workspace_registry.get_workflow_names())
    elif query == "detect_workflow_type":
        value = workspace_registry.detect_workflow_type_direct(
            payload_str(payload, "project_file")
        )
    elif query == "get_change_label":
        value = workspace_registry.get_change_label_direct(
            payload_str(payload, "project_file")
        )
    elif query == "get_display_name":
        value = workspace_registry.get_display_name(
            payload_str(payload, "workflow_type")
        )
    elif query == "get_display_name_by_vcs":
        value = workspace_registry.get_display_name_by_vcs(
            payload_str(payload, "vcs_name")
        )
    elif query == "get_display_name_by_vcs_family":
        value = workspace_registry.get_display_name_by_vcs_family(
            payload_str(payload, "vcs_family")
        )
    elif query == "get_pre_allocated_env_prefix":
        value = workspace_registry.get_pre_allocated_env_prefix(
            payload_str(payload, "workflow_type")
        )
    elif query == "get_workspace_directory":
        value = workspace_registry.get_workspace_directory_direct(
            payload_str(payload, "workflow_type"),
            int(payload.get("workspace_num", 1)),
            payload_str(payload, "project_name"),
            payload_str(payload, "primary_workspace_dir"),
        )
    elif query == "get_workspace_name":
        value = workspace_registry.get_workspace_name_direct(
            payload_str(payload, "cwd")
        )
    else:
        raise ProviderHostRuntimeError(
            "operation_unsupported",
            f"unsupported workspace metadata query: {query}",
            target="payload.query",
        )
    return {"query": query, "value": value}


def workspace_resolve_ref(context: OperationContext) -> Mapping[str, Any]:
    from sase.workspace_provider import resolve_ref_direct

    payload = dict(context.request.payload)
    resolved = resolve_ref_direct(
        payload_str(payload, "ref"),
        payload_str(payload, "workflow_type"),
    )
    return {"value": asdict(resolved)}
