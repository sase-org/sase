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

AGENT_CLI_UPDATE = "agent-cli.update"
AGENT_PERSIST_DIRECTIVE = "agent.persist-directive"
AGENT_REVERT = "agent.revert"
AGENT_CLEANUP = "agent.cleanup"

AXE_BGCMD = "axe.bgcmd"

BEAD_ISSUE = "bead.issue"
BEAD_MUTATE = "bead.mutate"
BEAD_STATUS = "bead.status"

GATE_ACT = "gate.act"
GATE_ANSWER = "gate.answer"

GIT_POST_WRITE = "git.post-write"

LAUNCH_APPROVAL = "launch.approval"

NOTIFY_APPLY_STATE = "notify.apply-state"

PLUGIN_INSTALL = "plugin.install"
PLUGIN_UNINSTALL = "plugin.uninstall"
PLUGIN_UPDATE = "plugin.update"

MONITOR_STOP = "monitor.stop"
PROC_KILL = "proc.kill"
RUN_LAUNCH = "run.launch"
SASE_UPDATE = "sase.update"


__all__ = [
    "AGENT_CLEANUP",
    "AGENT_CLI_UPDATE",
    "AGENT_PERSIST_DIRECTIVE",
    "AGENT_REVERT",
    "AXE_BGCMD",
    "BEAD_ISSUE",
    "BEAD_MUTATE",
    "BEAD_STATUS",
    "GATE_ACT",
    "GATE_ANSWER",
    "GIT_POST_WRITE",
    "LAUNCH_APPROVAL",
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
    "PLUGIN_UNINSTALL",
    "PLUGIN_UPDATE",
    "PROC_KILL",
    "RUN_LAUNCH",
    "SASE_UPDATE",
]
