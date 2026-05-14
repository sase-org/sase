"""VCS operation handlers for the provider host runtime."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.host.runtime_shared import (
    OperationContext,
    OperationResult,
    ProviderHostRuntimeError,
    payload_str,
)
from sase.host.wire import HostRequestEnvelopeWire, HostSideEffectIntentWire


def vcs_query(context: OperationContext) -> OperationResult:
    from sase.vcs_provider import (
        detect_vcs_direct,
        detect_vcs_family_direct,
        get_vcs_provider,
    )

    payload = dict(context.request.payload)
    query = str(payload.get("query", ""))
    cwd = payload_str(payload, "cwd")
    context.logs.append(
        "info", f"vcs query dispatched: {query}", target="sase.host.vcs"
    )
    if query == "detect_vcs":
        value = detect_vcs_direct(cwd)
    elif query == "detect_vcs_family":
        value = detect_vcs_family_direct(cwd)
    else:
        provider = get_vcs_provider(cwd)
        value = _call_vcs_query(provider, query, payload, cwd)
    return OperationResult(
        result={"query": query, "value": value},
        spawned_processes=1,
        network_requests=_network_request_count(context.request),
    )


def vcs_mutation_shadow(context: OperationContext) -> OperationResult:
    payload = dict(context.request.payload)
    provider = str(payload.get("provider") or "unknown")
    operation = str(payload.get("operation") or "")
    cwd = payload_str(payload, "cwd", field_name="workspace_dir")
    if not operation:
        raise ProviderHostRuntimeError(
            "host_protocol_error",
            "vcs mutation payload must include operation",
            target="payload.operation",
        )
    context.logs.append(
        "warn",
        f"vcs mutation shadow-routed only: {provider}.{operation}",
        target="sase.host.vcs",
    )
    return OperationResult(
        result={"shadow": True, "provider": provider, "operation": operation},
        side_effects=(
            HostSideEffectIntentWire(
                type="vcs_mutation",
                data={
                    "provider": provider,
                    "operation": operation,
                    "workspace_dir": cwd,
                },
            ),
        ),
    )


def _call_vcs_query(
    provider: object,
    query: str,
    payload: Mapping[str, Any],
    cwd: str,
) -> Any:
    if query in {"get_branch_name", "get_workspace_name", "has_local_changes"}:
        return _call_provider_method(provider, query, cwd)
    if query == "resolve_revision":
        return provider.resolve_revision(  # type: ignore[attr-defined]
            payload_str(payload, "changespec_name"),
            payload_str(payload, "project_basename"),
            cwd,
        )
    if query == "resolve_current_changespec_head_ref":
        return provider.resolve_current_changespec_head_ref(  # type: ignore[attr-defined]
            payload_str(payload, "changespec_name"),
            payload_str(payload, "project_basename"),
            cwd,
        )
    if query in {
        "diff",
        "diff_with_untracked",
        "committed_diff",
        "get_default_parent_revision",
        "get_cl_number",
        "get_bug_number",
        "get_change_url",
        "get_conflicted_files",
        "is_sync_in_progress",
    }:
        return _call_provider_method(provider, query, cwd)
    if query in {"diff_revision", "show_revision", "get_description"}:
        return _call_provider_method(
            provider, query, payload_str(payload, "revision"), cwd
        )
    if query == "diff_name_status":
        return provider.diff_name_status(  # type: ignore[attr-defined]
            payload_str(payload, "parent_ref"),
            payload_str(payload, "head_ref"),
            cwd,
        )
    if query == "diff_line_stats":
        return provider.diff_line_stats(  # type: ignore[attr-defined]
            payload_str(payload, "parent_ref"),
            payload_str(payload, "head_ref"),
            cwd,
        )
    if query == "file_at_revision":
        return provider.file_at_revision(  # type: ignore[attr-defined]
            payload_str(payload, "revision"),
            payload_str(payload, "file_path"),
            cwd,
        )
    if query == "get_change_body":
        return provider.get_change_body(  # type: ignore[attr-defined]
            payload_str(payload, "change_ref"),
            cwd,
        )
    raise ProviderHostRuntimeError(
        "operation_unsupported",
        f"unsupported vcs query: {query}",
        target="payload.query",
    )


def _call_provider_method(provider: object, method_name: str, *args: object) -> Any:
    method = getattr(provider, method_name, None)
    if method is None:
        raise ProviderHostRuntimeError(
            "operation_unsupported",
            f"VCS provider has no query method: {method_name}",
            target="payload.query",
        )
    return method(*args)


def _network_request_count(request: HostRequestEnvelopeWire) -> int:
    payload = dict(request.payload)
    network = payload.get("network")
    if isinstance(network, Mapping) and network.get("required") is True:
        return 1
    return int(
        payload.get("network_required") is True
        or payload.get("requires_network") is True
    )
