"""Updates tab fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

from typing import Any

import pytest

from sase.agent_clis.history import AgentCliUpdateRun, AgentCliUpdateRunEntry
from sase.agent_clis.models import UpdateResultStatus, UpdateTrigger
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.updates.incoming_commits import (
    CommitSummary,
    IncomingCommits,
    RepoIncomingCommits,
)
from tests.ace.tui.test_plugins_browser_pane import (
    _NOW as _PLUGINS_NOW,
    _catalog,
    _core_versions,
)
from tests.ace.tui._plugins_browser_pane_helpers import _agent_cli_statuses


def _patch_plugins_catalog(
    monkeypatch: pytest.MonkeyPatch,
    *,
    catalog: Any | None = "default",
    error: str | None = None,
    uv_tool: Any | None = None,
    core_versions: Any | None = None,
    core_error: str | None = None,
    core_incoming_commits: dict[str, IncomingCommits] | None = None,
    install_mode: str | None = None,
    dev_root: str | None = None,
    agent_cli_statuses: Any | None = None,
    agent_cli_history: tuple[AgentCliUpdateRun, ...] = (),
    agent_cli_history_error: str | None = None,
    agent_cli_history_enabled: bool = False,
) -> None:
    """Stub the Updates pane's plugin catalog load with a deterministic result."""
    resolved = _catalog() if catalog == "default" else catalog
    resolved_core_versions = core_versions or _core_versions()
    result = pbp._PluginsLoadResult(
        catalog=resolved,
        error=error,
        now=_PLUGINS_NOW,
        uv_tool=uv_tool,
        core_versions=resolved_core_versions,
        core_error=core_error,
        core_incoming_commits=core_incoming_commits
        if core_incoming_commits is not None
        else _default_core_incoming_commits(resolved_core_versions),
        install_mode=install_mode,
        dev_root=dev_root,
        agent_cli_statuses=(
            _agent_cli_statuses()
            if agent_cli_statuses is None
            else tuple(agent_cli_statuses)
        ),
        agent_cli_colors={"claude": "#D97757", "codex": "#10A37F"},
        agent_cli_history=agent_cli_history,
        agent_cli_history_error=agent_cli_history_error,
    )
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: result)
    monkeypatch.setattr(
        pbp,
        "_load_agent_cli_history_config",
        lambda: pbp._AgentCliHistoryConfig(
            enabled=agent_cli_history_enabled,
            max_rows=8,
        ),
    )
    monkeypatch.setattr(pbp, "_collect_installed_core_versions", _core_versions)
    monkeypatch.setattr(
        pbp,
        "_fetch_incoming_commits",
        lambda *_a, **_kw: _visual_incoming_commits("plugin"),
    )
    monkeypatch.setattr(
        pbp,
        "_fetch_incoming_commit_groups",
        lambda specs, **_kw: tuple(
            RepoIncomingCommits(label, _visual_incoming_commits(label))
            for label, _spec in specs
        ),
    )


def _visual_incoming_commits(label: str) -> IncomingCommits:
    return IncomingCommits(
        total=3,
        commits=(
            CommitSummary("abc1234", f"Newest {label} change"),
            CommitSummary("def5678", f"Older {label} change"),
        ),
        source="github",
    )


def _default_core_incoming_commits(core_versions: Any) -> dict[str, IncomingCommits]:
    packages = getattr(core_versions, "packages", ())
    return {
        package.name: _visual_incoming_commits(package.name)
        for package in packages
        if getattr(package, "update_available", False)
    }


def _agent_cli_history() -> tuple[AgentCliUpdateRun, ...]:
    """Deterministic update history for Agent CLIs visual snapshots."""
    return (
        _history_run(
            "visual-claude-update",
            epoch=_PLUGINS_NOW - 2 * 60 * 60,
            trigger=UpdateTrigger.COMPREHENSIVE,
            elapsed=11.4,
            entries=(
                _history_entry(
                    "claude",
                    "Claude Code",
                    UpdateResultStatus.UPDATED,
                    old_version="1.0.0",
                    new_version="1.1.0",
                    elapsed=9.0,
                ),
                _history_entry(
                    "codex",
                    "Codex CLI",
                    UpdateResultStatus.ALREADY_CURRENT,
                    old_version="1.0.0",
                    new_version="1.0.0",
                ),
                _history_entry(
                    "qwen",
                    "Qwen Code",
                    UpdateResultStatus.SKIPPED,
                    reason="Not installed",
                ),
            ),
        ),
        _history_run(
            "visual-claude-failure",
            epoch=_PLUGINS_NOW - 2 * 24 * 60 * 60,
            trigger=UpdateTrigger.ADMIN_CENTER,
            elapsed=2.0,
            entries=(
                _history_entry(
                    "claude",
                    "Claude Code",
                    UpdateResultStatus.FAILED,
                    old_version="1.0.0",
                    new_version=None,
                    elapsed=2.0,
                    reason=(
                        "npm ERR! EACCES: permission denied while writing to the "
                        "global package directory; retry after fixing ownership"
                    ),
                ),
            ),
        ),
    )


def _history_run(
    run_id: str,
    *,
    epoch: float,
    trigger: UpdateTrigger,
    elapsed: float,
    entries: tuple[AgentCliUpdateRunEntry, ...],
) -> AgentCliUpdateRun:
    counts = {
        status.value: sum(entry.status is status for entry in entries)
        for status in UpdateResultStatus
    }
    return AgentCliUpdateRun(
        schema_version=1,
        run_id=run_id,
        timestamp="2023-11-14T22:13:20+00:00",
        epoch=epoch,
        trigger=trigger,
        all_clis=len(entries) > 1,
        elapsed_seconds=elapsed,
        counts=counts,
        entries=entries,
    )


def _history_entry(
    name: str,
    display_name: str,
    status: UpdateResultStatus,
    *,
    old_version: str | None = None,
    new_version: str | None = None,
    elapsed: float = 0.0,
    reason: str | None = None,
) -> AgentCliUpdateRunEntry:
    command = None
    if status in {UpdateResultStatus.UPDATED, UpdateResultStatus.FAILED}:
        command = (name, "update")
    return AgentCliUpdateRunEntry(
        name=name,
        display_name=display_name,
        status=status,
        old_version=old_version,
        new_version=new_version,
        command=command,
        reason=reason,
        elapsed_seconds=elapsed,
        output_tail=None,
    )
