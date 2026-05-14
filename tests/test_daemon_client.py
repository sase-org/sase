"""Tests for the low-level local daemon Python client."""

from __future__ import annotations

import json
import socket
import struct
import threading
from pathlib import Path
from typing import Any

import pytest

from sase.daemon import client as daemon_client
from sase.daemon.client import (
    LocalDaemonClient,
    LocalDaemonRpcError,
    LocalDaemonTransportError,
    default_socket_path,
)


def test_default_socket_path_matches_rust_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", "/tmp/sase-home")
    monkeypatch.setenv("HOSTNAME", "work station/01")

    assert default_socket_path() == Path(
        "/tmp/sase-home/run/work-station-01/sase-daemon.sock"
    )


def test_health_sends_framed_request_and_returns_payload(tmp_path: Path) -> None:
    request_holder: dict[str, Any] = {}
    socket_path = tmp_path / "daemon.sock"
    health_payload = {
        "schema_version": 1,
        "status": "ok",
        "service": "sase_local_daemon",
        "daemon_started": True,
        "version": "0.1.1",
        "min_client_schema_version": 1,
        "max_client_schema_version": 1,
        "fallback": {"available": False, "reason": None, "message": None},
    }
    response = {
        "schema_version": 1,
        "request_id": "req_test",
        "snapshot_id": None,
        "payload": {"type": "health", "data": health_payload},
    }
    thread = _serve_one(socket_path, response, request_holder)

    result = LocalDaemonClient(socket_path, timeout=1.0).health()
    thread.join(timeout=1)

    assert result == health_payload
    assert request_holder["request"]["payload"] == {
        "type": "health",
        "data": {"include_capabilities": True},
    }


def test_rpc_error_exposes_typed_fallback(tmp_path: Path) -> None:
    socket_path = tmp_path / "daemon.sock"
    response = {
        "schema_version": 1,
        "request_id": "req_test",
        "snapshot_id": None,
        "payload": {
            "type": "error",
            "data": {
                "schema_version": 1,
                "code": "unsupported_client_version",
                "message": "unsupported schema",
                "retryable": False,
                "target": "schema_version",
                "details": {"max_client_schema_version": 1},
                "fallback": {
                    "available": True,
                    "reason": "unsupported_client_version",
                    "message": "use direct source-store readers",
                },
            },
        },
    }
    thread = _serve_one(socket_path, response, {})

    with pytest.raises(LocalDaemonRpcError) as error:
        LocalDaemonClient(socket_path, timeout=1.0).capabilities()
    thread.join(timeout=1)

    assert error.value.code == "unsupported_client_version"
    assert error.value.target == "schema_version"
    assert error.value.fallback_reason == "unsupported_client_version"


def test_read_events_sends_subscription_request_and_reads_bounded_batches(
    tmp_path: Path,
) -> None:
    request_holder: dict[str, Any] = {}
    socket_path = tmp_path / "daemon.sock"
    responses = [
        {
            "schema_version": 1,
            "request_id": "req_events",
            "snapshot_id": "events_001",
            "payload": {
                "type": "events",
                "data": {
                    "schema_version": 1,
                    "snapshot_id": "events_001",
                    "events": [
                        {
                            "schema_version": 1,
                            "event_id": "0000000000000001",
                            "snapshot_id": "events_001",
                            "created_at": "2026-05-13T23:30:00Z",
                            "source": "daemon",
                            "payload": {
                                "type": "heartbeat",
                                "data": {"sequence": 1},
                            },
                        }
                    ],
                    "heartbeat": {
                        "schema_version": 1,
                        "sequence": 1,
                        "created_at": "2026-05-13T23:30:00Z",
                    },
                    "next_event_id": "0000000000000001",
                },
            },
        },
        {
            "schema_version": 1,
            "request_id": "req_events",
            "snapshot_id": "events_001",
            "payload": {
                "type": "events",
                "data": {
                    "schema_version": 1,
                    "snapshot_id": "events_001",
                    "events": [],
                    "heartbeat": {
                        "schema_version": 1,
                        "sequence": 2,
                        "created_at": "2026-05-13T23:30:01Z",
                    },
                    "next_event_id": "0000000000000002",
                },
            },
        },
    ]
    thread = _serve_stream(socket_path, responses, request_holder)

    batches = LocalDaemonClient(socket_path, timeout=1.0).read_events(
        2,
        after_event_id="0000000000000000",
        collections=["agents"],
        max_events=5,
    )
    thread.join(timeout=1)

    assert [batch["heartbeat"]["sequence"] for batch in batches] == [1, 2]
    assert request_holder["request"]["payload"] == {
        "type": "events",
        "data": {
            "since_event_id": "0000000000000000",
            "snapshot_id": None,
            "max_events": 5,
            "collections": ["agents"],
        },
    }


def test_oversized_request_fails_before_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_client, "LOCAL_DAEMON_MAX_PAYLOAD_BYTES", 32)

    with pytest.raises(LocalDaemonTransportError) as error:
        LocalDaemonClient(tmp_path / "missing.sock").request(
            {"type": "health", "data": {"include_capabilities": True}}
        )

    assert error.value.code == "payload_too_large"
    assert error.value.fallback_reason is None


def _serve_one(
    socket_path: Path,
    response: dict[str, Any],
    request_holder: dict[str, Any],
) -> threading.Thread:
    ready = threading.Event()

    def run() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(socket_path))
            server.listen(1)
            ready.set()
            conn, _ = server.accept()
            with conn:
                length = struct.unpack(">I", _recv_exact(conn, 4))[0]
                payload = _recv_exact(conn, length)
                request_holder["request"] = json.loads(payload.decode("utf-8"))
                encoded = json.dumps(response, separators=(",", ":")).encode("utf-8")
                conn.sendall(struct.pack(">I", len(encoded)) + encoded)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(timeout=1)
    return thread


def _serve_stream(
    socket_path: Path,
    responses: list[dict[str, Any]],
    request_holder: dict[str, Any],
) -> threading.Thread:
    ready = threading.Event()

    def run() -> None:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(socket_path))
            server.listen(1)
            ready.set()
            conn, _ = server.accept()
            with conn:
                length = struct.unpack(">I", _recv_exact(conn, 4))[0]
                payload = _recv_exact(conn, length)
                request_holder["request"] = json.loads(payload.decode("utf-8"))
                for response in responses:
                    encoded = json.dumps(response, separators=(",", ":")).encode(
                        "utf-8"
                    )
                    conn.sendall(struct.pack(">I", len(encoded)) + encoded)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(timeout=1)
    return thread


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = sock.recv(remaining)
        assert chunk
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
