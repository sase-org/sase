"""Shared constants and models for machine-targeted sudo over SSH."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]

CONTRACT_SCHEMA_VERSION = 1
DETACHED_EXECUTION_CAPABILITY = "detached_execution"
REMOTE_BASE = "/tmp"
REMOTE_EXECUTOR_DEATH_GRACE_SECONDS = 1.0
REMOTE_POLL_MAX_SECONDS = 2.0
REMOTE_POLL_SECONDS = 0.25
REMOTE_POLL_SSH_TIMEOUT_SECONDS = 5.0
REMOTE_STAGE_SSH_TIMEOUT_SECONDS = 15.0
REMOTE_STOP_GRACE_SECONDS = 5.0
REMOTE_OUTPUT_CHUNK_BYTES = 64 * 1024
SSH_TRANSPORT_FAILURE = 255
STAGE_MKDIR_FAILED = 11
STAGE_CHMOD_FAILED = 12
STAGE_WRITE_FAILED = 13
STAGE_REPLACE_FAILED = 14
STAGE_CHMOD_FILE_FAILED = 15
LIVENESS_DEAD = 1
LIVENESS_UNKNOWN = 2
PRE_SPAWN_REMOTE_ERROR_CODES = frozenset(
    {
        "detach_unsupported",
        "invalid_ssh_target",
        "remote_sudo_contract_mismatch",
        "remote_sudo_stage_failed",
        "remote_sudo_unavailable",
        "ssh_unavailable",
    }
)


@dataclass(frozen=True)
class RemoteSudoPaths:
    """Opaque target-side paths for one remote sudo attempt."""

    directory: str
    manifest: str
    ledger: str
    handshake: str
    log: str
    stop: str

    def to_dict(self) -> dict[str, str]:
        """Return a JSON-safe representation for operation sidecars."""
        return {
            "directory": self.directory,
            "handshake": self.handshake,
            "ledger": self.ledger,
            "log": self.log,
            "manifest": self.manifest,
            "stop": self.stop,
        }


@dataclass(frozen=True)
class RemoteSudoContract:
    """Target-side sudo exec contract advertised by ``sase sudo exec``."""

    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class RemoteExecutorLiveness:
    """Three-way remote executor probe result."""

    classification: str
    reason: str


__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "DETACHED_EXECUTION_CAPABILITY",
    "LIVENESS_DEAD",
    "LIVENESS_UNKNOWN",
    "PRE_SPAWN_REMOTE_ERROR_CODES",
    "REMOTE_BASE",
    "REMOTE_EXECUTOR_DEATH_GRACE_SECONDS",
    "REMOTE_OUTPUT_CHUNK_BYTES",
    "REMOTE_POLL_MAX_SECONDS",
    "REMOTE_POLL_SECONDS",
    "REMOTE_POLL_SSH_TIMEOUT_SECONDS",
    "REMOTE_STAGE_SSH_TIMEOUT_SECONDS",
    "REMOTE_STOP_GRACE_SECONDS",
    "SSH_TRANSPORT_FAILURE",
    "STAGE_CHMOD_FAILED",
    "STAGE_CHMOD_FILE_FAILED",
    "STAGE_MKDIR_FAILED",
    "STAGE_REPLACE_FAILED",
    "STAGE_WRITE_FAILED",
    "CommandRunner",
    "RemoteExecutorLiveness",
    "RemoteSudoContract",
    "RemoteSudoPaths",
]
