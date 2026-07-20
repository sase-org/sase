"""Updates tab fixtures for Config Center PNG visual snapshots."""

from __future__ import annotations

from typing import Any

import pytest

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
    core_incoming_commits: dict[str, IncomingCommits] | None = None,
    agent_cli_statuses: Any | None = None,
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
        core_incoming_commits=core_incoming_commits
        if core_incoming_commits is not None
        else _default_core_incoming_commits(resolved_core_versions),
        agent_cli_statuses=(
            _agent_cli_statuses()
            if agent_cli_statuses is None
            else tuple(agent_cli_statuses)
        ),
        agent_cli_colors={"claude": "#D97757", "codex": "#10A37F"},
    )
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: result)
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
