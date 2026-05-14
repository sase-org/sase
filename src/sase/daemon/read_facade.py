"""Shared local-daemon read routing and fallback helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.daemon.client import (
    LocalDaemonClient,
    LocalDaemonError,
    LocalDaemonRpcError,
    LocalDaemonTransportError,
    daemon_disabled,
)

FALLBACKABLE_RPC_CODES = {
    "cursor_expired",
    "projection_degraded",
    "snapshot_expired",
    "unsupported_capability",
    "unsupported_client_version",
    "payload_too_large",
    "resource_not_found",
}

CAPABILITY_BY_READ_SURFACE = {
    "changespec_list": "changespecs.read",
    "changespec_search": "changespecs.read",
    "changespec_detail": "changespecs.read",
    "agent_active": "agents.read",
    "agent_recent": "agents.read",
    "agent_archive": "agents.read",
    "agent_search": "agents.read",
    "agent_detail": "agents.read",
    "notification_list": "notifications.read",
    "notification_detail": "notifications.read",
    "notification_counts": "notifications.read",
    "notification_pending_actions": "notifications.read",
    "bead_list": "beads.read",
    "bead_ready": "beads.read",
    "bead_blocked": "beads.read",
    "bead_show": "beads.read",
    "bead_stats": "beads.read",
    "xprompt_catalog": "catalogs.read",
    "editor_catalog": "catalogs.read",
    "snippet_catalog": "catalogs.read",
    "file_history": "catalogs.read",
}


@dataclass(frozen=True)
class DaemonReadResult[T]:
    """A daemon read outcome with optional debug fallback metadata."""

    value: T
    surface: str
    used_daemon: bool
    fallback_reason: str | None = None
    fallback_message: str | None = None

    def debug_json(self) -> dict[str, Any]:
        return {
            "daemon": {
                "surface": self.surface,
                "used": self.used_daemon,
                "fallback_reason": self.fallback_reason,
                "fallback_message": self.fallback_message,
            }
        }


def read_or_fallback[T](
    surface: str,
    *,
    daemon_loader: Callable[[LocalDaemonClient], T],
    direct_loader: Callable[[], T],
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
    required_capability: str | None = None,
) -> DaemonReadResult[T]:
    """Run a daemon read when supported, otherwise run the direct loader."""

    capability = required_capability or CAPABILITY_BY_READ_SURFACE.get(surface)
    if daemon_disabled(args):
        return _fallback(
            surface,
            direct_loader,
            reason="daemon_disabled",
            message="daemon reads disabled by --no-daemon or SASE_NO_DAEMON",
        )

    daemon_client = client or LocalDaemonClient()
    if capability:
        try:
            capabilities = _capability_set(daemon_client.capabilities())
        except LocalDaemonError as error:
            return _fallback_from_error(surface, direct_loader, error)
        if capability not in capabilities:
            return _fallback(
                surface,
                direct_loader,
                reason="unsupported_capability",
                message=f"local daemon does not advertise {capability}",
            )

    try:
        return DaemonReadResult(
            value=daemon_loader(daemon_client),
            surface=surface,
            used_daemon=True,
        )
    except LocalDaemonError as error:
        if not is_fallbackable_daemon_error(error):
            raise
        return _fallback_from_error(surface, direct_loader, error)


def is_fallbackable_daemon_error(error: LocalDaemonError) -> bool:
    if isinstance(error, LocalDaemonTransportError):
        return error.fallback_reason is not None or error.code in FALLBACKABLE_RPC_CODES
    if isinstance(error, LocalDaemonRpcError):
        return error.fallback_reason is not None or error.code in FALLBACKABLE_RPC_CODES
    return False


def _capability_set(response: dict[str, Any]) -> set[str]:
    capabilities = response.get("capabilities")
    if not isinstance(capabilities, list):
        return set()
    return {item for item in capabilities if isinstance(item, str)}


def _fallback[T](
    surface: str,
    direct_loader: Callable[[], T],
    *,
    reason: str,
    message: str | None,
) -> DaemonReadResult[T]:
    return DaemonReadResult(
        value=direct_loader(),
        surface=surface,
        used_daemon=False,
        fallback_reason=reason,
        fallback_message=message,
    )


def _fallback_from_error[T](
    surface: str,
    direct_loader: Callable[[], T],
    error: LocalDaemonError,
) -> DaemonReadResult[T]:
    if isinstance(error, LocalDaemonRpcError):
        return _fallback(
            surface,
            direct_loader,
            reason=error.fallback_reason or error.code,
            message=error.fallback_message or error.message,
        )
    if isinstance(error, LocalDaemonTransportError):
        return _fallback(
            surface,
            direct_loader,
            reason=error.fallback_reason or error.code,
            message=str(error),
        )
    return _fallback(
        surface,
        direct_loader,
        reason="daemon_error",
        message=str(error),
    )


__all__ = [
    "CAPABILITY_BY_READ_SURFACE",
    "FALLBACKABLE_RPC_CODES",
    "DaemonReadResult",
    "is_fallbackable_daemon_error",
    "read_or_fallback",
]
