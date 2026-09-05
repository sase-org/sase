"""Pilot tests for Projects-tab ``i`` / ``I`` init check and apply flow."""

from __future__ import annotations

import json
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion, TrackedProcResult
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.init_plan_modal import InitPlanModal
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


async def test_entering_projects_tab_submits_no_init(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        await _open_projects(page)
        await page.pause()
        assert submitted == []


async def test_i_on_drifted_project_submits_check_and_sets_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        notices: list[tuple[str, str]] = []
        original_notify = page.app.notify

        def capture(message: str, **kwargs: Any) -> None:
            notices.append((message, str(kwargs.get("severity", "information"))))
            original_notify(message, **kwargs)

        page.app.notify = capture  # type: ignore[method-assign]
        _center, pane = await _open_projects(page)
        option_list = pane.query_one("#projects-list", OptionList)
        assert page.app.focused is option_list

        await page.press("i")
        await page.pause()

        assert "Checking initialization for alpha" in pane._status_message
        assert len(submitted) == 1
        args, kwargs, handle = submitted[0]
        assert args[0] == "init-check"
        assert kwargs["dedup_key"] == "sase-init-check:alpha"
        assert kwargs["exclusive_scopes"] == ("sase-init",)
        assert kwargs["cl_name"] == "alpha"
        assert kwargs["duplicate_message"] == (
            "A project initialization is already running."
        )
        reporter = _RecordingReporter(stdout=_current_json(), returncode=0)
        result = args[1](reporter)
        assert reporter.runs[0][0] == [
            "sase",
            "init",
            "-p",
            "alpha",
            "--check",
            "--json",
        ]
        assert reporter.runs[0][1]["log_lines"] is False
        assert reporter.runs[0][1]["cwd"] == Path.home()
        assert isinstance(result, TrackedProcResult)

        payload = _drift_payload("alpha")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        modal = page.app.screen
        assert isinstance(modal, InitPlanModal)
        await page.wait_for(lambda _s: len(modal.query("#init-plan-confirm")) > 0)

        await page.press("y")
        await page.wait_for(lambda _s: len(submitted) == 2)
        apply_args, apply_kwargs, _apply_handle = submitted[1]
        assert apply_args[0] == "init-apply"
        assert apply_kwargs["dedup_key"] == "sase-init:alpha"
        assert apply_kwargs["exclusive_scopes"] == ("sase-init",)
        apply_reporter = _RecordingReporter(stdout="", returncode=0)
        apply_args[1](apply_reporter)
        assert apply_reporter.runs[0][0] == [
            "sase",
            "init",
            "-p",
            "alpha",
            "--yes",
        ]


async def test_current_payload_opens_no_modal_and_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        notices: list[str] = []
        original_notify = page.app.notify

        def capture(message: str, **kwargs: Any) -> None:
            notices.append(message)
            original_notify(message, **kwargs)

        page.app.notify = capture  # type: ignore[method-assign]
        _center, pane = await _open_projects(page)
        await page.press("i")
        await page.pause()
        args, kwargs, handle = submitted[0]
        current = check_payload(
            project_plan(
                "alpha",
                planners=(planner_row("memory", label="Memory", summary="Current"),),
            ),
            status="current",
        )
        kwargs["on_complete"](_completion(handle.proc_id, current))
        await page.pause()
        assert not isinstance(page.app.screen, InitPlanModal)
        assert any("is initialized" in message for message in notices)
        assert "Memory" in notices[-1] or "Memory" in pane._status_message


async def test_initialize_all_ignores_marks_and_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        _center, pane = await _open_projects(page)
        pane._marked_projects.add("alpha")
        pane._text_filter = "alpha"
        pane._apply_filters()
        pane.query_one("#projects-list", OptionList).focus()
        await page.pause()

        await page.press("I")
        await page.pause()

        assert len(submitted) == 1
        args, kwargs, _handle = submitted[0]
        assert args[0] == "init-check"
        assert kwargs["dedup_key"] == "sase-init-check:all"
        reporter = _RecordingReporter(stdout=_current_json(), returncode=0)
        args[1](reporter)
        assert reporter.runs[0][0] == [
            "sase",
            "init",
            "--all",
            "--check",
            "--json",
        ]


async def test_marked_set_init_submits_one_ordered_check_and_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        _center, pane = await _open_projects(page)
        pane._marked_projects = {"alpha", "beta"}
        pane.query_one("#projects-list", OptionList).focus()

        await page.press("i")
        await page.pause()

        assert len(submitted) == 1
        args, kwargs, handle = submitted[0]
        assert args[0] == "init-check"
        assert kwargs["dedup_key"] == "sase-init-check:alpha:beta"
        assert kwargs["exclusive_scopes"] == ("sase-init",)
        assert kwargs["cl_name"] == ""
        reporter = _RecordingReporter(stdout=_current_json(), returncode=0)
        args[1](reporter)
        assert reporter.runs[0][0] == [
            "sase",
            "init",
            "-p",
            "alpha",
            "-p",
            "beta",
            "--check",
            "--json",
        ]

        payload = check_payload(
            project_plan(
                "alpha",
                status="needs_attention",
                planners=(planner_row("memory", has_changes=True),),
            ),
            project_plan(
                "beta",
                status="needs_attention",
                planners=(planner_row("memory", has_changes=True),),
            ),
        )
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        await page.press("y")
        await page.wait_for(lambda _s: len(submitted) == 2)

        apply_args, _apply_kwargs, _apply_handle = submitted[1]
        apply_reporter = _RecordingReporter(
            stdout="Initialization summary: 2 initialized\n",
            returncode=0,
        )
        apply_args[1](apply_reporter)
        assert apply_reporter.runs[0][0] == [
            "sase",
            "init",
            "-p",
            "alpha",
            "-p",
            "beta",
            "--yes",
        ]


async def test_i_filters_disabled_marks_and_submits_nothing_when_only_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(
        monkeypatch,
        records=[
            make_project_record("alpha", state="disabled", launchable=False),
            make_project_record("beta", state="enabled"),
        ],
    )
    async with AcePage() as page:
        submitted = _install_submit(page)
        notices: list[tuple[str, str]] = []
        original_notify = page.app.notify

        def capture(message: str, **kwargs: Any) -> None:
            notices.append((message, str(kwargs.get("severity", "information"))))
            original_notify(message, **kwargs)

        page.app.notify = capture  # type: ignore[method-assign]
        _center, pane = await _open_projects(page)
        option_list = pane.query_one("#projects-list", OptionList)
        option_list.highlighted = 0
        pane._marked_projects = {"alpha"}
        pane.action_initialize_project()
        await page.pause()

        assert submitted == []
        assert "alpha" in pane._status_message
        assert any(severity == "warning" for _message, severity in notices)

        pane._marked_projects = {"alpha", "beta"}
        pane.action_initialize_project()
        await page.pause()
        assert len(submitted) == 1
        reporter = _RecordingReporter(stdout=_current_json("beta"), returncode=0)
        submitted[0][0][1](reporter)
        assert reporter.runs[0][0] == [
            "sase",
            "init",
            "-p",
            "beta",
            "--check",
            "--json",
        ]


async def test_second_activation_uses_real_collision_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    gate = threading.Event()

    def hang(reporter: object) -> TrackedProcResult[None]:
        del reporter
        gate.wait(timeout=30)
        return TrackedProcResult(success=True, message="done")

    async with AcePage() as page:
        notices: list[str] = []
        original_notify = page.app.notify

        def capture(message: str, **kwargs: Any) -> None:
            notices.append(message)
            original_notify(message, **kwargs)

        page.app.notify = capture  # type: ignore[method-assign]
        _center, pane = await _open_projects(page)
        first = page.app._submit_session_worker(
            "init-check",
            hang,
            exclusive_scopes=("sase-init",),
            duplicate_message="A project initialization is already running.",
        )
        assert first is not None
        await page.pause()
        pane.action_initialize_project()
        await page.wait_for(
            lambda _s: any("already running" in item for item in notices)
        )
        assert pane._status_message == "A project initialization is already running."
        gate.set()


async def test_apply_completion_refresh_preserves_selected_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        make_project_record("alpha", state="enabled"),
        make_project_record("beta", state="enabled"),
    ]
    _patch_panes(monkeypatch, records=records)
    async with AcePage() as page:
        submitted = _install_submit(page)
        _center, pane = await _open_projects(page)
        option_list = pane.query_one("#projects-list", OptionList)
        option_list.highlighted = 1
        await page.pause()
        assert pane._selected_project_name() == "beta"

        await page.press("i")
        await page.pause()
        args, kwargs, handle = submitted[0]
        payload = _drift_payload("beta")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        await page.press("y")
        await page.wait_for(lambda _s: len(submitted) == 2)

        records[:] = [
            make_project_record("beta", state="enabled"),
            make_project_record("alpha", state="enabled"),
        ]
        apply_args, apply_kwargs, apply_handle = submitted[1]
        apply_reporter = _RecordingReporter(
            stdout="Initialization summary: 1 initialized\n",
            returncode=0,
        )
        apply_result = apply_args[1](apply_reporter)
        apply_kwargs["on_complete"](
            _completion(
                apply_handle.proc_id,
                apply_result.payload,
                proc_type="init-apply",
                message=apply_result.message,
            )
        )
        await page.pause()

        assert pane._selected_project_name() == "beta"
        assert option_list.highlighted == 0
        assert "Initialized 1" in pane._status_message


async def test_apply_timeout_surfaces_failure_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        notices: list[tuple[str, str]] = []
        original_notify = page.app.notify

        def capture(message: str, **kwargs: Any) -> None:
            notices.append((message, str(kwargs.get("severity", "information"))))
            original_notify(message, **kwargs)

        page.app.notify = capture  # type: ignore[method-assign]
        _center, pane = await _open_projects(page)

        await page.press("i")
        await page.pause()
        args, kwargs, handle = submitted[0]
        payload = _drift_payload("alpha")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        await page.press("y")
        await page.wait_for(lambda _s: len(submitted) == 2)

        apply_args, apply_kwargs, apply_handle = submitted[1]
        timeout_reporter = _TimeoutReporter()
        apply_result = apply_args[1](timeout_reporter)
        apply_kwargs["on_complete"](
            _completion(
                apply_handle.proc_id,
                apply_result.payload,
                success=False,
                proc_type="init-apply",
                message=apply_result.message,
                error=apply_result.error,
            )
        )
        await page.pause()

        assert apply_result.payload is not None
        assert apply_result.payload.kind == "failure"
        assert any(
            "timed out" in message and severity == "error"
            for message, severity in notices
        )
        assert "timed out" in pane._status_message
        assert pane._selected_project_name() == "alpha"


async def test_terminal_valve_suspends_runs_scoped_argv_and_reloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        suspend = _SuspendRecorder()
        monkeypatch.setattr(page.app, "suspend", lambda: suspend)
        run_calls: list[tuple[list[str], dict[str, Any]]] = []

        def fake_run(
            argv: list[str], **kwargs: Any
        ) -> subprocess.CompletedProcess[str]:
            assert suspend.active is True
            run_calls.append((list(argv), kwargs))
            return subprocess.CompletedProcess(list(argv), 0, "", "")

        monkeypatch.setattr(
            "sase.ace.tui.modals.projects_pane_init_actions.subprocess.run",
            fake_run,
        )
        _center, pane = await _open_projects(page)

        await page.press("i")
        await page.pause()
        args, kwargs, handle = submitted[0]
        payload = _tty_blocked_payload("alpha")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        modal = page.app.screen
        assert isinstance(modal, InitPlanModal)
        await page.wait_for(lambda _s: len(modal.query("#init-plan-terminal")) > 0)

        await page.press("t")
        await page.pause()

        assert run_calls == [
            (["sase", "init", "-p", "alpha"], {"cwd": Path.home(), "check": False})
        ]
        assert suspend.enters == 1
        assert suspend.exits == 1
        assert page.app.screen is not modal
        assert len(submitted) == 1
        assert "Returned from terminal init for alpha" in pane._status_message


async def test_terminal_valve_unsupported_suspend_notifies_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from textual.app import SuspendNotSupported

    _patch_panes(monkeypatch)
    async with AcePage() as page:
        submitted = _install_submit(page)
        notices: list[tuple[str, str]] = []
        original_notify = page.app.notify

        def capture(message: str, **kwargs: Any) -> None:
            notices.append((message, str(kwargs.get("severity", "information"))))
            original_notify(message, **kwargs)

        page.app.notify = capture  # type: ignore[method-assign]

        def fail_suspend() -> Any:
            raise SuspendNotSupported()

        monkeypatch.setattr(page.app, "suspend", fail_suspend)
        run_calls: list[Any] = []
        monkeypatch.setattr(
            "sase.ace.tui.modals.projects_pane_init_actions.subprocess.run",
            lambda *a, **kw: run_calls.append((a, kw)),
        )
        _center, pane = await _open_projects(page)

        await page.press("i")
        await page.pause()
        args, kwargs, handle = submitted[0]
        payload = _tty_blocked_payload("alpha")
        kwargs["on_complete"](_completion(handle.proc_id, payload))
        await page.expect_modal("InitPlanModal")
        modal = page.app.screen
        await page.wait_for(lambda _s: len(modal.query("#init-plan-terminal")) > 0)

        await page.press("t")
        await page.pause()

        assert run_calls == []
        assert any(severity == "error" for _message, severity in notices)
        assert "Could not run" in pane._status_message
