"""Shared local-daemon write routing and fallback helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.daemon.client import (
    LocalDaemonClient,
    LocalDaemonError,
    LocalDaemonRpcError,
    LocalDaemonTransportError,
)
from sase.daemon.paths import daemon_disabled

FALLBACKABLE_WRITE_RPC_CODES = {
    "unsupported_capability",
    "unsupported_mutation",
    "unsupported_client_version",
    "payload_too_large",
    "host_adapter_required",
    "daemon_unavailable",
    "invalid_request",
}

CAPABILITY_BY_WRITE_SURFACE = {
    "agents.dismissed_identity": "agents.write",
    "agents.archive_bundle": "agents.write",
    "agents.archive_revived": "agents.write",
    "agents.archive_purged": "agents.write",
    "agents.artifact_associated": "agents.write",
    "agents.cleanup_result": "agents.write",
    "beads": "beads.write",
    "changespec.status": "changespecs.write",
    "changespec.field": "changespecs.write",
    "changespec.comments": "changespecs.write",
    "changespec.hooks": "changespecs.write",
    "changespec.hook_suffix": "changespecs.write",
    "changespec.mentors": "changespecs.write",
    "changespec.mentor_status": "changespecs.write",
    "changespec.lifecycle_name": "changespecs.write",
    "changespec.timestamps": "changespecs.write",
    "changespec.active_archive_moved": "changespecs.write",
    "contract": "writes.contract",
    "notifications.append": "notifications.write",
    "notifications.state_update": "notifications.write",
    "pending_actions.register": "notifications.write",
    "pending_actions.update": "notifications.write",
    "pending_actions.cleanup": "notifications.write",
    "workflow.action_response": "workflows.write",
    "workflow.hitl_request": "workflows.write",
    "workflow.step_transition": "workflows.write",
    "workflow.state": "workflows.write",
}


@dataclass(frozen=True)
class DaemonWriteResult[T]:
    """A daemon write outcome with optional direct-writer fallback metadata."""

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


def write_or_fallback[T](
    surface: str,
    *,
    daemon_writer: Callable[[LocalDaemonClient], T],
    direct_writer: Callable[[], T],
    args: Any | None = None,
    client: LocalDaemonClient | None = None,
    required_capability: str | None = None,
) -> DaemonWriteResult[T]:
    """Run a daemon write when supported, otherwise run the direct writer."""

    if daemon_disabled(args):
        return _fallback(
            surface,
            direct_writer,
            reason="daemon_disabled",
            message="daemon writes disabled by --no-daemon or SASE_NO_DAEMON",
        )

    capability = required_capability or CAPABILITY_BY_WRITE_SURFACE.get(surface)
    daemon_client = client or LocalDaemonClient()
    if capability:
        try:
            capabilities = _capability_set(daemon_client.capabilities())
        except LocalDaemonError as error:
            return _fallback_from_error(surface, direct_writer, error)
        if capability not in capabilities:
            return _fallback(
                surface,
                direct_writer,
                reason="unsupported_capability",
                message=f"local daemon does not advertise {capability}",
            )

    try:
        return DaemonWriteResult(
            value=daemon_writer(daemon_client),
            surface=surface,
            used_daemon=True,
        )
    except LocalDaemonError as error:
        if not is_fallbackable_daemon_write_error(error):
            raise
        return _fallback_from_error(surface, direct_writer, error)


def is_fallbackable_daemon_write_error(error: LocalDaemonError) -> bool:
    if isinstance(error, LocalDaemonTransportError):
        return (
            error.fallback_reason is not None
            or error.code in FALLBACKABLE_WRITE_RPC_CODES
        )
    if isinstance(error, LocalDaemonRpcError):
        return (
            error.fallback_reason is not None
            or error.code in FALLBACKABLE_WRITE_RPC_CODES
        )
    return False


def _capability_set(response: dict[str, Any]) -> set[str]:
    capabilities = response.get("capabilities")
    if not isinstance(capabilities, list):
        return set()
    return {item for item in capabilities if isinstance(item, str)}


def _fallback[T](
    surface: str,
    direct_writer: Callable[[], T],
    *,
    reason: str,
    message: str | None,
) -> DaemonWriteResult[T]:
    return DaemonWriteResult(
        value=direct_writer(),
        surface=surface,
        used_daemon=False,
        fallback_reason=reason,
        fallback_message=message,
    )


def _fallback_from_error[T](
    surface: str,
    direct_writer: Callable[[], T],
    error: LocalDaemonError,
) -> DaemonWriteResult[T]:
    if isinstance(error, LocalDaemonRpcError):
        return _fallback(
            surface,
            direct_writer,
            reason=error.fallback_reason or error.code,
            message=error.fallback_message or error.message,
        )
    if isinstance(error, LocalDaemonTransportError):
        return _fallback(
            surface,
            direct_writer,
            reason=error.fallback_reason or error.code,
            message=str(error),
        )
    return _fallback(
        surface,
        direct_writer,
        reason="daemon_error",
        message=str(error),
    )


__all__ = [
    "CAPABILITY_BY_WRITE_SURFACE",
    "FALLBACKABLE_WRITE_RPC_CODES",
    "DaemonWriteResult",
    "is_fallbackable_daemon_write_error",
    "write_or_fallback",
]
