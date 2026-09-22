"""SSH relay for machine-targeted sudo authentication.

Compatibility facade: the implementation now lives in the sibling modules
``ssh_defs``, ``ssh_paths``, ``ssh_transport``, ``ssh_exec``, and
``ssh_detached``. New code should import the owning submodule directly.
"""

from __future__ import annotations

from sase.sudo.ssh_defs import PRE_SPAWN_REMOTE_ERROR_CODES, CommandRunner
from sase.sudo.ssh_detached import cleanup_remote_sudo, wait_for_remote_sudo_ledger
from sase.sudo.ssh_exec import (
    remote_supports_detached_execution,
    run_remote_sudo,
    run_remote_sudo_detached,
)
from sase.sudo.ssh_paths import allocate_remote_sudo_paths

__all__ = [
    "CommandRunner",
    "PRE_SPAWN_REMOTE_ERROR_CODES",
    "allocate_remote_sudo_paths",
    "cleanup_remote_sudo",
    "remote_supports_detached_execution",
    "run_remote_sudo",
    "run_remote_sudo_detached",
    "wait_for_remote_sudo_ledger",
]
