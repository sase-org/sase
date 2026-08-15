"""Stable operation names for durable ACE/CLI command contracts."""

from __future__ import annotations

PATCH_STATUS = "patch.status"
PATCH_SUBMIT = "patch.submit"
PATCH_ARCHIVE = "patch.archive"
PATCH_RESTORE = "patch.restore"
PATCH_REVERT = "patch.revert"
PATCH_REWORD = "patch.reword"
PATCH_TAG = "patch.tag"
PATCH_MAIL = "patch.mail"
PATCH_ACCEPT = "patch.accept"
PATCH_REBASE = "patch.rebase"
PATCH_SYNC = "patch.sync"
PATCH_REWIND = "patch.rewind"

AGENT_PERSIST_DIRECTIVE = "agent.persist-directive"
AGENT_REVERT = "agent.revert"
AGENT_CLEANUP = "agent.cleanup"

BEAD_STATUS = "bead.status"

NOTIFY_APPLY_STATE = "notify.apply-state"

PLUGIN_INSTALL = "plugin.install"

MONITOR_STOP = "monitor.stop"
RUN_LAUNCH = "run.launch"


__all__ = [
    "AGENT_CLEANUP",
    "AGENT_PERSIST_DIRECTIVE",
    "AGENT_REVERT",
    "BEAD_STATUS",
    "MONITOR_STOP",
    "NOTIFY_APPLY_STATE",
    "PATCH_ACCEPT",
    "PATCH_ARCHIVE",
    "PATCH_MAIL",
    "PATCH_REBASE",
    "PATCH_RESTORE",
    "PATCH_REVERT",
    "PATCH_REWIND",
    "PATCH_REWORD",
    "PATCH_STATUS",
    "PATCH_SUBMIT",
    "PATCH_SYNC",
    "PATCH_TAG",
    "PLUGIN_INSTALL",
    "RUN_LAUNCH",
]
