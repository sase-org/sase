"""Compatibility exports for daemon lifecycle actions."""

from __future__ import annotations

import os
import subprocess

from sase.integrations._daemon_lifecycle_projection_actions import (
    run_daemon_backup,
    run_daemon_checkpoint,
    run_daemon_diff,
    run_daemon_list_backups,
    run_daemon_rebuild,
    run_daemon_restore,
    run_daemon_verify,
)
from sase.integrations._daemon_lifecycle_runtime_actions import (
    repair_stale_lock,
    run_daemon_start,
    run_daemon_stop,
    wait_for_background_start,
)

__all__ = [
    "os",
    "subprocess",
    "repair_stale_lock",
    "run_daemon_backup",
    "run_daemon_checkpoint",
    "run_daemon_diff",
    "run_daemon_list_backups",
    "run_daemon_rebuild",
    "run_daemon_restore",
    "run_daemon_start",
    "run_daemon_stop",
    "run_daemon_verify",
    "wait_for_background_start",
]
