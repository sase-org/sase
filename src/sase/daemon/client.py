"""Thin Unix-socket client for the local SASE daemon framed JSON RPC."""

from __future__ import annotations

import json
import socket
import struct
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sase.daemon.constants import (
    LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
    LOCAL_DAEMON_MAX_PAYLOAD_BYTES,
    LOCAL_DAEMON_SCHEMA_VERSION,
)
from sase.daemon.compatibility import (
    client_metadata,
    validate_negotiated_compatibility,
    validate_response_envelope,
)
from sase.daemon.errors import (
    LocalDaemonError,
    LocalDaemonRpcError,
    LocalDaemonTransportError,
    LocalDaemonUnavailableError,
)
from sase.daemon.paths import daemon_disabled, default_socket_path
from sase.daemon.protocol import (
    LocalDaemonTransport,
    payload_data,
    raise_for_rpc_error,
    read_exact,
    rpc_error,
    selector_data,
)
from sase.daemon.read_requests import LocalDaemonReadMixin
from sase.host.wire import (
    HostRequestEnvelopeWire,
    HostResponseEnvelopeWire,
    host_response_from_dict,
    host_wire_to_json_dict,
)

__all__ = [
    "LOCAL_DAEMON_DEFAULT_PAGE_LIMIT",
    "LOCAL_DAEMON_MAX_PAYLOAD_BYTES",
    "LOCAL_DAEMON_SCHEMA_VERSION",
    "LocalDaemonClient",
    "LocalDaemonError",
    "LocalDaemonRpcError",
    "LocalDaemonTransport",
    "LocalDaemonTransportError",
    "LocalDaemonUnavailableError",
    "daemon_disabled",
    "default_socket_path",
    "diff",
    "health",
    "read",
    "rebuild",
    "verify",
    "write",
]


class LocalDaemonClient(LocalDaemonReadMixin):
    """Small synchronous client for one-request local daemon RPC calls."""

    def __init__(
        self,
        socket_path: str | Path | None = None,
        *,
        timeout: float = 1.0,
        client_name: str = "sase-cli",
        client_version: str = "0.1.1",
        transport: LocalDaemonTransport | None = None,
    ) -> None:
        self.socket_path = (
            Path(socket_path) if socket_path is not None else default_socket_path()
        )
        self.timeout = timeout
        self.client_name = client_name
        self.client_version = client_version
        self.transport = transport

    def request(
        self,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        envelope = {
            "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
            "request_id": request_id or f"req_{uuid.uuid4().hex}",
            "client": client_metadata(
                name=self.client_name,
                version=self.client_version,
            ),
            "payload": payload,
        }
        response = self._send_envelope(envelope)
        validate_response_envelope(response)
        response_payload = response.get("payload")
        if (
            isinstance(response_payload, dict)
            and response_payload.get("type") == "error"
            and isinstance(response_payload.get("data"), dict)
        ):
            raise rpc_error(response_payload["data"])
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
        data = payload_data(response, "health")
        validate_negotiated_compatibility(data)
        return data

    def capabilities(self) -> dict[str, Any]:
        response = self.request({"type": "capabilities"})
        data = payload_data(response, "capabilities")
        validate_negotiated_compatibility(data)
        return data

    def batch(self, requests: list[dict[str, Any]]) -> dict[str, Any]:
        response = self.request({"type": "batch", "data": {"requests": requests}})
        return payload_data(response, "batch")

    def write(
        self,
        surface: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        response = self.request({"type": "write", "data": {"surface": surface, **data}})
        return payload_data(response, "write")

    def indexing_status(
        self,
        *,
        surface: str = "all",
        project_id: str | None = None,
    ) -> dict[str, Any]:
        data = selector_data(surface=surface, project_id=project_id)
        response = self.request({"type": "indexing_status", "data": data})
        return payload_data(response, "indexing_status")

    def scheduler_submit(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self.request({"type": "scheduler_submit", "data": data})
        return payload_data(response, "scheduler_submit")

    def scheduler_status(self, *, project_id: str, batch_id: str) -> dict[str, Any]:
        response = self.request(
            {
                "type": "scheduler_status",
                "data": {
                    "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
                    "project_id": project_id,
                    "batch_id": batch_id,
                },
            }
        )
        return payload_data(response, "scheduler_status")

    def scheduler_cancel(self, data: dict[str, Any]) -> dict[str, Any]:
        response = self.request({"type": "scheduler_cancel", "data": data})
        return payload_data(response, "scheduler_cancel")

    def host_call(
        self,
        envelope: HostRequestEnvelopeWire | dict[str, Any],
    ) -> HostResponseEnvelopeWire:
        response = self.request(
            {
                "type": "host_call",
                "data": (
                    host_wire_to_json_dict(envelope)
                    if isinstance(envelope, HostRequestEnvelopeWire)
                    else envelope
                ),
            }
        )
        return host_response_from_dict(payload_data(response, "host_call"))

    def rebuild(
        self,
        *,
        storage_reset_only: bool = False,
        surface: str = "all",
        project_id: str | None = None,
    ) -> dict[str, Any]:
        data = selector_data(surface=surface, project_id=project_id)
        data["storage_reset_only"] = storage_reset_only
        response = self.request(
            {
                "type": "rebuild",
                "data": data,
            }
        )
        return payload_data(response, "rebuild")

    def checkpoint(self, *, mode: str = "passive") -> dict[str, Any]:
        response = self.request(
            {
                "type": "projection_checkpoint",
                "data": {"mode": mode},
            }
        )
        return payload_data(response, "projection_checkpoint")

    def backup(self, *, path: str | None = None) -> dict[str, Any]:
        data: dict[str, Any] = {}
        if path is not None:
            data["path"] = path
        response = self.request({"type": "projection_backup", "data": data})
        return payload_data(response, "projection_backup")

    def list_backups(self, *, limit: int = 20) -> dict[str, Any]:
        response = self.request(
            {"type": "projection_list_backups", "data": {"limit": limit}}
        )
        return payload_data(response, "projection_list_backups")

    def restore(
        self,
        *,
        path: str,
        live_recovery: bool = False,
        allow_host_mismatch: bool = False,
    ) -> dict[str, Any]:
        response = self.request(
            {
                "type": "projection_restore",
                "data": {
                    "path": path,
                    "live_recovery": live_recovery,
                    "allow_host_mismatch": allow_host_mismatch,
                },
            }
        )
        return payload_data(response, "projection_restore")

    def verify(
        self,
        *,
        surface: str = "all",
        project_id: str | None = None,
    ) -> dict[str, Any]:
        data = selector_data(surface=surface, project_id=project_id)
        response = self.request({"type": "verify", "data": data})
        return payload_data(response, "verify")

    def diff(
        self,
        *,
        surface: str = "all",
        project_id: str | None = None,
        limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        data = selector_data(surface=surface, project_id=project_id)
        data["page"] = {"limit": limit, "cursor": cursor}
        response = self.request({"type": "diff", "data": data})
        return payload_data(response, "diff")

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
            yield payload_data(response, "events")

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
        if self.transport is not None:
            return self.transport.request(envelope)
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
            "client": client_metadata(
                name=self.client_name,
                version=self.client_version,
            ),
            "payload": payload,
        }
        with self._connected_socket(envelope) as sock:
            while True:
                response = self._read_response(sock)
                validate_response_envelope(response)
                raise_for_rpc_error(response)
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
            raise LocalDaemonUnavailableError(
                f"timed out talking to local daemon at {self.socket_path}",
                fallback_reason="daemon_not_running",
                retryable=True,
            ) from error
        except OSError as error:
            if sock is not None:
                sock.close()
            raise LocalDaemonUnavailableError(
                f"local daemon socket unavailable at {self.socket_path}: {error}",
                fallback_reason="daemon_not_running",
            ) from error

    def _read_response(self, sock: socket.socket) -> dict[str, Any]:
        try:
            response_len = read_exact(sock, 4)
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
            response_payload = read_exact(sock, expected)
        except TimeoutError as error:
            raise LocalDaemonUnavailableError(
                f"timed out talking to local daemon at {self.socket_path}",
                fallback_reason="daemon_not_running",
                retryable=True,
            ) from error
        except OSError as error:
            raise LocalDaemonUnavailableError(
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


def health(
    *, socket_path: str | Path | None = None, timeout: float = 1.0
) -> dict[str, Any]:
    return LocalDaemonClient(socket_path, timeout=timeout).health()


def rebuild(
    *,
    socket_path: str | Path | None = None,
    timeout: float = 5.0,
    storage_reset_only: bool = False,
    surface: str = "all",
    project_id: str | None = None,
) -> dict[str, Any]:
    return LocalDaemonClient(socket_path, timeout=timeout).rebuild(
        storage_reset_only=storage_reset_only,
        surface=surface,
        project_id=project_id,
    )


def verify(
    *,
    socket_path: str | Path | None = None,
    timeout: float = 5.0,
    surface: str = "all",
    project_id: str | None = None,
) -> dict[str, Any]:
    return LocalDaemonClient(socket_path, timeout=timeout).verify(
        surface=surface,
        project_id=project_id,
    )


def diff(
    *,
    socket_path: str | Path | None = None,
    timeout: float = 5.0,
    surface: str = "all",
    project_id: str | None = None,
    limit: int = LOCAL_DAEMON_DEFAULT_PAGE_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    return LocalDaemonClient(socket_path, timeout=timeout).diff(
        surface=surface,
        project_id=project_id,
        limit=limit,
        cursor=cursor,
    )


def read(
    surface: str,
    data: dict[str, Any] | None = None,
    *,
    socket_path: str | Path | None = None,
    timeout: float = 1.0,
) -> dict[str, Any]:
    return LocalDaemonClient(socket_path, timeout=timeout).read(surface, data)


def write(
    surface: str,
    data: dict[str, Any],
    *,
    socket_path: str | Path | None = None,
    timeout: float = 1.0,
) -> dict[str, Any]:
    return LocalDaemonClient(socket_path, timeout=timeout).write(surface, data)
