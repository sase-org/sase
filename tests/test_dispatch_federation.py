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


def test_empty_remote_hosts_keep_facade_disabled_without_rust_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail_binding(name: str) -> object:
        raise AssertionError(f"unexpected rust binding lookup: {name}")

    monkeypatch.setattr(federation, "require_rust_binding", fail_binding)

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


def test_host_config_validates_plan_and_redacts_secret(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def validate(plan: dict[str, Any]) -> dict[str, Any]:
        return {**plan, "endpoint": "https://fleet.example.test"}

    monkeypatch.setattr(federation, "require_rust_binding", lambda _name: validate)
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


def test_host_config_requires_env_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        federation,
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
