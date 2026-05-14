"""Payload validation and protocol helpers for the local daemon client."""

from __future__ import annotations

import socket
from typing import Any, Protocol

from sase.daemon.errors import LocalDaemonRpcError, LocalDaemonTransportError


class LocalDaemonTransport(Protocol):
    """In-process transport seam for tests and non-socket embedders."""

    def request(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """Return one local daemon response envelope for ``envelope``."""


def selector_data(
    *,
    surface: str,
    project_id: str | None,
) -> dict[str, Any]:
    data: dict[str, Any] = {"surface": surface}
    if project_id:
        data["project_id"] = project_id
    return data


def read_exact(sock: socket.socket, size: int) -> bytes:
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


def payload_data(response: dict[str, Any], expected_type: str) -> dict[str, Any]:
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


def read_payload_data(
    response: dict[str, Any], expected_surface: str
) -> dict[str, Any]:
    data = payload_data(response, "read")
    if data.get("surface") != expected_surface:
        raise LocalDaemonTransportError(
            f"unexpected local daemon read surface for {expected_surface}",
            code="invalid_request",
            fallback_reason=None,
        )
    surface_data = data.get("data")
    if not isinstance(surface_data, dict):
        raise LocalDaemonTransportError(
            f"missing local daemon read data for {expected_surface}",
            code="invalid_request",
            fallback_reason=None,
        )
    return surface_data


def rpc_error(data: dict[str, Any]) -> LocalDaemonRpcError:
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


def raise_for_rpc_error(response: dict[str, Any]) -> None:
    response_payload = response.get("payload")
    if (
        isinstance(response_payload, dict)
        and response_payload.get("type") == "error"
        and isinstance(response_payload.get("data"), dict)
    ):
        raise rpc_error(response_payload["data"])
