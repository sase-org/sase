"""Shared local-daemon read routing and fallback helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

from sase.daemon.client import (
    LocalDaemonClient,
    LocalDaemonError,
    LocalDaemonRpcError,
    LocalDaemonTransportError,
)
from sase.daemon.read_config import (
    daemon_fallback_diagnostics_enabled,
    daemon_read_disable_reason,
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
    "ace_changespec_list": "changespecs.read",
    "ace_changespec_search": "changespecs.read",
    "ace_changespec_detail": "changespecs.read",
    "agent_active": "agents.read",
    "agent_recent": "agents.read",
    "agent_archive": "agents.read",
    "agent_search": "agents.read",
    "agent_detail": "agents.read",
    "ace_agent_active": "agents.read",
    "ace_agent_recent": "agents.read",
    "ace_agent_archive": "agents.read",
    "ace_agent_search": "agents.read",
    "ace_agent_detail": "agents.read",
    "ace_archive": "agents.read",
    "ace_search": "agents.read",
    "ace_artifact_detail": "agents.read",
    "notification_list": "notifications.read",
    "notification_detail": "notifications.read",
    "notification_counts": "notifications.read",
    "notification_pending_actions": "notifications.read",
    "ace_notification_list": "notifications.read",
    "ace_notification_detail": "notifications.read",
    "ace_notification_counts": "notifications.read",
    "ace_notification_pending_actions": "notifications.read",
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

CAPABILITY_PROBE_TIMEOUT_SECONDS = 0.05


@dataclass
class _DaemonReadSession:
    """One process/client-local daemon read routing session."""

    capabilities: set[str] | None = None
    circuit_open: bool = False
    circuit_reason: str | None = None
    circuit_message: str | None = None
    circuit_surface: str | None = None
    capability_attempts: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def open_circuit(self, surface: str, error: LocalDaemonError) -> None:
        self.circuit_open = True
        self.circuit_reason = _error_reason(error)
        self.circuit_message = _error_message(error)
        self.circuit_surface = surface
        self.diagnostics = {
            "opened_by_surface": surface,
            "opened_by_reason": self.circuit_reason,
            "opened_by_message": self.circuit_message,
        }

    def diagnostic_json(self) -> dict[str, Any]:
        return {
            "circuit_open": self.circuit_open,
            "circuit_reason": self.circuit_reason,
            "circuit_message": self.circuit_message,
            "circuit_surface": self.circuit_surface,
            "capabilities_cached": self.capabilities is not None,
            "capability_attempts": self.capability_attempts,
            "capability_probe_timeout_seconds": CAPABILITY_PROBE_TIMEOUT_SECONDS,
            **self.diagnostics,
        }


_PROCESS_READ_SESSION = _DaemonReadSession()
_CLIENT_READ_SESSIONS: WeakKeyDictionary[LocalDaemonClient, _DaemonReadSession] = (
    WeakKeyDictionary()
)


@dataclass(frozen=True)
class DaemonReadResult[T]:
    """A daemon read outcome with optional debug fallback metadata."""

    value: T
    surface: str
    used_daemon: bool
    fallback_reason: str | None = None
    fallback_message: str | None = None
    fallback_diagnostics: dict[str, Any] | None = None

    def debug_json(self) -> dict[str, Any]:
        diagnostics_enabled = daemon_fallback_diagnostics_enabled()
        daemon: dict[str, Any] = {
            "daemon": {
                "surface": self.surface,
                "used": self.used_daemon,
                "fallback_reason": self.fallback_reason,
                "fallback_message": self.fallback_message,
                "fallback_diagnostics_enabled": diagnostics_enabled,
            }
        }
        if diagnostics_enabled and self.fallback_diagnostics is not None:
            daemon["daemon"]["fallback_diagnostics"] = self.fallback_diagnostics
        return daemon


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
    read_session = _read_session_for_client(client)
    disable_reason = daemon_read_disable_reason(surface, args=args)
    if disable_reason is not None:
        return _fallback(
            surface,
            direct_loader,
            reason=disable_reason.reason,
            message=disable_reason.message,
        )

    if read_session.circuit_open:
        return _fallback(
            surface,
            direct_loader,
            reason="daemon_circuit_open",
            message=read_session.circuit_message,
            diagnostics=read_session.diagnostic_json(),
        )

    daemon_client = client or LocalDaemonClient()
    if capability:
        try:
            capabilities = _cached_capability_set(daemon_client, read_session)
        except LocalDaemonError as error:
            _maybe_open_circuit(read_session, surface, error)
            return _fallback_from_error(
                surface,
                direct_loader,
                error,
                diagnostics=read_session.diagnostic_json(),
            )
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
        _maybe_open_circuit(read_session, surface, error)
        return _fallback_from_error(
            surface,
            direct_loader,
            error,
            diagnostics=read_session.diagnostic_json(),
        )


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


def _cached_capability_set(
    client: LocalDaemonClient,
    session: _DaemonReadSession,
) -> set[str]:
    if session.capabilities is not None:
        return session.capabilities
    session.capability_attempts += 1
    response = client.capabilities(timeout=CAPABILITY_PROBE_TIMEOUT_SECONDS)
    session.capabilities = _capability_set(response)
    return session.capabilities


def _read_session_for_client(
    client: LocalDaemonClient | None,
) -> _DaemonReadSession:
    if client is None:
        return _PROCESS_READ_SESSION
    try:
        return _CLIENT_READ_SESSIONS.setdefault(client, _DaemonReadSession())
    except TypeError:
        return _DaemonReadSession()


def _maybe_open_circuit(
    session: _DaemonReadSession,
    surface: str,
    error: LocalDaemonError,
) -> None:
    if isinstance(error, LocalDaemonTransportError):
        session.open_circuit(surface, error)


def _fallback[T](
    surface: str,
    direct_loader: Callable[[], T],
    *,
    reason: str,
    message: str | None,
    diagnostics: dict[str, Any] | None = None,
) -> DaemonReadResult[T]:
    return DaemonReadResult(
        value=direct_loader(),
        surface=surface,
        used_daemon=False,
        fallback_reason=reason,
        fallback_message=message,
        fallback_diagnostics=diagnostics,
    )


def _fallback_from_error[T](
    surface: str,
    direct_loader: Callable[[], T],
    error: LocalDaemonError,
    *,
    diagnostics: dict[str, Any] | None = None,
) -> DaemonReadResult[T]:
    if isinstance(error, LocalDaemonRpcError):
        return _fallback(
            surface,
            direct_loader,
            reason=error.fallback_reason or error.code,
            message=error.fallback_message or error.message,
            diagnostics=diagnostics,
        )
    if isinstance(error, LocalDaemonTransportError):
        return _fallback(
            surface,
            direct_loader,
            reason=error.fallback_reason or error.code,
            message=str(error),
            diagnostics=diagnostics,
        )
    return _fallback(
        surface,
        direct_loader,
        reason="daemon_error",
        message=str(error),
        diagnostics=diagnostics,
    )


def _error_reason(error: LocalDaemonError) -> str:
    if isinstance(error, LocalDaemonRpcError):
        return error.fallback_reason or error.code
    if isinstance(error, LocalDaemonTransportError):
        return error.fallback_reason or error.code
    return "daemon_error"


def _error_message(error: LocalDaemonError) -> str:
    if isinstance(error, LocalDaemonRpcError):
        return error.fallback_message or error.message
    return str(error)


__all__ = [
    "CAPABILITY_BY_READ_SURFACE",
    "CAPABILITY_PROBE_TIMEOUT_SECONDS",
    "FALLBACKABLE_RPC_CODES",
    "DaemonReadResult",
    "is_fallbackable_daemon_error",
    "read_or_fallback",
]
