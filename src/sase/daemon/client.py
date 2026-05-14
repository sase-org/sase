"""Thin Unix-socket client for the local SASE daemon framed JSON RPC."""

from __future__ import annotations

import json
import os
import socket
import struct
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOCAL_DAEMON_SCHEMA_VERSION = 1
LOCAL_DAEMON_MAX_PAYLOAD_BYTES = 1_048_576
LOCAL_DAEMON_DEFAULT_PAGE_LIMIT = 100


class LocalDaemonError(RuntimeError):
    """Base class for local daemon client failures."""


@dataclass(frozen=True)
class LocalDaemonTransportError(LocalDaemonError):
    """Transport-level failure with daemon fallback metadata."""

    message: str
    code: str = "daemon_unavailable"
    fallback_reason: str | None = "daemon_not_running"
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class LocalDaemonRpcError(LocalDaemonError):
    """Typed error returned by the local daemon RPC protocol."""

    code: str
    message: str
    retryable: bool
    target: str | None
    details: dict[str, Any] | None
    fallback_reason: str | None
    fallback_message: str | None

    def __str__(self) -> str:
        return self.message


class LocalDaemonClient:
    """Small synchronous client for one-request local daemon RPC calls."""

    def __init__(
        self,
        socket_path: str | Path | None = None,
        *,
        timeout: float = 1.0,
        client_name: str = "sase-cli",
        client_version: str = "0.1.1",
    ) -> None:
        self.socket_path = (
            Path(socket_path) if socket_path is not None else default_socket_path()
        )
        self.timeout = timeout
        self.client_name = client_name
        self.client_version = client_version

    def request(
        self,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        envelope = {
            "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
            "request_id": request_id or f"req_{uuid.uuid4().hex}",
            "client": {
                "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
                "name": self.client_name,
                "version": self.client_version,
            },
            "payload": payload,
        }
        response = self._send_envelope(envelope)
        response_payload = response.get("payload")
        if (
            isinstance(response_payload, dict)
            and response_payload.get("type") == "error"
            and isinstance(response_payload.get("data"), dict)
        ):
            raise _rpc_error(response_payload["data"])
        return response

    def health(
        self, *, include_capabilities: bool = True, timeout: float | None = None
    ) -> dict[str, Any]:
        response = self._request_with_optional_timeout(
            {
                "type": "health",
                "data": {"include_capabilities": include_capabilities},
            },
            timeout=timeout,
        )
        return _payload_data(response, "health")

    def capabilities(self) -> dict[str, Any]:
        response = self.request({"type": "capabilities"})
        return _payload_data(response, "capabilities")

    def batch(self, requests: list[dict[str, Any]]) -> dict[str, Any]:
        response = self.request({"type": "batch", "data": {"requests": requests}})
        return _payload_data(response, "batch")

    def events(
        self,
        *,
        after_event_id: str | None = None,
        since_event_id: str | None = None,
        snapshot_id: str | None = None,
        collections: list[str] | None = None,
        max_events: int = 1,
    ) -> Iterator[dict[str, Any]]:
        """Iterate local daemon event batches until the stream ends or errors."""

        event_id = after_event_id if after_event_id is not None else since_event_id
        data: dict[str, Any] = {
            "since_event_id": event_id,
            "snapshot_id": snapshot_id,
            "max_events": max_events,
        }
        if collections:
            data["collections"] = collections
        for response in self._stream_payload({"type": "events", "data": data}):
            yield _payload_data(response, "events")

    def read_events(
        self,
        limit: int,
        *,
        after_event_id: str | None = None,
        since_event_id: str | None = None,
        snapshot_id: str | None = None,
        collections: list[str] | None = None,
        max_events: int = 1,
    ) -> list[dict[str, Any]]:
        """Read a bounded number of local daemon event batches."""

        if limit < 0:
            raise ValueError("event batch read limit must be non-negative")
        batches: list[dict[str, Any]] = []
        for batch in self.events(
            after_event_id=after_event_id,
            since_event_id=since_event_id,
            snapshot_id=snapshot_id,
            collections=collections,
            max_events=max_events,
        ):
            batches.append(batch)
            if len(batches) >= limit:
                break
        return batches

    def _send_envelope(self, envelope: dict[str, Any]) -> dict[str, Any]:
        with self._connected_socket(envelope) as sock:
            return self._read_response(sock)

    def _request_with_optional_timeout(
        self, payload: dict[str, Any], *, timeout: float | None
    ) -> dict[str, Any]:
        if timeout is None:
            return self.request(payload)
        original_timeout = self.timeout
        self.timeout = timeout
        try:
            return self.request(payload)
        finally:
            self.timeout = original_timeout

    def _stream_payload(self, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        envelope = {
            "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
            "request_id": f"req_{uuid.uuid4().hex}",
            "client": {
                "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
                "name": self.client_name,
                "version": self.client_version,
            },
            "payload": payload,
        }
        with self._connected_socket(envelope) as sock:
            while True:
                response = self._read_response(sock)
                _raise_for_rpc_error(response)
                yield response

    def _connected_socket(self, envelope: dict[str, Any]) -> socket.socket:
        payload = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
        if len(payload) > LOCAL_DAEMON_MAX_PAYLOAD_BYTES:
            raise LocalDaemonTransportError(
                (
                    f"local daemon request is {len(payload)} bytes; "
                    f"maximum is {LOCAL_DAEMON_MAX_PAYLOAD_BYTES}"
                ),
                code="payload_too_large",
                fallback_reason=None,
            )
        frame = struct.pack(">I", len(payload)) + payload
        sock: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect(str(self.socket_path))
            sock.sendall(frame)
            return sock
        except TimeoutError as error:
            if sock is not None:
                sock.close()
            raise LocalDaemonTransportError(
                f"timed out talking to local daemon at {self.socket_path}",
                fallback_reason="daemon_not_running",
                retryable=True,
            ) from error
        except OSError as error:
            if sock is not None:
                sock.close()
            raise LocalDaemonTransportError(
                f"local daemon socket unavailable at {self.socket_path}: {error}",
                fallback_reason="daemon_not_running",
            ) from error

    def _read_response(self, sock: socket.socket) -> dict[str, Any]:
        try:
            response_len = _read_exact(sock, 4)
            expected = struct.unpack(">I", response_len)[0]
            if expected > LOCAL_DAEMON_MAX_PAYLOAD_BYTES:
                raise LocalDaemonTransportError(
                    (
                        f"local daemon response is {expected} bytes; "
                        f"maximum is {LOCAL_DAEMON_MAX_PAYLOAD_BYTES}"
                    ),
                    code="payload_too_large",
                    fallback_reason=None,
                )
            response_payload = _read_exact(sock, expected)
        except TimeoutError as error:
            raise LocalDaemonTransportError(
                f"timed out talking to local daemon at {self.socket_path}",
                fallback_reason="daemon_not_running",
                retryable=True,
            ) from error
        except OSError as error:
            raise LocalDaemonTransportError(
                f"local daemon socket read failed at {self.socket_path}: {error}",
                fallback_reason="daemon_not_running",
                retryable=True,
            ) from error

        try:
            response = json.loads(response_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LocalDaemonTransportError(
                f"invalid local daemon response JSON: {error}",
                code="invalid_request",
                fallback_reason=None,
            ) from error
        if not isinstance(response, dict):
            raise LocalDaemonTransportError(
                "invalid local daemon response envelope",
                code="invalid_request",
                fallback_reason=None,
            )
        return response


def default_socket_path(
    *,
    sase_home: str | Path | None = None,
    host_identity: str | None = None,
) -> Path:
    home = _default_sase_home() if sase_home is None else Path(sase_home)
    host = _sanitize_host_identity(
        host_identity if host_identity is not None else os.environ.get("HOSTNAME")
    )
    return home / "run" / host / "sase-daemon.sock"


def _default_sase_home() -> Path:
    if value := os.environ.get("SASE_HOME"):
        return Path(value)
    if value := os.environ.get("HOME"):
        return Path(value) / ".sase"
    return Path(".sase")


def _sanitize_host_identity(value: str | None) -> str:
    if value is None or not value.strip():
        return "sase-host"
    sanitized = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in ".-_") else "-"
        for ch in value.strip()
    ).strip("-")
    return sanitized or "sase-host"


def _read_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise LocalDaemonTransportError(
                "local daemon socket closed before a complete frame was read",
                code="invalid_request",
                fallback_reason=None,
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _payload_data(response: dict[str, Any], expected_type: str) -> dict[str, Any]:
    payload = response.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != expected_type:
        raise LocalDaemonTransportError(
            f"unexpected local daemon response payload for {expected_type}",
            code="invalid_request",
            fallback_reason=None,
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise LocalDaemonTransportError(
            f"missing local daemon response data for {expected_type}",
            code="invalid_request",
            fallback_reason=None,
        )
    return data


def _rpc_error(data: dict[str, Any]) -> LocalDaemonRpcError:
    fallback_raw = data.get("fallback")
    fallback: dict[str, Any] = fallback_raw if isinstance(fallback_raw, dict) else {}
    details = data.get("details") if isinstance(data.get("details"), dict) else None
    return LocalDaemonRpcError(
        code=str(data.get("code", "internal")),
        message=str(data.get("message", "local daemon RPC failed")),
        retryable=bool(data.get("retryable", False)),
        target=data.get("target") if isinstance(data.get("target"), str) else None,
        details=details,
        fallback_reason=(
            fallback.get("reason") if isinstance(fallback.get("reason"), str) else None
        ),
        fallback_message=(
            fallback.get("message")
            if isinstance(fallback.get("message"), str)
            else None
        ),
    )


def _raise_for_rpc_error(response: dict[str, Any]) -> None:
    response_payload = response.get("payload")
    if (
        isinstance(response_payload, dict)
        and response_payload.get("type") == "error"
        and isinstance(response_payload.get("data"), dict)
    ):
        raise _rpc_error(response_payload["data"])
