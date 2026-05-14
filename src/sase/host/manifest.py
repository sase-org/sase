"""Manifest discovery and policy helpers for provider/plugin host calls."""

from __future__ import annotations

import importlib.metadata
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.host.wire import (
    PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
    HostManifestWire,
    HostNetworkPolicyWire,
    HostProcessPolicyWire,
    HostRequestEnvelopeWire,
    HostEnvironmentRequirementWire,
)

_ENTRY_POINT_GROUPS = (
    "sase_llm",
    "sase_vcs",
    "sase_workspace",
    "sase_config",
    "sase_xprompts",
)


@dataclass(frozen=True)
class HostManifestRecord:
    manifest: HostManifestWire
    entry_points: Mapping[str, tuple[str, ...]]
    compatibility_mode: str
    source: str
    daemon_authoritative: bool
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class HostManifestDiscovery:
    records: tuple[HostManifestRecord, ...]
    diagnostics: tuple[str, ...]

    def by_plugin_id(self) -> dict[str, HostManifestRecord]:
        return {record.manifest.plugin_id: record for record in self.records}


class HostPolicyError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        target: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.target = target
        self.details = details


def discover_host_manifests(
    *,
    entry_points: Mapping[str, Iterable[str]] | None = None,
) -> HostManifestDiscovery:
    discovered = (
        {group: tuple(names) for group, names in entry_points.items()}
        if entry_points is not None
        else _installed_entry_points()
    )
    records = list(_builtin_manifest_records())
    diagnostics: list[str] = []

    if _entry_point_present(discovered, "sase_vcs", "github") or _entry_point_present(
        discovered, "sase_workspace", "github"
    ):
        records.append(_github_manifest_record())

    known = {
        (group, name)
        for record in records
        for group, names in record.entry_points.items()
        for name in names
    }
    for group, names in discovered.items():
        for name in names:
            if (group, name) not in known:
                diagnostics.append(
                    f"{group}:{name} has no host manifest; daemon-authoritative "
                    "routing requires an explicit manifest"
                )

    return HostManifestDiscovery(records=tuple(records), diagnostics=tuple(diagnostics))


def validate_manifest_for_request(request: HostRequestEnvelopeWire) -> None:
    manifest = request.manifest
    if manifest is None:
        return
    if manifest.schema_version != PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION:
        raise HostPolicyError(
            "manifest_invalid",
            (
                "host manifest schema mismatch: "
                f"got {manifest.schema_version}, "
                f"expected {PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION}"
            ),
            target="manifest.schema_version",
        )
    if not manifest.plugin_id.strip():
        raise HostPolicyError(
            "manifest_invalid",
            "host manifest plugin_id must not be empty",
            target="manifest.plugin_id",
        )
    if manifest.operation_families and not _manifest_allows_operation(
        manifest, request
    ):
        raise HostPolicyError(
            "operation_unsupported",
            (
                "manifest does not declare operation family "
                f"{operation_policy_key(request)}"
            ),
            target="manifest.operation_families",
            details={"operation": operation_policy_key(request)},
        )
    if _request_requires_network(request) and not _network_policy_allows(
        manifest.network
    ):
        raise HostPolicyError(
            "network_denied",
            (
                "manifest network policy denies network use for "
                f"{operation_policy_key(request)}"
            ),
            target="manifest.network",
            details={"mode": manifest.network.mode},
        )


def operation_policy_key(request: HostRequestEnvelopeWire) -> str:
    operation = request.operation.operation
    family = request.operation.family
    if operation == family or operation.startswith(f"{family}."):
        return operation
    return f"{family}.{operation}"


def effective_timeout_ms(
    request: HostRequestEnvelopeWire, *, default_timeout_ms: int
) -> int:
    requested = request.deadline.timeout_ms
    if requested is not None:
        return requested
    manifest = request.manifest
    if manifest is None:
        return default_timeout_ms
    key = operation_policy_key(request)
    hint = manifest.timeout_hints_ms.get(key) or manifest.timeout_hints_ms.get(
        request.operation.family
    )
    if hint is None:
        return default_timeout_ms
    return min(int(hint), default_timeout_ms)


def resource_policy_diagnostics() -> dict[str, Any]:
    return {
        "timeout": {
            "state": "active",
            "default_ms": 30_000,
            "source": "request bounded by daemon policy; manifest hints are upper-bounded",
        },
        "rss_soft_cap": {
            "state": "unavailable",
            "reason": "portable Python host RSS enforcement is not enabled in v1",
        },
        "cgroup_v2_cpu_quota": _cgroup_v2_diagnostics(),
        "seccomp": _seccomp_diagnostics(),
        "compatibility_mode": {
            "state": "active",
            "reason": "known built-ins use compatibility manifests until real provider routing lands",
        },
    }


def _installed_entry_points() -> dict[str, tuple[str, ...]]:
    entry_points = importlib.metadata.entry_points()
    return {
        group: tuple(
            ep.name
            for ep in sorted(entry_points.select(group=group), key=lambda e: e.name)
        )
        for group in _ENTRY_POINT_GROUPS
    }


def _entry_point_present(
    discovered: Mapping[str, Iterable[str]], group: str, name: str
) -> bool:
    return name in set(discovered.get(group, ()))


def _builtin_manifest_records() -> tuple[HostManifestRecord, ...]:
    return (
        _llm_record("claude", ("claude",), ("CLAUDE_*",)),
        _llm_record("codex", ("codex",), ("CODEX_*", "OPENAI_*")),
        _llm_record("gemini", ("gemini",), ("GEMINI_*", "GOOGLE_*")),
        _llm_record("opencode", ("opencode",), ("OPENCODE_*",)),
        _llm_record("qwen", ("qwen",), ("QWEN_*",)),
        HostManifestRecord(
            manifest=HostManifestWire(
                schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
                plugin_id="builtin.vcs.bare_git",
                version="compatibility.v1",
                operation_families=(
                    "vcs.query",
                    "vcs.mutation",
                    "vcs.commit_dispatch",
                    "workspace.metadata",
                    "workspace.resolve_ref",
                    "workspace.setup",
                    "workspace.submit",
                ),
                capabilities=("host.manifest.v1",),
                network=HostNetworkPolicyWire(
                    mode="compatibility",
                    allowed_hosts=(),
                ),
                filesystem_roots=(
                    "cwd",
                    "workspace_root",
                    "project_file_dir",
                    "sase_home",
                ),
                process=HostProcessPolicyWire(
                    spawn_allowed=True,
                    allowed_commands=("git",),
                ),
                environment=HostEnvironmentRequirementWire(
                    required_vars=("PATH", "HOME"),
                    optional_vars=("SASE_HOME", "GIT_*"),
                ),
                timeout_hints_ms={
                    "vcs.query": 10_000,
                    "vcs.mutation": 120_000,
                    "workspace.setup": 300_000,
                },
                warm_host_eligible=True,
                wasm_compatible=False,
                wasm_notes=("Current compatibility implementation shells out to git."),
            ),
            entry_points={
                "sase_vcs": ("bare_git",),
                "sase_workspace": ("bare_git",),
            },
            compatibility_mode="builtin_default",
            source="builtin",
            daemon_authoritative=True,
        ),
        HostManifestRecord(
            manifest=HostManifestWire(
                schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
                plugin_id="builtin.workspace.cd",
                version="compatibility.v1",
                operation_families=("workspace.metadata", "workspace.resolve_ref"),
                capabilities=("host.manifest.v1",),
                network=HostNetworkPolicyWire(mode="deny"),
                filesystem_roots=("cwd", "declared_workspace_root"),
                process=HostProcessPolicyWire(spawn_allowed=False),
                environment=HostEnvironmentRequirementWire(
                    required_vars=("HOME",),
                    optional_vars=("SASE_HOME",),
                ),
                timeout_hints_ms={
                    "workspace.metadata": 1_000,
                    "workspace.resolve_ref": 5_000,
                },
                warm_host_eligible=True,
                wasm_compatible=True,
                wasm_notes="Path and config inputs must come from the host envelope.",
            ),
            entry_points={"sase_workspace": ("cd",)},
            compatibility_mode="builtin_default",
            source="builtin",
            daemon_authoritative=True,
        ),
    )


def _llm_record(
    name: str, commands: tuple[str, ...], optional_env: tuple[str, ...]
) -> HostManifestRecord:
    return HostManifestRecord(
        manifest=HostManifestWire(
            schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
            plugin_id=f"builtin.llm.{name}",
            version="compatibility.v1",
            operation_families=("llm.metadata", "llm.resolve_model", "llm.invoke"),
            capabilities=("host.manifest.v1",),
            network=HostNetworkPolicyWire(mode="compatibility"),
            filesystem_roots=(
                "cwd",
                "sase_home",
                "provider_config_home",
                "agent_artifacts_dir",
            ),
            process=HostProcessPolicyWire(
                spawn_allowed=True, allowed_commands=commands
            ),
            environment=HostEnvironmentRequirementWire(
                required_vars=("PATH", "HOME"),
                optional_vars=("SASE_HOME", *optional_env),
            ),
            timeout_hints_ms={
                "llm.metadata": 1_000,
                "llm.resolve_model": 1_000,
                "llm.invoke": 1_800_000,
            },
            warm_host_eligible=True,
            wasm_compatible=False,
            wasm_notes="Metadata can be WASM-compatible; invocation needs provider CLI APIs.",
        ),
        entry_points={"sase_llm": (name,)},
        compatibility_mode="builtin_default",
        source="builtin",
        daemon_authoritative=True,
    )


def _github_manifest_record() -> HostManifestRecord:
    return HostManifestRecord(
        manifest=HostManifestWire(
            schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
            plugin_id="external.github",
            version="compatibility.v1",
            operation_families=(
                "vcs.query",
                "vcs.mutation",
                "vcs.commit_dispatch",
                "workspace.metadata",
                "workspace.resolve_ref",
                "workspace.submit",
                "config.resources",
                "xprompt.catalog",
            ),
            capabilities=("host.manifest.v1",),
            network=HostNetworkPolicyWire(
                mode="declared",
                allowed_hosts=("github.com", "api.github.com"),
            ),
            filesystem_roots=(
                "cwd",
                "workspace_root",
                "project_file_dir",
                "sase_home",
                "package_resources",
            ),
            process=HostProcessPolicyWire(
                spawn_allowed=True, allowed_commands=("git", "gh")
            ),
            environment=HostEnvironmentRequirementWire(
                required_vars=("PATH", "HOME"),
                optional_vars=("SASE_HOME", "GH_*", "GITHUB_*"),
            ),
            timeout_hints_ms={
                "vcs.query": 15_000,
                "vcs.mutation": 180_000,
                "config.resources": 5_000,
                "xprompt.catalog": 5_000,
            },
            warm_host_eligible=True,
            wasm_compatible=False,
            wasm_notes=(
                "Resource catalog is WASM-compatible; VCS/workspace calls need git/gh."
            ),
        ),
        entry_points={
            "sase_vcs": ("github",),
            "sase_workspace": ("github",),
            "sase_config": ("sase_github",),
            "sase_xprompts": ("sase_github",),
        },
        compatibility_mode="external_maintained_default",
        source="maintained_external",
        daemon_authoritative=True,
    )


def _manifest_allows_operation(
    manifest: HostManifestWire, request: HostRequestEnvelopeWire
) -> bool:
    allowed = set(manifest.operation_families)
    key = operation_policy_key(request)
    return (
        key in allowed
        or request.operation.operation in allowed
        or request.operation.family in allowed
    )


def _request_requires_network(request: HostRequestEnvelopeWire) -> bool:
    payload = dict(request.payload)
    network = payload.get("network")
    if isinstance(network, Mapping) and network.get("required") is True:
        return True
    return (
        payload.get("network_required") is True
        or payload.get("requires_network") is True
    )


def _network_policy_allows(policy: HostNetworkPolicyWire) -> bool:
    return policy.mode in {"allow", "declared", "compatibility"}


def _cgroup_v2_diagnostics() -> dict[str, Any]:
    root = Path("/sys/fs/cgroup")
    controllers = root / "cgroup.controllers"
    return {
        "state": "available" if controllers.exists() else "unavailable",
        "enforced": False,
        "reason": (
            "cgroup v2 detected; quota enforcement is opt-in for provider host v1"
            if controllers.exists()
            else "cgroup v2 controllers file is not present"
        ),
    }


def _seccomp_diagnostics() -> dict[str, Any]:
    if os.name != "posix":
        return {"state": "unavailable", "enforced": False, "reason": "non-POSIX host"}
    status = Path("/proc/self/status")
    if not status.exists():
        return {
            "state": "unavailable",
            "enforced": False,
            "reason": "/proc/self/status is unavailable",
        }
    mode = "unknown"
    for line in status.read_text(errors="replace").splitlines():
        if line.startswith("Seccomp:"):
            mode = line.split(":", 1)[1].strip()
            break
    return {
        "state": "available",
        "enforced": mode not in {"0", "unknown"},
        "mode": mode,
        "reason": "seccomp profile detection only; provider host v1 does not install profiles",
    }


__all__ = [
    "HostManifestDiscovery",
    "HostManifestRecord",
    "HostPolicyError",
    "discover_host_manifests",
    "effective_timeout_ms",
    "operation_policy_key",
    "resource_policy_diagnostics",
    "validate_manifest_for_request",
]
