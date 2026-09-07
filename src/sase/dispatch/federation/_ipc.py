"""Blocking length-prefixed JSON IPC client for the local federation worker."""

from __future__ import annotations

import json
import socket
import struct
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._constants import FEDERATION_IPC_SCHEMA_VERSION, FEDERATION_MAX_FRAME_BYTES
from ._errors import FederationWorkerResponseError, FederationWorkerUnavailable
from ._settings import resolve_timeout


@dataclass(frozen=True)
class FederationIpcClient:
    """Blocking length-prefixed JSON IPC client."""

    socket_path: Path
    max_frame_bytes: int = FEDERATION_MAX_FRAME_BYTES

    def request(
        self,
        operation: Mapping[str, Any],
        *,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        timeout = resolve_timeout(timeout_seconds, 5.0)
        request_id = f"py-{uuid.uuid4().hex}"
        deadline_unix_ms = int((time.time() + timeout) * 1000)
        envelope = {
            "schema_version": FEDERATION_IPC_SCHEMA_VERSION,
            "request_id": request_id,
            "deadline_unix_ms": deadline_unix_ms,
            "operation": dict(operation),
        }
        try:
            payload = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise FederationWorkerUnavailable(
                "IPC request is not JSON serializable"
            ) from exc
        if len(payload) > self.max_frame_bytes:
            raise FederationWorkerUnavailable("IPC request exceeds frame limit")

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(str(self.socket_path))
                sock.sendall(struct.pack(">I", len(payload)) + payload)
                response = self._read_frame(sock)
        except OSError as exc:
            raise FederationWorkerUnavailable(
                f"federation worker socket is unavailable: {self.socket_path}"
            ) from exc
        try:
            decoded = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FederationWorkerUnavailable(
                "federation worker returned invalid JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise FederationWorkerUnavailable(
                "federation worker returned non-object JSON"
            )
        if decoded.get("schema_version") != FEDERATION_IPC_SCHEMA_VERSION:
            raise FederationWorkerUnavailable(
                "federation worker returned an unsupported schema version"
            )
        if decoded.get("request_id") != request_id:
            raise FederationWorkerUnavailable(
                "federation worker returned a mismatched request_id"
            )
        if not decoded.get("ok"):
            error = decoded.get("error")
            if not isinstance(error, Mapping):
                error = {"message": "federation worker returned an unknown error"}
            raise FederationWorkerResponseError(error)
        result = decoded.get("result")
        if not isinstance(result, dict):
            raise FederationWorkerUnavailable(
                "federation worker returned no result object"
            )
        return result

    def _read_frame(self, sock: socket.socket) -> bytes:
        header = _recv_exact(sock, 4)
        length = struct.unpack(">I", header)[0]
        if length == 0:
            raise FederationWorkerUnavailable("IPC response frame was empty")
        if length > self.max_frame_bytes:
            raise FederationWorkerUnavailable("IPC response exceeds frame limit")
        return _recv_exact(sock, length)


def _recv_exact(sock: socket.socket, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise FederationWorkerUnavailable("IPC socket closed mid-frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
