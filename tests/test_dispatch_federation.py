"""Tests for the local federation-worker Python facade."""

from __future__ import annotations

import json
import socket
import struct
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import pytest

import sase.dispatch.federation as federation
from sase.dispatch.credentials import LocalCredentialStore
from sase.dispatch.models import CredentialRecord, MachineDiagnostic
from tests.conftest import redirect_sase_home


def _installation_id(hex_char: str) -> str:
    return f"sase_inst_v1_{hex_char * 64}"


def test_empty_remote_hosts_keep_facade_disabled_without_rust_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_binding(name: str) -> object:
        raise AssertionError(f"unexpected rust binding lookup: {name}")

    monkeypatch.setattr(federation._hosts, "require_rust_binding", fail_binding)

    config = federation.load_federation_config(
        {
            "dispatch": {
                "federation_worker": {"sase_home": str(tmp_path)},
                "remote_hosts": [],
            }
        }
    )
    facade = federation.build_federation_facade(config)

    assert not config.enabled
    assert facade.health_sync()["status"] == "disabled"
    assert facade.summary_sync() == {
        "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
        "operation": "summary",
        "disabled": True,
        "hosts": [],
    }
    assert facade.attention_sync({"schema_version": 1, "logical_keys": []}) == {
        "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
        "operation": "attention",
        "disabled": True,
        "hosts": [],
    }
    assert facade.attention_inventory_sync({"schema_version": 1}) == {
        "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
        "operation": "attention_inventory",
        "disabled": True,
        "hosts": [],
    }
    with pytest.raises(
        federation.FederationWorkerUnavailable,
        match="no configured dispatch machines are available",
    ):
        facade.mutate_sync("apollo", {"schema_version": 1})
    with pytest.raises(
        federation.FederationWorkerUnavailable,
        match="no configured dispatch machines are available",
    ):
        facade.resolve_attention_sync("apollo", {"schema_version": 1})


def test_federation_worker_resolver_checks_active_python_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    worker = tmp_path / federation.FEDERATION_WORKER_COMMAND
    worker.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(federation._supervisor.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        federation._supervisor.sys, "executable", str(tmp_path / "python")
    )

    assert federation.resolve_federation_worker_command() == (str(worker),)


def test_host_config_validates_plan_and_redacts_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def validate(plan: dict[str, Any]) -> dict[str, Any]:
        return {**plan, "endpoint": "https://fleet.example.test"}

    monkeypatch.setattr(
        federation._hosts, "require_rust_binding", lambda _name: validate
    )
    monkeypatch.setenv("SASE_FLEET_TOKEN", "secret-token")

    config = federation.load_federation_config(
        {
            "dispatch": {
                "federation_worker": {"sase_home": str(tmp_path)},
                "remote_hosts": [
                    {
                        "alias": "workstation",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "env:SASE_FLEET_TOKEN",
                        "pinned_installation_id": "remote-install",
                    }
                ],
            }
        }
    )

    assert config.enabled
    assert config.hosts_wire()[0]["bearer_token"] == "secret-token"
    assert config.redacted_hosts()[0]["bearer_token"] == "<redacted>"


def test_machine_config_derives_federation_host_from_local_credential(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pin = "sase_inst_v1_" + "a" * 64
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    LocalCredentialStore().put(
        CredentialRecord(
            ref="fleet:workstation",
            token="stored-token",
            token_type="bearer",
            provider_ref="builtin@https",
            endpoint="https://fleet.example.test/",
            installation_id=pin,
            scopes=("fleet.launch",),
        )
    )

    def validate(plan: dict[str, Any]) -> dict[str, Any]:
        assert plan["provider_ref"] == "builtin:https"
        return {**plan, "endpoint": "https://fleet.example.test"}

    monkeypatch.setattr(
        federation._hosts, "require_rust_binding", lambda _name: validate
    )

    config = federation.load_federation_config(
        {
            "dispatch": {
                "federation_worker": {"sase_home": str(tmp_path / ".sase")},
                "machines": {
                    "workstation": {
                        "provider": "builtin@https",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "fleet:workstation",
                        "installation_pin": pin,
                    }
                },
            }
        }
    )

    assert config.enabled
    assert config.hosts_wire() == [
        {
            "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
            "alias": "workstation",
            "plan": {
                "provider_ref": "builtin:https",
                "endpoint": "https://fleet.example.test",
                "pinned_installation_id": pin,
                "connection_kind": "gateway",
                "schema_version": 1,
                "credential_ref": "fleet:workstation",
                "tls": {
                    "schema_version": 1,
                    "mode": "system_roots",
                    "ca_ref": None,
                    "server_name_ref": None,
                },
            },
            "bearer_token": "stored-token",
            "origin_installation_id": pin,
        }
    ]


def test_host_config_requires_env_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        federation._hosts,
        "require_rust_binding",
        lambda _name: lambda plan: {**plan, "credential_ref": "env:MISSING_TOKEN"},
    )
    monkeypatch.delenv("MISSING_TOKEN", raising=False)

    with pytest.raises(federation.FederationConfigError, match="MISSING_TOKEN"):
        federation.load_federation_config(
            {
                "dispatch": {
                    "federation_worker": {"sase_home": str(tmp_path)},
                    "remote_hosts": [{"endpoint": "https://fleet.example.test"}],
                }
            }
        )


def test_dispatch_machines_resolve_local_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    installation_id = _installation_id("a")

    class Store:
        def get(self, ref: str) -> CredentialRecord | None:
            assert ref == "cred:workstation"
            return CredentialRecord(
                ref=ref,
                token="stored-secret",
                token_type="bearer",
                provider_ref="builtin@https",
                endpoint="https://fleet.example.test",
                installation_id=installation_id,
            )

    monkeypatch.setattr(
        federation._hosts,
        "validate_connection_plan",
        lambda _machine, **kwargs: (),
    )

    config = federation.load_federation_config(
        {
            "dispatch": {
                "federation_worker": {"sase_home": str(tmp_path)},
                "machines": {
                    "workstation": {
                        "provider_ref": "builtin@https",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "cred:workstation",
                        "pinned_installation_id": installation_id,
                    }
                },
            }
        },
        credential_store=Store(),  # type: ignore[arg-type]
    )

    assert config.enabled
    assert config.diagnostics == ()
    wire = config.hosts_wire()[0]
    assert wire["alias"] == "workstation"
    assert wire["bearer_token"] == "stored-secret"
    assert wire["origin_installation_id"] == installation_id
    assert config.redacted_hosts()[0]["bearer_token"] == "<redacted>"


def test_dispatch_machines_degrade_to_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Store:
        def get(self, _ref: str) -> CredentialRecord | None:
            return None

    monkeypatch.setattr(
        federation._hosts,
        "validate_connection_plan",
        lambda _machine, **kwargs: (
            MachineDiagnostic(
                code="invalid_connection_plan",
                alias="unused",
                severity="error",
                message="unused",
            ),
        ),
    )

    config = federation.load_federation_config(
        {
            "dispatch": {
                "federation_worker": {"sase_home": str(tmp_path)},
                "machines": {
                    "missing": {
                        "provider_ref": "builtin@https",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "cred:missing",
                        "pinned_installation_id": _installation_id("b"),
                    },
                    "quarantined": {
                        "provider_ref": "builtin@https",
                        "endpoint": "https://fleet.example.test",
                        "credential_ref": "cred:quarantined",
                        "pinned_installation_id": _installation_id("c"),
                        "quarantined": True,
                        "quarantine_reason": "pin mismatch",
                    },
                },
            }
        },
        credential_store=Store(),  # type: ignore[arg-type]
    )

    assert not config.enabled
    assert config.hosts == ()
    codes = {diagnostic.code for diagnostic in config.diagnostics}
    assert {"credential_missing", "machine_quarantined"} <= codes
    disabled = federation.build_federation_facade(config).summary_sync()
    assert disabled["disabled"] is True
    assert {item["code"] for item in disabled["diagnostics"]} >= codes


def test_supervisor_spawns_worker_and_replaces_config(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    argv: list[str] = []
    state = {"started": False}

    class Proc:
        def poll(self) -> int | None:
            return None

    class Client:
        def __init__(self, _path: Path, _max_frame_bytes: int) -> None:
            pass

        def request(
            self, operation: Mapping[str, Any], *, timeout_seconds: float
        ) -> dict[str, Any]:
            calls.append(dict(operation))
            if operation.get("op") == "health":
                if not state["started"]:
                    raise federation.FederationWorkerUnavailable("not ready")
                return {"schema_version": 1, "status": "ok"}
            if operation.get("op") == "replace_config":
                return {"schema_version": 1, "configured_hosts": 1}
            if operation.get("op") == "summary":
                return {"schema_version": 1, "hosts": [{"status": "ok"}]}
            raise AssertionError(f"unexpected operation: {operation}")

    def popen(command: list[str], **_kwargs: object) -> Proc:
        argv.extend(command)
        state["started"] = True
        return Proc()

    config = federation.FederationConfig(
        worker=federation.FederationWorkerSettings(
            command=("worker-bin",),
            sase_home=tmp_path,
            socket_path=tmp_path / "worker.sock",
            idle_timeout_seconds=3,
        ),
        hosts=(
            federation.FederationHostConfig(
                alias="remote",
                plan={
                    "provider_ref": "fleet",
                    "endpoint": "https://fleet.example.test",
                    "pinned_installation_id": "remote-install",
                },
                bearer_token="secret-token",
            ),
        ),
    )
    supervisor = federation.FederationWorkerSupervisor(
        config,
        client_factory=cast(federation.IpcClientFactory, Client),
        popen=cast(federation.PopenFactory, popen),
        sleep=lambda _seconds: None,
    )

    assert supervisor.request({"op": "summary"}, timeout_seconds=1)["hosts"] == [
        {"status": "ok"}
    ]
    assert argv[:1] == ["worker-bin"]
    assert "--sase-home" in argv
    assert str(tmp_path) in argv
    assert [call["op"] for call in calls] == [
        "health",
        "health",
        "health",
        "replace_config",
        "summary",
    ]
    assert calls[3]["hosts"][0]["bearer_token"] == "secret-token"


def test_facade_read_deadline_preserves_healthy_partial_host(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, Any]] = []

    class Supervisor:
        def request(
            self,
            operation: Mapping[str, Any],
            *,
            timeout_seconds: float,
            retry: bool = True,
        ) -> dict[str, Any]:
            calls.append(
                {
                    "operation": dict(operation),
                    "timeout_seconds": timeout_seconds,
                    "retry": retry,
                }
            )
            return {
                "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
                "operation": "summary",
                "configured_hosts": 2,
                "partial": True,
                "hosts": [
                    {
                        "schema_version": 1,
                        "alias": "apollo",
                        "origin_installation_id": _installation_id("a"),
                        "connection_health": "online",
                        "summaries": [{"logical_key": "healthy", "status": "running"}],
                    }
                ],
                "diagnostics": [
                    {
                        "alias": "zeus",
                        "operation": "summary",
                        "code": "host_deadline_exceeded",
                        "severity": "warning",
                        "message": "zeus summary exceeded the read deadline",
                    }
                ],
            }

    config = federation.FederationConfig(
        worker=federation.FederationWorkerSettings(
            sase_home=tmp_path,
            socket_path=tmp_path / "worker.sock",
            request_timeout_seconds=5.0,
        ),
        hosts=(
            federation.FederationHostConfig(
                alias="apollo",
                plan={"provider_ref": "fleet", "endpoint": "https://apollo.test"},
                bearer_token="secret-a",
                origin_installation_id=_installation_id("a"),
            ),
            federation.FederationHostConfig(
                alias="zeus",
                plan={"provider_ref": "fleet", "endpoint": "https://zeus.test"},
                bearer_token="secret-b",
                origin_installation_id=_installation_id("b"),
            ),
        ),
    )
    facade = federation.FederationFacade(
        config,
        supervisor=cast(federation.FederationWorkerSupervisor, Supervisor()),
    )

    response = facade.summary_sync(cache_only=False, timeout_seconds=0.125)

    assert calls == [
        {
            "operation": {"op": "summary", "cache_only": False},
            "timeout_seconds": 0.125,
            "retry": True,
        }
    ]
    assert response["partial"] is True
    assert response["configured_hosts"] == 2
    assert response["hosts"][0]["alias"] == "apollo"
    assert response["hosts"][0]["summaries"][0]["logical_key"] == "healthy"
    assert response["diagnostics"][0]["code"] == "host_deadline_exceeded"


def test_facade_catalog_hosts_threads_per_host_queries(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    class Supervisor:
        def request(
            self,
            operation: Mapping[str, Any],
            *,
            timeout_seconds: float,
            retry: bool = True,
        ) -> dict[str, Any]:
            calls.append(
                {
                    "operation": dict(operation),
                    "timeout_seconds": timeout_seconds,
                    "retry": retry,
                }
            )
            return {
                "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
                "operation": "catalog",
                "hosts": [],
            }

    config = federation.FederationConfig(
        worker=federation.FederationWorkerSettings(
            sase_home=tmp_path,
            socket_path=tmp_path / "worker.sock",
        ),
        hosts=(
            federation.FederationHostConfig(
                alias="apollo",
                plan={"provider_ref": "fleet", "endpoint": "https://apollo.test"},
                bearer_token="secret-a",
                origin_installation_id=_installation_id("a"),
            ),
        ),
    )
    facade = federation.FederationFacade(
        config,
        supervisor=cast(federation.FederationWorkerSupervisor, Supervisor()),
    )

    response = facade.catalog_hosts_sync(
        (
            {
                "schema_version": 1,
                "installation_id": _installation_id("a"),
                "query": {
                    "schema_version": 1,
                    "limit": 100,
                    "cursor": "a:100",
                    "include_terminal": True,
                },
            },
        ),
        timeout_seconds=0.25,
    )

    assert response["operation"] == "catalog"
    assert calls == [
        {
            "operation": {
                "op": "catalog_hosts",
                "queries": [
                    {
                        "schema_version": 1,
                        "installation_id": _installation_id("a"),
                        "query": {
                            "schema_version": 1,
                            "limit": 100,
                            "cursor": "a:100",
                            "include_terminal": True,
                        },
                    }
                ],
                "cache_only": False,
            },
            "timeout_seconds": 0.25,
            "retry": True,
        }
    ]


def test_ipc_client_decodes_success_and_error_frames(tmp_path: Path) -> None:
    success_socket = tmp_path / "success.sock"
    success_thread = _serve_one_ipc(
        success_socket,
        lambda request: {
            "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
            "request_id": request["request_id"],
            "ok": True,
            "result": {"status": "ok"},
        },
    )

    client = federation.FederationIpcClient(success_socket)
    assert client.request({"op": "health"}, timeout_seconds=1) == {"status": "ok"}
    success_thread.join(timeout=1)
    assert not success_thread.is_alive()

    error_socket = tmp_path / "error.sock"
    error_thread = _serve_one_ipc(
        error_socket,
        lambda request: {
            "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
            "request_id": request["request_id"],
            "ok": False,
            "error": {
                "schema_version": federation.FEDERATION_IPC_SCHEMA_VERSION,
                "code": "unavailable",
                "message": "remote failed",
            },
        },
    )

    with pytest.raises(federation.FederationWorkerResponseError, match="remote failed"):
        federation.FederationIpcClient(error_socket).request(
            {"op": "summary"}, timeout_seconds=1
        )
    error_thread.join(timeout=1)
    assert not error_thread.is_alive()


def test_ipc_client_rejects_oversized_response(tmp_path: Path) -> None:
    socket_path = tmp_path / "oversize.sock"
    thread = _serve_raw_ipc(
        socket_path,
        lambda _request: struct.pack(">I", 257) + (b"x" * 257),
    )

    with pytest.raises(federation.FederationWorkerUnavailable, match="frame limit"):
        federation.FederationIpcClient(socket_path, max_frame_bytes=256).request(
            {"op": "health"}, timeout_seconds=1
        )
    thread.join(timeout=1)
    assert not thread.is_alive()


def _serve_one_ipc(
    socket_path: Path,
    handler: Callable[[dict[str, Any]], dict[str, Any]],
) -> threading.Thread:
    def encode(request: dict[str, Any]) -> bytes:
        response = json.dumps(handler(request), separators=(",", ":")).encode()
        return struct.pack(">I", len(response)) + response

    return _serve_raw_ipc(socket_path, encode)


def _serve_raw_ipc(
    socket_path: Path,
    handler: Callable[[dict[str, Any]], bytes],
) -> threading.Thread:
    ready = threading.Event()

    def run() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(socket_path))
            server.listen(1)
            ready.set()
            conn, _addr = server.accept()
            with conn:
                header = _recv_exact(conn, 4)
                length = struct.unpack(">I", header)[0]
                request = json.loads(_recv_exact(conn, length))
                conn.sendall(handler(request))

    thread = threading.Thread(target=run)
    thread.start()
    assert ready.wait(timeout=1)
    return thread


def _recv_exact(conn: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = conn.recv(remaining)
        if not chunk:
            raise AssertionError("socket closed before frame was complete")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
