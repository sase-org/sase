"""Federation IPC and supervisor-resilience tests.

Split from ``tests.test_dispatch_federation``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

import pytest

import sase.dispatch.federation as federation


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


class _FakeIpcSocket:
    """Controllable stand-in for a connected IPC socket."""

    def __init__(
        self,
        *,
        recv_error: Exception | None = None,
        connect_error: Exception | None = None,
    ) -> None:
        self.recv_error = recv_error
        self.connect_error = connect_error
        self.timeout_seconds: float | None = None
        self.sent: bytes = b""

    def __enter__(self) -> _FakeIpcSocket:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def settimeout(self, timeout: float | None) -> None:
        self.timeout_seconds = timeout

    def connect(self, _address: object) -> None:
        if self.connect_error is not None:
            raise self.connect_error

    def sendall(self, payload: bytes) -> None:
        self.sent += payload

    def recv(self, _count: int) -> bytes:
        if self.recv_error is not None:
            raise self.recv_error
        raise AssertionError("unexpected recv without a programmed response")


def _patch_ipc_socket(monkeypatch: pytest.MonkeyPatch, fake: _FakeIpcSocket) -> None:
    def factory(*_args: object, **_kwargs: object) -> _FakeIpcSocket:
        return fake

    monkeypatch.setattr(federation._ipc.socket, "socket", factory)


def test_ipc_recv_timeout_is_worker_timeout_with_grace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeIpcSocket(recv_error=TimeoutError("timed out"))
    _patch_ipc_socket(monkeypatch, fake)

    before = time.time()
    with pytest.raises(federation.FederationWorkerTimeout):
        federation.FederationIpcClient(tmp_path / "worker.sock").request(
            {"op": "health"}, timeout_seconds=1.0
        )
    after = time.time()

    # The socket waits past the worker deadline for the bounded partial
    # response, while the envelope deadline itself does not move.
    assert fake.timeout_seconds == pytest.approx(2.0)
    envelope = json.loads(fake.sent[4:].decode("utf-8"))
    assert envelope["deadline_unix_ms"] == pytest.approx((before + 1.0) * 1000, abs=50)
    assert envelope["deadline_unix_ms"] <= after * 1000 + 1000


def test_ipc_refused_socket_is_plain_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeIpcSocket(connect_error=ConnectionRefusedError("refused"))
    _patch_ipc_socket(monkeypatch, fake)

    with pytest.raises(federation.FederationWorkerUnavailable) as exc_info:
        federation.FederationIpcClient(tmp_path / "worker.sock").request(
            {"op": "health"}, timeout_seconds=1.0
        )
    assert type(exc_info.value) is federation.FederationWorkerUnavailable


def test_supervisor_does_not_respawn_or_resend_on_worker_timeout(
    tmp_path: Path,
) -> None:
    sends: list[dict[str, Any]] = []
    spawns: list[list[str]] = []

    class Proc:
        def poll(self) -> int | None:
            return None

    class Client:
        def __init__(self, _path: Path, _max_frame_bytes: int) -> None:
            pass

        def request(
            self, operation: Mapping[str, Any], *, timeout_seconds: float
        ) -> dict[str, Any]:
            sends.append(dict(operation))
            if operation.get("op") == "summary":
                raise federation.FederationWorkerTimeout("slow worker")
            if operation.get("op") == "replace_config":
                return {"schema_version": 1, "configured_hosts": 0}
            return {"schema_version": 1, "status": "ok"}

    def popen(command: list[str], **_kwargs: object) -> Proc:
        spawns.append(command)
        raise AssertionError("slow worker must not trigger a respawn")

    config = federation.FederationConfig(
        worker=federation.FederationWorkerSettings(
            command=("worker-bin",),
            sase_home=tmp_path,
            socket_path=tmp_path / "worker.sock",
        ),
        hosts=(),
    )
    supervisor = federation.FederationWorkerSupervisor(
        config,
        client_factory=cast(federation.IpcClientFactory, Client),
        popen=cast(federation.PopenFactory, popen),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(federation.FederationWorkerTimeout):
        supervisor.request({"op": "summary"}, timeout_seconds=1)

    assert spawns == []
    assert [call["op"] for call in sends] == ["health", "replace_config", "summary"]


def test_supervisor_still_respawns_and_retries_refused_connection(
    tmp_path: Path,
) -> None:
    sends: list[dict[str, Any]] = []
    spawns = 0
    state = {"started": False, "summaries": 0}

    class Proc:
        def poll(self) -> int | None:
            return None

    class Client:
        def __init__(self, _path: Path, _max_frame_bytes: int) -> None:
            pass

        def request(
            self, operation: Mapping[str, Any], *, timeout_seconds: float
        ) -> dict[str, Any]:
            sends.append(dict(operation))
            if operation.get("op") == "health":
                if not state["started"]:
                    raise federation.FederationWorkerUnavailable("not ready")
                return {"schema_version": 1, "status": "ok"}
            if operation.get("op") == "replace_config":
                return {"schema_version": 1, "configured_hosts": 0}
            if operation.get("op") == "summary":
                state["summaries"] += 1
                if state["summaries"] == 1:
                    raise federation.FederationWorkerUnavailable("refused")
                return {"schema_version": 1, "hosts": []}
            raise AssertionError(f"unexpected operation: {operation}")

    def popen(command: list[str], **_kwargs: object) -> Proc:
        nonlocal spawns
        spawns += 1
        state["started"] = True
        return Proc()

    config = federation.FederationConfig(
        worker=federation.FederationWorkerSettings(
            command=("worker-bin",),
            sase_home=tmp_path,
            socket_path=tmp_path / "worker.sock",
        ),
        hosts=(),
    )
    supervisor = federation.FederationWorkerSupervisor(
        config,
        client_factory=cast(federation.IpcClientFactory, Client),
        popen=cast(federation.PopenFactory, popen),
        sleep=lambda _seconds: None,
    )

    assert supervisor.request({"op": "summary"}, timeout_seconds=1)["hosts"] == []
    assert spawns == 2
    assert [call["op"] for call in sends].count("summary") == 2


def test_supervisor_slow_health_probe_does_not_spawn_worker(
    tmp_path: Path,
) -> None:
    sends: list[dict[str, Any]] = []

    class Client:
        def __init__(self, _path: Path, _max_frame_bytes: int) -> None:
            pass

        def request(
            self, operation: Mapping[str, Any], *, timeout_seconds: float
        ) -> dict[str, Any]:
            sends.append(dict(operation))
            if operation.get("op") == "health":
                raise federation.FederationWorkerTimeout("slow probe")
            if operation.get("op") == "replace_config":
                return {"schema_version": 1, "configured_hosts": 0}
            return {"schema_version": 1, "hosts": []}

    def popen(command: list[str], **_kwargs: object) -> object:
        raise AssertionError("slow health probe must not spawn a worker")

    config = federation.FederationConfig(
        worker=federation.FederationWorkerSettings(
            command=("worker-bin",),
            sase_home=tmp_path,
            socket_path=tmp_path / "worker.sock",
        ),
        hosts=(),
    )
    supervisor = federation.FederationWorkerSupervisor(
        config,
        client_factory=cast(federation.IpcClientFactory, Client),
        popen=cast(federation.PopenFactory, popen),
        sleep=lambda _seconds: None,
    )

    assert supervisor.request({"op": "summary"}, timeout_seconds=1)["hosts"] == []
    assert [call["op"] for call in sends] == [
        "health",
        "replace_config",
        "summary",
    ]
