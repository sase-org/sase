"""Shared types and path normalization for local-command trust management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from sase.config.local_trust import LocalCommandProjection

LOCAL_COMMAND_TRUST_STORE_WIRE_SCHEMA_VERSION = 1
LOCAL_COMMAND_TRUST_STORE_DIRECTORY = "local_config_trust"
LOCAL_COMMAND_TRUST_STORE_FILENAME = "records.json"


class LocalCommandTrustManagementError(RuntimeError):
    """Raised when trust status or acknowledgment cannot be completed."""


@dataclass(frozen=True)
class LocalCommandTrustContext:
    """One resolved checkout, logical config location, identity and projection."""

    checkout_root: Path
    selected_config_path: Path
    logical_config_path: str
    project_identity: str
    projection: LocalCommandProjection


def canonical_path(path: Path) -> Path:
    """Return a stable canonical path or a trust-management error."""
    try:
        return path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as error:
        raise LocalCommandTrustManagementError(
            f"cannot canonicalize checkout path {path}: {error}"
        ) from error
