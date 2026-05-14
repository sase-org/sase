from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

from sase.host.manifest import discover_host_manifests
from sase.host.runtime import (
    ProviderHostRuntime,
    ProviderHostRuntimeConfig,
    redact_host_log,
)
from sase.host.wire import (
    HOST_CAP_IPC_V1,
    PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
    HostEnvironmentRequirementWire,
    HostManifestWire,
    HostNetworkPolicyWire,
    HostProcessPolicyWire,
    host_wire_to_json_dict,
)


def _request(
    operation: str = "fake.echo",
    payload: dict[str, Any] | None = None,
    *,
    timeout_ms: int = 30_000,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
        "request_id": "host_req_py_runtime",
        "deadline": {
            "timeout_ms": timeout_ms,
            "deadline_unix_ms": None,
            "cancellation_token": "cancel-host-req",
        },
        "actor": {
            "schema_version": PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
            "actor_type": "test",
            "name": "pytest",
            "version": "0.1.0",
            "runtime": "python",
        },
        "operation": {
            "family": "config",
            "operation": operation,
        },
        "declared_capabilities": [HOST_CAP_IPC_V1],
        "workspace": {
            "project_id": "project-a",
            "project_dir": None,
            "workspace_dir": None,
            "changespec": None,
        },
        "environment": {
            "inherit": False,
            "allow": [],
            "deny": [],
            "required": [],
        },
        "manifest": manifest,
        "payload": payload or {},
    }


def test_runtime_fake_operation_logs_and_redacts_secret() -> None:
    runtime = ProviderHostRuntime(ProviderHostRuntimeConfig())

    response = runtime.handle_json_frame(
        json.dumps(_request("fake.log", {"message": "token=super-secret"}))
    )

    assert response.status == "ok"
    assert response.result == {"logged": True}
    assert response.logs[0].message == "token=[REDACTED]"


def test_runtime_fake_sleep_returns_typed_timeout() -> None:
    runtime = ProviderHostRuntime(ProviderHostRuntimeConfig())

    response = runtime.handle_json_frame(
        json.dumps(_request("fake.sleep", {"sleep_ms": 20}, timeout_ms=1))
    )

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "host_timeout"
    assert response.error.retryable is True


def test_runtime_rejects_operation_not_declared_by_manifest() -> None:
    runtime = ProviderHostRuntime(ProviderHostRuntimeConfig())

    response = runtime.handle_json_frame(
        json.dumps(_request("fake.echo", manifest=_manifest("config.fake.log")))
    )

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "operation_unsupported"
    assert response.error.target == "manifest.operation_families"


def test_runtime_rejects_network_when_manifest_denies_it() -> None:
    runtime = ProviderHostRuntime(ProviderHostRuntimeConfig())

    response = runtime.handle_json_frame(
        json.dumps(
            _request(
                "fake.echo",
                {"network_required": True},
                manifest=_manifest("config.fake.echo", network_mode="deny"),
            )
        )
    )

    assert response.status == "error"
    assert response.error is not None
    assert response.error.code == "network_denied"


def test_manifest_discovery_reports_builtin_and_unknown_plugins() -> None:
    discovery = discover_host_manifests(
        entry_points={
            "sase_llm": ("codex",),
            "sase_vcs": ("github", "custom"),
            "sase_workspace": ("github",),
            "sase_config": ("sase_github",),
            "sase_xprompts": ("sase_github",),
        }
    )

    records = discovery.by_plugin_id()
    assert records["builtin.llm.codex"].compatibility_mode == "builtin_default"
    assert records["external.github"].manifest.network.mode == "declared"
    assert any(
        "sase_vcs:custom has no host manifest" in item for item in discovery.diagnostics
    )


def test_provider_host_cli_round_trips_over_real_subprocess() -> None:
    frame = json.dumps(_request("fake.echo", {"value": 42})) + "\n"

    completed = subprocess.run(
        [sys.executable, "-m", "sase", "daemon", "provider-host"],
        input=frame,
        text=True,
        capture_output=True,
        timeout=5,
        check=True,
    )

    payload = json.loads(completed.stdout.splitlines()[0])
    assert payload["status"] == "ok"
    assert payload["request_id"] == "host_req_py_runtime"
    assert payload["result"]["echo"] == {"value": 42}
    assert "provider host handled request_id=host_req_py_runtime" in completed.stderr


def test_redact_host_log_handles_common_credential_shapes() -> None:
    assert redact_host_log("api_key=abc Bearer secret-token") == (
        "api_key=[REDACTED] Bearer [REDACTED]"
    )


def _manifest(*operation_families: str, network_mode: str = "deny") -> dict[str, Any]:
    return host_wire_to_json_dict(
        HostManifestWire(
            schema_version=PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
            plugin_id="test.plugin",
            version="1.0.0",
            operation_families=operation_families,
            network=HostNetworkPolicyWire(mode=network_mode),
            process=HostProcessPolicyWire(spawn_allowed=False),
            environment=HostEnvironmentRequirementWire(),
        )
    )
