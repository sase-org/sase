"""Compatibility metadata and validation for local daemon RPC."""

from __future__ import annotations

import importlib
import importlib.metadata
from typing import Any

from sase import __version__ as SASE_PACKAGE_VERSION
from sase.core.rust import RUST_EXTENSION_MODULE_NAME
from sase.daemon.constants import (
    LOCAL_DAEMON_CLIENT_METADATA_SCHEMA_VERSION,
    LOCAL_DAEMON_EXPECTED_PROJECTION_READ_SCHEMA_VERSION,
    LOCAL_DAEMON_EXPECTED_PROJECTION_WRITE_SCHEMA_VERSION,
    LOCAL_DAEMON_MAX_SUPPORTED_SCHEMA_VERSION,
    LOCAL_DAEMON_MIN_SUPPORTED_SCHEMA_VERSION,
    LOCAL_DAEMON_SCHEMA_VERSION,
)
from sase.daemon.errors import LocalDaemonRpcError, LocalDaemonTransportError

_DIRECT_FALLBACK = "use direct source-store readers/writers or set SASE_NO_DAEMON=1"


def client_metadata(*, name: str, version: str) -> dict[str, Any]:
    """Return the client compatibility record sent with every request."""

    return {
        "schema_version": LOCAL_DAEMON_SCHEMA_VERSION,
        "metadata_schema_version": LOCAL_DAEMON_CLIENT_METADATA_SCHEMA_VERSION,
        "name": name,
        "version": version,
        "package_version": SASE_PACKAGE_VERSION,
        "min_supported_schema_version": LOCAL_DAEMON_MIN_SUPPORTED_SCHEMA_VERSION,
        "max_supported_schema_version": LOCAL_DAEMON_MAX_SUPPORTED_SCHEMA_VERSION,
        "sase_core_rs_version": _sase_core_rs_version(),
    }


def validate_response_envelope(response: dict[str, Any]) -> None:
    """Reject local daemon envelopes outside this client's schema range."""

    schema_version = response.get("schema_version")
    if not isinstance(schema_version, int):
        raise LocalDaemonTransportError(
            "local daemon response envelope is missing integer schema_version",
            code="unsupported_server_version",
            fallback_reason="unsupported_server_version",
        )
    if schema_version < LOCAL_DAEMON_MIN_SUPPORTED_SCHEMA_VERSION:
        raise _compatibility_error(
            code="unsupported_server_version",
            message=(
                "local daemon response schema is too old; upgrade or restart "
                "the daemon, or use SASE_NO_DAEMON=1"
            ),
            target="schema_version",
            details={"server_schema_version": schema_version},
        )
    if schema_version > LOCAL_DAEMON_MAX_SUPPORTED_SCHEMA_VERSION:
        raise _compatibility_error(
            code="unsupported_server_version",
            message=(
                "local daemon response schema is newer than this client; "
                "upgrade sase or use SASE_NO_DAEMON=1"
            ),
            target="schema_version",
            details={"server_schema_version": schema_version},
        )


def validate_negotiated_compatibility(data: dict[str, Any]) -> None:
    """Validate compatibility fields from health/capabilities responses."""

    compatibility = data.get("compatibility")
    if not isinstance(compatibility, dict):
        return

    range_data = compatibility.get("supported_client_schema_range")
    if isinstance(range_data, dict):
        min_server = range_data.get("min")
        max_server = range_data.get("max")
    else:
        min_server = data.get("min_client_schema_version")
        max_server = data.get("max_client_schema_version")
    if isinstance(min_server, int) and isinstance(max_server, int):
        if max_server < LOCAL_DAEMON_MIN_SUPPORTED_SCHEMA_VERSION:
            raise _compatibility_error(
                code="unsupported_server_version",
                message=(
                    "local daemon is too old for this client; upgrade or "
                    "restart the daemon, or use SASE_NO_DAEMON=1"
                ),
                target="compatibility.supported_client_schema_range",
                details={"server_min": min_server, "server_max": max_server},
            )
        if min_server > LOCAL_DAEMON_MAX_SUPPORTED_SCHEMA_VERSION:
            raise _compatibility_error(
                code="unsupported_server_version",
                message=(
                    "local daemon requires a newer client; upgrade sase or "
                    "use SASE_NO_DAEMON=1"
                ),
                target="compatibility.supported_client_schema_range",
                details={"server_min": min_server, "server_max": max_server},
            )

    _validate_projection_schema(
        compatibility,
        "projection_read_schema_version",
        LOCAL_DAEMON_EXPECTED_PROJECTION_READ_SCHEMA_VERSION,
    )
    _validate_projection_schema(
        compatibility,
        "projection_write_schema_version",
        LOCAL_DAEMON_EXPECTED_PROJECTION_WRITE_SCHEMA_VERSION,
    )


def _validate_projection_schema(
    compatibility: dict[str, Any], field: str, expected: int
) -> None:
    actual = compatibility.get(field)
    if actual is None:
        return
    if actual != expected:
        raise _compatibility_error(
            code="projection_schema_mismatch",
            message=(
                "local daemon projection schema is incompatible; rebuild "
                "projections, restart the daemon, or use SASE_NO_DAEMON=1"
            ),
            target=f"compatibility.{field}",
            details={"expected": expected, "actual": actual},
        )


def _compatibility_error(
    *,
    code: str,
    message: str,
    target: str,
    details: dict[str, Any],
) -> LocalDaemonRpcError:
    return LocalDaemonRpcError(
        code=code,
        message=message,
        retryable=False,
        target=target,
        details=details,
        fallback_reason=code,
        fallback_message=_DIRECT_FALLBACK,
    )


def _sase_core_rs_version() -> str | None:
    try:
        return importlib.metadata.version(RUST_EXTENSION_MODULE_NAME)
    except importlib.metadata.PackageNotFoundError:
        pass
    try:
        module = importlib.import_module(RUST_EXTENSION_MODULE_NAME)
    except Exception:
        return None
    version = getattr(module, "__version__", None)
    return version if isinstance(version, str) else None
