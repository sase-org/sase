"""Shared fixtures for Projects-tab init check/apply flow tests."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.projects_pane import ProjectCountsLoadResult, ProjectsPane
from sase.ace.tui.proc_observer import ObservedProc
from sase.repo_inventory import RepoInventory
from sase.workspace_provider.inventory import WorkspaceInventory
from tests.ace.tui._plugins_browser_pane_helpers import _core_versions
from tests.ace.tui._proc_submit_signature_helpers import (
    assert_session_worker_submit_signature,
)
from tests.ace.tui.modals.project_management_modal_test_helpers import (
    make_project_record,
)
from tests.ace.tui.modals.projects_pane_init_test_helpers import (
    action_row,
    check_payload,
    planner_row,
    project_plan,
    raw_document,
    raw_planner,
    raw_project,
)


def _patch_panes(
    monkeypatch: pytest.MonkeyPatch,
    records: list[Any] | None = None,
) -> None:
    config_result = cp._LoadResult(view=None, error=None, token=("tok", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: config_result)
    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.xprompt.loader.get_all_project_local_prompts",
        lambda: {},
    )
    plugins_result = pbp._PluginsLoadResult(
        catalog=None, error="stub", now=0.0, core_versions=_core_versions()
    )
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: plugins_result)
    monkeypatch.setattr(pbp, "_collect_installed_core_versions", _core_versions)
    seeded = records or [
        make_project_record("alpha", state="enabled"),
        make_project_record("beta", state="enabled"),
    ]
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: list(seeded),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.collect_project_inventory_counts",
        lambda *_args: ProjectCountsLoadResult({}),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_repo_inventory",
        lambda *_args, **_kwargs: RepoInventory(()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_workspace_inventory",
        lambda *_args, **_kwargs: WorkspaceInventory((), ()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.get_known_project_workspaces",
        lambda **_kwargs: {},
    )


class _RecordingReporter:
    def __init__(self, *, stdout: str, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.runs: list[tuple[list[str], dict[str, Any]]] = []
        self.phases: list[str] = []

    def phase(self, label: str) -> None:
        self.phases.append(label)

    def log(self, _text: str, **_kwargs: Any) -> None:
        return None

    def run(
        self, argv: list[object], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        recorded = [str(part) for part in argv]
        self.runs.append((recorded, kwargs))
        return subprocess.CompletedProcess(recorded, self.returncode, self.stdout, "")


class _TimeoutReporter(_RecordingReporter):
    def __init__(self) -> None:
        super().__init__(stdout="")

    def run(
        self, argv: list[object], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        recorded = [str(part) for part in argv]
        self.runs.append((recorded, kwargs))
        raise subprocess.TimeoutExpired(recorded, float(kwargs["timeout"]))


def _install_submit(page: AcePage) -> list[tuple[tuple[Any, ...], dict[str, Any], Any]]:
    submitted: list[tuple[tuple[Any, ...], dict[str, Any], Any]] = []

    def fake_submit(*args: Any, **kwargs: Any) -> Any:
        assert_session_worker_submit_signature(args, kwargs)
        handle = SimpleNamespace(proc_id=f"session-{len(submitted)}")
        submitted.append((args, kwargs, handle))
        return handle

    page.app._submit_session_worker = fake_submit  # type: ignore[method-assign]
    return submitted


def _completion(
    proc_id: str,
    payload: object | None,
    *,
    success: bool = True,
    message: str = "ok",
    error: str | None = None,
    proc_type: str = "init-check",
) -> TrackedProcCompletion[Any]:
    return TrackedProcCompletion(
        proc_info=ObservedProc(
            proc_id=proc_id,
            proc_type=proc_type,
            cl_name="",
            project_file="",
            status="success" if success else "error",
            message=message,
            started_at=datetime(2026, 9, 4, 12, 0, 0),
        ),
        success=success,
        message=message,
        output="",
        payload=payload,
        error=error,
    )


def _drift_payload(name: str = "alpha"):
    return check_payload(
        project_plan(
            name,
            status="needs_attention",
            planners=(
                planner_row(
                    "memory",
                    summary="1 update",
                    has_changes=True,
                    actions=(action_row(operation="update", added=1),),
                ),
            ),
        )
    )


def _tty_blocked_payload(name: str = "alpha"):
    return check_payload(
        project_plan(
            name,
            status="failed",
            planners=(
                planner_row(
                    "config",
                    summary="choose a machine identity",
                    has_changes=True,
                    runnable=False,
                    requires_tty=True,
                    blockers=["owner identity requires a TTY"],
                    actions=(action_row(operation="create"),),
                ),
            ),
        ),
        status="blocked",
    )


class _SuspendRecorder:
    def __init__(self) -> None:
        self.active = False
        self.enters = 0
        self.exits = 0

    def __enter__(self) -> None:
        self.enters += 1
        self.active = True

    def __exit__(self, *_exc_info: object) -> None:
        self.active = False
        self.exits += 1


def _current_json(name: str = "alpha") -> str:
    return json.dumps(
        raw_document(
            raw_project(name, planners=[raw_planner("memory", label="Memory")]),
            status="current",
        )
    )


async def _open_projects(page: AcePage) -> tuple[ConfigCenterModal, ProjectsPane]:
    modal = ConfigCenterModal(initial_tab="projects")
    page.app.push_screen(modal)
    await page.expect_modal("ConfigCenterModal")
    await page.wait_for(lambda _s: bool(modal.query("#projects")))
    pane = modal.query_one("#projects", ProjectsPane)
    await page.wait_for(lambda _s: bool(pane.query("#projects-list")))
    return modal, pane
