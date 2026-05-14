"""Release contract constants for daemon rollout closeout."""

from __future__ import annotations

from typing import Any

from sase.daemon.constants import (
    LOCAL_DAEMON_EXPECTED_PROJECTION_READ_SCHEMA_VERSION,
    LOCAL_DAEMON_EXPECTED_PROJECTION_WRITE_SCHEMA_VERSION,
    LOCAL_DAEMON_MAX_SUPPORTED_SCHEMA_VERSION,
    LOCAL_DAEMON_MIN_SUPPORTED_SCHEMA_VERSION,
)
from sase.host.wire import PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION

SASE_CORE_RS_DEPENDENCY_NAME = "sase-core-rs"
SASE_CORE_RS_SUPPORTED_SPECIFIER = ">=0.1.1,<0.2.0"
SASE_CORE_RS_DEPENDENCY = (
    f"{SASE_CORE_RS_DEPENDENCY_NAME}{SASE_CORE_RS_SUPPORTED_SPECIFIER}"
)


def release_contract_payload() -> dict[str, Any]:
    """Return package and wire-version support for release diagnostics."""

    return {
        "sase_core_rs": {
            "dependency": SASE_CORE_RS_DEPENDENCY,
            "name": SASE_CORE_RS_DEPENDENCY_NAME,
            "supported_specifier": SASE_CORE_RS_SUPPORTED_SPECIFIER,
        },
        "local_daemon": {
            "min_supported_schema_version": LOCAL_DAEMON_MIN_SUPPORTED_SCHEMA_VERSION,
            "max_supported_schema_version": LOCAL_DAEMON_MAX_SUPPORTED_SCHEMA_VERSION,
            "expected_projection_read_schema_version": (
                LOCAL_DAEMON_EXPECTED_PROJECTION_READ_SCHEMA_VERSION
            ),
            "expected_projection_write_schema_version": (
                LOCAL_DAEMON_EXPECTED_PROJECTION_WRITE_SCHEMA_VERSION
            ),
        },
        "provider_host": {
            "ipc_wire_schema_version": PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION,
        },
    }


__all__ = [
    "SASE_CORE_RS_DEPENDENCY",
    "SASE_CORE_RS_DEPENDENCY_NAME",
    "SASE_CORE_RS_SUPPORTED_SPECIFIER",
    "release_contract_payload",
]
