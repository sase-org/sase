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
    LocalDaemonUnavailableError,
    default_socket_path,
)
from sase.daemon.scheduler import (
    SchedulerBatchSubmit,
    SchedulerLaunchSpec,
    submit_scheduler_batch,
)


class _CaptureTransport:
    def __init__(self, payload_type: str, data: dict[str, Any]) -> None:
        self.payload_type = payload_type
        self.data = data
        self.envelope: dict[str, Any] | None = None

    def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        self.envelope = envelope
        return {
            "schema_version": 1,
            "request_id": envelope["request_id"],
            "snapshot_id": None,
            "payload": {"type": self.payload_type, "data": self.data},
        }


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


def test_scheduler_submit_helper_sends_batch_payload() -> None:
    response_data = {
        "schema_version": 1,
        "handle": {
            "schema_version": 1,
            "batch_id": "batch-a",
            "idempotency_key": "idem-a",
            "queue_id": "agents",
            "project_id": "project-a",
            "slot_count": 1,
            "status": "queued",
            "created_at": "2026-05-14T06:00:00Z",
        },
        "duplicate": False,
        "status": {"schema_version": 1, "handle": {}, "slots": []},
    }
    transport = _CaptureTransport("scheduler_submit", response_data)
    client = LocalDaemonClient(transport=transport)

    result = submit_scheduler_batch(
        client,
        SchedulerBatchSubmit(
            project_id="project-a",
            idempotency_key="idem-a",
            batch_id="batch-a",
            queue_id="agents",
            launch_specs=[
                SchedulerLaunchSpec(
                    project_id="project-a",
                    prompt="run this",
                    model="codex/gpt-5.5",
                )
            ],
        ),
    )

    assert result == response_data
    assert transport.envelope is not None
    assert transport.envelope["payload"] == {
        "type": "scheduler_submit",
        "data": {
            "schema_version": 1,
            "project_id": "project-a",
            "idempotency_key": "idem-a",
            "batch_id": "batch-a",
            "queue_id": "agents",
            "launch_specs": [
                {
                    "schema_version": 1,
                    "project_id": "project-a",
                    "prompt": "run this",
                    "cwd": None,
                    "model": "codex/gpt-5.5",
                    "parent_agent_id": None,
                    "workflow_id": None,
                    "metadata": {},
                }
            ],
            "metadata": {},
        },
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


def test_rebuild_sends_storage_reset_request(tmp_path: Path) -> None:
    request_holder: dict[str, Any] = {}
    socket_path = tmp_path / "daemon.sock"
    response = {
        "schema_version": 1,
        "request_id": "req_rebuild",
        "snapshot_id": None,
        "payload": {
            "type": "rebuild",
            "data": {
                "schema_version": 1,
                "mode": "projection_storage_rebuild",
                "storage_reset_only": True,
                "limitation": "storage reset/replay only",
                "report": {"seeded_events": 0},
            },
        },
    }
    thread = _serve_one(socket_path, response, request_holder)

    result = LocalDaemonClient(socket_path, timeout=1.0).rebuild()
    thread.join(timeout=1)

    assert result["mode"] == "projection_storage_rebuild"
    assert request_holder["request"]["payload"] == {
        "type": "rebuild",
        "data": {"surface": "all", "storage_reset_only": False},
    }


def test_rebuild_can_request_explicit_storage_reset(tmp_path: Path) -> None:
    request_holder: dict[str, Any] = {}
    socket_path = tmp_path / "daemon.sock"
    response = {
        "schema_version": 1,
        "request_id": "req_rebuild",
        "snapshot_id": None,
        "payload": {
            "type": "rebuild",
            "data": {
                "schema_version": 1,
                "mode": "projection_storage_rebuild",
                "storage_reset_only": True,
                "surface": "beads",
                "project_id": "demo",
                "limitation": "storage reset/replay only",
                "report": {"seeded_events": 0},
                "summaries": [],
            },
        },
    }
    thread = _serve_one(socket_path, response, request_holder)

    result = LocalDaemonClient(socket_path, timeout=1.0).rebuild(
        storage_reset_only=True,
        surface="beads",
        project_id="demo",
    )
    thread.join(timeout=1)

    assert result["storage_reset_only"] is True
    assert request_holder["request"]["payload"] == {
        "type": "rebuild",
        "data": {
            "surface": "beads",
            "project_id": "demo",
            "storage_reset_only": True,
        },
    }


def test_verify_and_diff_send_indexing_selectors(tmp_path: Path) -> None:
    verify_holder: dict[str, Any] = {}
    verify_socket = tmp_path / "verify.sock"
    verify_response = {
        "schema_version": 1,
        "request_id": "req_verify",
        "snapshot_id": None,
        "payload": {
            "type": "verify",
            "data": {
                "schema_version": 1,
                "ok": True,
                "summaries": [],
            },
        },
    }
    verify_thread = _serve_one(verify_socket, verify_response, verify_holder)

    verify = LocalDaemonClient(verify_socket, timeout=1.0).verify(
        surface="agents",
        project_id="demo",
    )
    verify_thread.join(timeout=1)

    assert verify["ok"] is True
    assert verify_holder["request"]["payload"] == {
        "type": "verify",
        "data": {"surface": "agents", "project_id": "demo"},
    }

    diff_holder: dict[str, Any] = {}
    diff_socket = tmp_path / "diff.sock"
    diff_response = {
        "schema_version": 1,
        "request_id": "req_diff",
        "snapshot_id": None,
        "payload": {
            "type": "diff",
            "data": {
                "schema_version": 1,
                "surface": "beads",
                "records": [],
                "counts": {"missing": 0, "stale": 0, "extra": 0, "corrupt": 0},
                "next_cursor": None,
                "bounded": {"max_payload_bytes": 1048576, "truncated": False},
            },
        },
    }
    diff_thread = _serve_one(diff_socket, diff_response, diff_holder)

    diff = LocalDaemonClient(diff_socket, timeout=1.0).diff(
        surface="beads",
        limit=7,
        cursor="14",
    )
    diff_thread.join(timeout=1)

    assert diff["records"] == []
    assert diff_holder["request"]["payload"] == {
        "type": "diff",
        "data": {
            "surface": "beads",
            "page": {"limit": 7, "cursor": "14"},
        },
    }


def test_missing_socket_raises_typed_unavailable(tmp_path: Path) -> None:
    with pytest.raises(LocalDaemonUnavailableError) as error:
        LocalDaemonClient(tmp_path / "missing.sock", timeout=0.01).health()

    assert error.value.fallback_reason == "daemon_not_running"


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
