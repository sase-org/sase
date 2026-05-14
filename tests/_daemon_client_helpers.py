"""Shared helpers for local daemon client tests."""

from __future__ import annotations

import json
import socket
import struct
import threading
from pathlib import Path
from typing import Any


class CaptureTransport:
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


def serve_one(
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


def serve_stream(
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
