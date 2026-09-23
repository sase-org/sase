"""Shared fixtures for the Updates-tab agent-CLI install-flow tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.agent_clis.install import (
    AgentCliInstallEntry,
    InstallScript,
)
from sase.agent_clis.models import (
    AgentCliOperation,
    AgentCliStatus,
    AgentCliUpdateResult,
    InstallRoute,
    UpdateResultStatus,
)
from tests.ace.tui._plugins_browser_pane_helpers import _agent_cli_statuses

_DIGEST = "ab" * 32


def _by_name() -> dict[str, AgentCliStatus]:
    return {status.name: status for status in _agent_cli_statuses()}


def _npm_entry(
    status: AgentCliStatus, *, on_path: bool | None = True
) -> AgentCliInstallEntry:
    assert status.package is not None
    return AgentCliInstallEntry(
        status,
        route=InstallRoute.NPM,
        argv=("npm", "install", "-g", status.package),
        env_overlay=status.install_env,
        install_dir="/home/dev/.npm-global/bin",
        install_dir_on_path=on_path,
    )


def _script_entry(
    status: AgentCliStatus,
    script: InstallScript,
    *,
    on_path: bool | None = False,
) -> AgentCliInstallEntry:
    return AgentCliInstallEntry(
        status,
        route=InstallRoute.SCRIPT,
        argv=("bash", str(script.path)),
        env_overlay=status.install_env,
        script=script,
        install_dir="~/.local/bin",
        install_dir_on_path=on_path,
    )


def _skip_entry(status: AgentCliStatus, reason: str) -> AgentCliInstallEntry:
    return AgentCliInstallEntry(
        status,
        route=InstallRoute.MANUAL,
        skip_reason=reason,
    )


def _make_script(
    tmp_path: Path, *, payload: bytes = b"#!/bin/bash\necho hi\n"
) -> InstallScript:
    path = tmp_path / "install-ab.sh"
    path.write_bytes(payload)
    return InstallScript(
        url="https://dev.meta.ai/install.sh",
        path=path,
        digest=_DIGEST,
        size_bytes=len(payload),
    )


def _install_result(
    name: str,
    display_name: str,
    status: UpdateResultStatus,
    *,
    new_version: str | None = "0.8.0",
    reason: str | None = None,
    on_path: bool | None = None,
) -> AgentCliUpdateResult:
    return AgentCliUpdateResult(
        name=name,
        display_name=display_name,
        status=status,
        old_version=None,
        new_version=new_version,
        command=("npm", "install", "-g", "x")
        if status is UpdateResultStatus.UPDATED
        else None,
        docs_url=None,
        reason=reason,
        operation=AgentCliOperation.INSTALL,
        install_dir="/home/dev/.npm-global/bin",
        install_dir_on_path=on_path,
    )


def _stub_install_plan(
    monkeypatch: pytest.MonkeyPatch, plan: Any
) -> list[tuple[str, ...]]:
    """Stub the pane install-planning seam; record requested names."""
    requested: list[tuple[str, ...]] = []

    def _plan(names: tuple[str, ...], **_kwargs: Any) -> Any:
        requested.append(tuple(names))
        return plan

    monkeypatch.setattr(pbp, "_plan_agent_cli_installs", _plan)
    return requested


def _completion(payload: Any, *, success: bool, message: str) -> Any:
    from datetime import datetime

    from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
    from sase.ace.tui.proc_observer import ObservedProc

    return TrackedProcCompletion(
        proc_info=ObservedProc(
            proc_id="session-test",
            proc_type="agent-cli-plugin-install",
            cl_name="",
            project_file="",
            status="done",
            message=message,
            started_at=datetime(2026, 8, 21, 12, 0, 0),
            display_name="agent-cli-plugin-install",
        ),
        success=success,
        message=message,
        output="",
        payload=payload,
    )


class _FakeReporter:
    """A minimal session-proc reporter recording phases and result logs."""

    def __init__(self) -> None:
        self.phases: list[str] = []
        self.sections: list[str] = []
        self.logs: list[tuple[str, str]] = []

    def phase(self, label: str) -> None:
        self.phases.append(label)

    def section(self, title: str) -> None:
        self.sections.append(title)

    def log(self, text: str, *, stream: str = "stdout") -> None:
        self.logs.append((stream, text))

    def command_runner(self) -> Any:
        def _run(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("executor was stubbed; no subprocess should run")

        return _run

    def uv_runner(self) -> Any:
        def _run(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("executor was stubbed; no subprocess should run")

        return _run


# -- detail panel ------------------------------------------------------------
