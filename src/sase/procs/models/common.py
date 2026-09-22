"""Shared wire constants and schema validation for proc models."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

PROC_WIRE_SCHEMA_VERSION: Final = 3
SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS: Final = frozenset({1, 2, PROC_WIRE_SCHEMA_VERSION})

ACTIVE_PROC_STATUSES: Final = frozenset({"pending", "running", "settling"})
TERMINAL_PROC_STATUSES: Final = frozenset({"success", "error", "killed"})

# A supervised proc submitted by a session, attributed to it.
COMMAND_PROC_KIND: Final = "command"
# A proc a TUI process runs itself and mirrors into the store.
TUI_PROC_KIND: Final = "tui"
# A supervised proc no session owns, so every surface always shows it.
DETACHED_PROC_KIND: Final = "detached"
PROC_KINDS: Final = frozenset({COMMAND_PROC_KIND, TUI_PROC_KIND, DETACHED_PROC_KIND})
PROC_LIFECYCLE_LEGACY: Final = "legacy"
PROC_LIFECYCLE_PROC_SHELL: Final = "proc-shell"
STORE_LOG_OWNER: Final = "proc-store"
ARTIFACTS_LOG_OWNER: Final = "artifacts"
XPROMPT_PROC_ORIGIN: Final = "xprompt-proc"


def require_wire_schema(data: Mapping[str, Any]) -> None:
    schema = int(data["schema_version"])
    if schema not in SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS:
        raise ValueError(
            f"proc wire schema mismatch: got {schema}, "
            f"expected one of {sorted(SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS)}"
        )


__all__ = [
    "ACTIVE_PROC_STATUSES",
    "ARTIFACTS_LOG_OWNER",
    "COMMAND_PROC_KIND",
    "DETACHED_PROC_KIND",
    "PROC_KINDS",
    "PROC_LIFECYCLE_LEGACY",
    "PROC_LIFECYCLE_PROC_SHELL",
    "PROC_WIRE_SCHEMA_VERSION",
    "STORE_LOG_OWNER",
    "SUPPORTED_PROC_WIRE_SCHEMA_VERSIONS",
    "TERMINAL_PROC_STATUSES",
    "TUI_PROC_KIND",
    "XPROMPT_PROC_ORIGIN",
    "require_wire_schema",
]
