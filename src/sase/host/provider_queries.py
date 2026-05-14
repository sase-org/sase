"""Client helpers for routed VCS/workspace provider-host queries."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from sase.daemon.client import LocalDaemonClient
from sase.daemon.errors import LocalDaemonError
from sase.daemon.paths import daemon_disabled
from sase.host.manifest import discover_host_manifests
from sase.host.wire import (
    HOST_CAP_IPC_V1,
    HOST_CAP_MANIFEST_V1,
    HOST_CAP_VCS_QUERY,
    HOST_CAP_WORKSPACE_METADATA,
    HOST_CAP_WORKSPACE_RESOLVE_REF,
    PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
    HostActorWire,
    HostDeadlineWire,
    HostEnvironmentPolicyWire,
    HostManifestWire,
    HostOperationSelectorWire,
    HostRequestEnvelopeWire,
    HostWorkspaceIdentityWire,
)

TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


class _HostProviderQueryError(RuntimeError):
    """A routed provider-host query failed and should fall back directly."""


def provider_host_queries_enabled() -> bool:
    """Return whether direct callers should try daemon provider-host queries."""

    if os.environ.get("SASE_PROVIDER_HOST_ACTIVE") == "1":
        return False
    if daemon_disabled(None):
        return False
    if _optional_env_bool("SASE_DAEMON_FORCE_DIRECT") is True:
        return False
    env_value = _optional_env_bool("SASE_PROVIDER_HOST_QUERIES")
    if env_value is not None:
        return env_value
    return False


def host_vcs_query(
    query: str,
    *,
    cwd: str,
    payload: dict[str, Any] | None = None,
    manifest_plugin_id: str = "builtin.vcs.bare_git",
    timeout_ms: int = 10_000,
    client: LocalDaemonClient | None = None,
) -> dict[str, Any]:
    request = _request(
        family="vcs",
        operation="vcs.query",
        declared_capability=HOST_CAP_VCS_QUERY,
        cwd=cwd,
        payload={"query": query, "cwd": cwd, **(payload or {})},
        manifest_plugin_id=manifest_plugin_id,
        timeout_ms=timeout_ms,
    )
    return _call(request, client=client)


def host_workspace_metadata(
    query: str,
    *,
    payload: dict[str, Any] | None = None,
    cwd: str | None = None,
    manifest_plugin_id: str | None = None,
    timeout_ms: int = 5_000,
    client: LocalDaemonClient | None = None,
) -> dict[str, Any]:
    request = _request(
        family="workspace",
        operation="workspace.metadata",
        declared_capability=HOST_CAP_WORKSPACE_METADATA,
        cwd=cwd,
        payload={"query": query, **(payload or {})},
        manifest_plugin_id=manifest_plugin_id,
        timeout_ms=timeout_ms,
    )
    return _call(request, client=client)


def host_workspace_resolve_ref(
    ref: str,
    workflow_type: str,
    *,
    cwd: str | None = None,
    timeout_ms: int = 5_000,
    client: LocalDaemonClient | None = None,
) -> dict[str, Any]:
    request = _request(
        family="workspace",
        operation="workspace.resolve_ref",
        declared_capability=HOST_CAP_WORKSPACE_RESOLVE_REF,
        cwd=cwd,
        payload={"ref": ref, "workflow_type": workflow_type},
        manifest_plugin_id=_workspace_manifest_plugin_id(workflow_type),
        timeout_ms=timeout_ms,
    )
    return _call(request, client=client)


def _call(
    request: HostRequestEnvelopeWire, *, client: LocalDaemonClient | None
) -> dict[str, Any]:
    try:
        response = (client or LocalDaemonClient()).host_call(request)
    except LocalDaemonError as exc:
        raise _HostProviderQueryError(str(exc)) from exc
    if response.status != "ok":
        error = response.error
        message = error.message if error is not None else "provider host query failed"
        raise _HostProviderQueryError(message)
    return dict(response.result)


def _request(
    *,
    family: str,
    operation: str,
    declared_capability: str,
    cwd: str | None,
    payload: dict[str, Any],
    manifest_plugin_id: str | None,
    timeout_ms: int,
) -> HostRequestEnvelopeWire:
    workspace_dir = str(Path(cwd).resolve()) if cwd else None
    project_id = Path(workspace_dir).name if workspace_dir else "default"
    return HostRequestEnvelopeWire(
        schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
        request_id=f"host_req_{uuid.uuid4().hex}",
        deadline=HostDeadlineWire(timeout_ms=timeout_ms),
        actor=HostActorWire(
            schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
            actor_type="python-client",
            name="sase",
            version=None,
            runtime="python",
        ),
        operation=HostOperationSelectorWire(family=family, operation=operation),
        declared_capabilities=(
            HOST_CAP_IPC_V1,
            HOST_CAP_MANIFEST_V1,
            declared_capability,
        ),
        workspace=HostWorkspaceIdentityWire(
            project_id=project_id,
            project_dir=workspace_dir,
            workspace_dir=workspace_dir,
            changespec=None,
        ),
        environment=HostEnvironmentPolicyWire(
            inherit=False,
            allow=("PATH", "HOME", "SASE_HOME", "GIT_*", "GH_*", "GITHUB_*"),
            deny=("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"),
            required=("PATH", "HOME"),
        ),
        manifest=_manifest(manifest_plugin_id),
        payload=payload,
    )


def _manifest(plugin_id: str | None) -> HostManifestWire | None:
    if plugin_id is None:
        return None
    record = discover_host_manifests().by_plugin_id().get(plugin_id)
    return None if record is None else record.manifest


def _workspace_manifest_plugin_id(workflow_type: str) -> str | None:
    if workflow_type == "cd":
        return "builtin.workspace.cd"
    if workflow_type == "git":
        return "builtin.vcs.bare_git"
    if workflow_type == "gh":
        return "external.github"
    return None


def _optional_env_bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


__all__ = [
    "host_vcs_query",
    "host_workspace_metadata",
    "host_workspace_resolve_ref",
    "provider_host_queries_enabled",
]
