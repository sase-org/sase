"""SASE-wide update action tests for the Plugins pane."""

from __future__ import annotations

from datetime import datetime
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from textual.widgets import Static

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals import plugins_browser_dev_update as pbdu
from sase.ace.tui.modals import plugins_browser_sase_update as pbsu
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.ace.tui.task_queue import TaskInfo, TaskQueue
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.updates.incoming_commits import (
    CommitSummary,
    IncomingCommits,
    RepoIncomingCommits,
)
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.receipt import parse_receipt
from sase.uv_tool.render import PlannedPackage
from sase.uv_tool.render import UpdateOutcome as SaseUpdateOutcome
from sase.uv_tool.render import UpdateSummary
from sase.uv_tool.runner import ChangeKind
from sase.version.inventory import RuntimeVersionInventory
from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _not_uv_tool,
    _open_plugins_pane,
    _patch_catalog,
    _patch_catalog_recording,
    _patch_other_panes,
    _render,
    _spy_notify,
)
from tests.ace.tui._plugins_browser_pane_update_helpers import (
    _dev_plan,
    _dev_result,
    _editable_catalog,
    _patch_sase_update_managed_fallback,
    _version_record,
)


def _multi_root_dev_plan() -> DevUpdatePlan:
    base = _dev_plan()
    roots = []
    packages = []
    roles = {"sase": "host", "sase-core": "core", "sase-github": "plugin"}
    for index, name in enumerate(("sase", "sase-core", "sase-github"), start=1):
        git_root = f"/repo/{name}"
        roots.append(
            replace(
                base.roots[0],
                git_root=git_root,
                packages=(name,),
                behind=index,
            )
        )
        packages.append(
            replace(
                base.packages[0],
                record=_version_record(name, role=roles[name]),
                git_root=git_root,
                behind=index,
            )
        )
    return replace(base, packages=tuple(packages), roots=tuple(roots))


def _mixed_preview(plan: DevUpdatePlan) -> pbp._DevUpdatePreview:
    return pbp._DevUpdatePreview(
        plan=plan,
        subject="sase",
        managed_argv=(
            "uv",
            "tool",
            "install",
            "--editable",
            "/repo/sase",
            "--upgrade-package",
            "sase-core-rs",
        ),
        managed_packages=(
            PlannedPackage(
                name="sase-core-rs",
                role="dependency",
                current_version="0.4.0",
            ),
        ),
    )


def _core_summary(*, changed: bool) -> UpdateSummary:
    return UpdateSummary(
        outcomes=(
            SaseUpdateOutcome(
                name="sase-core-rs",
                role="dependency",
                kind=ChangeKind.UPGRADED if changed else ChangeKind.UNCHANGED,
                old_version="0.4.0" if changed else None,
                new_version="0.4.1" if changed else "0.4.0",
            ),
        )
    )


def _task(
    task_id: str,
    task_type: str,
    status: str = "running",
) -> TaskInfo:
    return TaskInfo(
        task_id=task_id,
        task_type=task_type,
        cl_name=f"{task_type}-cl",
        project_file="/tmp/project.sase",
        status=status,
        message=f"{task_type} task",
        started_at=datetime(2026, 7, 9, 12, 0, 0),
    )


def _queue(*tasks: TaskInfo) -> TaskQueue:
    queue = TaskQueue()
    for task in tasks:
        queue._tasks[task.task_id] = task
    return queue


class _FailingTaskQueue:
    def get_all(self) -> list[TaskInfo]:
        raise RuntimeError("queue unavailable")


def test_restart_blockers_include_running_tracked_background_tasks() -> None:
    blockers = pbsu._running_background_tasks(
        SimpleNamespace(
            _task_queue=_queue(
                _task("run-sync", "sync"),
                _task("run-mail", "mail"),
                _task("run-launch", "launch"),
                _task("done-sync", "sync", status="success"),
                _task("done-mail", "mail", status="error"),
                _task("done-update", "sase-update", status="success"),
            )
        )
    )

    assert {task.task_id for task in blockers} == {
        "run-sync",
        "run-mail",
        "run-launch",
    }


def test_restart_blockers_fail_open_when_queue_cannot_be_inspected() -> None:
    assert (
        pbsu._running_background_tasks(SimpleNamespace(_task_queue=_FailingTaskQueue()))
        == []
    )
    assert (
        pbsu._running_background_tasks(
            SimpleNamespace(_task_queue=SimpleNamespace(get_all=None))
        )
        == []
    )
    assert pbsu._running_background_tasks(SimpleNamespace()) == []


def test_sase_preview_carries_transitive_wheel_core_as_managed_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    host = _version_record("sase", role="host")
    github = _version_record("sase-github", role="plugin")
    telegram = _version_record("sase-telegram", role="plugin")
    core = replace(
        _version_record("sase-core-rs", role="core"),
        display_version="0.4.0",
        distribution_version="0.4.0",
        source_version=None,
        source_root=None,
        install_type="wheel",
    )
    inventory = RuntimeVersionInventory(
        executable="sase",
        python_executable="/tool/bin/python",
        python_version="3.14",
        packages=(host, core, github, telegram),
    )
    receipt = parse_receipt(
        """
[tool]
requirements = [
    { name = "sase", editable = "/repo/sase" },
    { name = "sase-github", editable = "/repo/sase-github" },
    { name = "sase-telegram", editable = "/repo/sase-telegram" },
]
"""
    )
    seen: list[str] = []

    def _plan(records: tuple[Any, ...], **_kwargs: Any) -> DevUpdatePlan:
        seen.extend(record.name for record in records)
        return _dev_plan(status="skipped")

    monkeypatch.setattr(
        pbdu, "collect_runtime_version_inventory", lambda **_kw: inventory
    )
    monkeypatch.setattr(pbdu, "plan_dev_update", _plan)
    monkeypatch.setattr(
        "sase.main.update_routing.write_editable_overrides",
        lambda _requirements: tmp_path / "editable-overrides.txt",
    )

    preview = pbdu.make_sase_dev_update_preview(receipt)

    assert preview.error is None
    assert seen == ["sase", "sase-github", "sase-telegram"]
    assert preview.managed_packages == (
        PlannedPackage(
            name="sase-core-rs",
            role="dependency",
            current_version="0.4.0",
        ),
    )
    assert preview.managed_argv[-2:] == ("--upgrade-package", "sase-core-rs")


async def test_updates_pane_sase_update_opens_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        assert [v.key for v in modal._variants] == ["update-sase"]
        assert modal._incoming_commits_loader is not None
        preview = _render(modal._preview_renderable())
        assert "uv tool upgrade sase" in preview
        assert "Upgrades sase core + every installed plugin" in preview


async def test_updates_pane_sase_update_disabled_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._uv_tool = _not_uv_tool()
        messages = _spy_notify(monkeypatch, pane)
        pane.action_update_sase()
        await page.pause()
        assert messages and messages[0][1] == "warning"
        assert "uv tool install" in messages[0][0]


async def test_updates_pane_sase_update_confirm_executes_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    executed: list[object | None] = []

    def _fake_run(install: object | None) -> tuple[UpdateSummary, float]:
        executed.append(install)
        return (
            UpdateSummary(
                outcomes=(
                    SaseUpdateOutcome(
                        name="sase",
                        role="primary",
                        kind=ChangeKind.UPGRADED,
                        old_version="0.5.0",
                        new_version="0.6.0",
                    ),
                )
            ),
            0.2,
        )

    monkeypatch.setattr(pbp, "run_sase_update_summary", _fake_run)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        timer_callbacks: list[Any] = []

        def _set_timer(delay: float, callback: Any) -> object:
            assert delay == 1.0
            timer_callbacks.append(callback)
            return SimpleNamespace(stop=lambda: None)

        monkeypatch.setattr(page.app, "set_timer", _set_timer)
        background = page.app._task_queue.submit(
            "sync",
            "feature_a",
            "/tmp/project.sase",
            display_name="sync feature_a",
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(executed) and bool(timer_callbacks))
        assert restart_calls == []
        assert calls  # initial load happened; changed update does not need a reload
        assert any(
            "restart queued until 1 background task finishes" in message
            for message, _severity in messages
        )

        page.app._task_queue.complete(
            background.task_id,
            success=True,
            message="sync done",
            output="sync done",
        )
        timer_callbacks.pop(0)()
        await page.pause()

        assert restart_calls == [True]
        assert any("restarting ACE" in message for message, _severity in messages)
        assert not any("will be stopped" in message for message, _severity in messages)
        receipt = update_receipt.read_and_clear_pending_update_toast()
        assert receipt is not None
        assert receipt.primary is not None
        assert receipt.primary.old == "0.5.0"
        assert receipt.primary.new == "0.6.0"


async def test_updates_pane_sase_update_noop_closes_without_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    executed: list[int] = []

    def _fake_run(_install: object | None) -> tuple[UpdateSummary, float]:
        executed.append(1)
        return (UpdateSummary(outcomes=()), 0.1)

    monkeypatch.setattr(pbp, "run_sase_update_summary", _fake_run)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        # Confirming closes the Admin Center immediately; the no-op task then
        # completes on the main TUI without a restart.
        await page.wait_for(lambda _s: bool(executed) and bool(messages))
        await page.expect_no_modal()
        assert restart_calls == []
        assert messages == [
            (
                "Nothing to update: sase, core, and plugins are current.",
                "error",
            )
        ]


async def test_updates_pane_sase_update_dev_preview_and_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)
    plan = _dev_plan()
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt: pbp._DevUpdatePreview(plan=plan, subject="sase"),
    )
    executed: list[DevUpdatePlan] = []

    def _fake_execute(plan_arg: DevUpdatePlan) -> DevUpdateResult:
        executed.append(plan_arg)
        return _dev_result(plan_arg)

    monkeypatch.setattr(pbp, "_execute_tui_dev_update", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        assert modal._incoming_commits_loader is not None
        preview = _render(modal._preview_renderable())
        assert "fetch + fast-forward origin/main" in preview
        assert "Reinstall uv-tool editable Python packages" in preview
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(executed) and bool(restart_calls))
        assert executed == [plan]
        assert restart_calls == [True]
        receipt = update_receipt.read_and_clear_pending_update_toast()
        assert receipt is not None
        assert receipt.plugins
        assert receipt.plugins[0].name == "sase-github"
        assert receipt.plugins[0].old == "0.1.0+1.gabc123def"
        assert receipt.plugins[0].new == "0.1.0+2.gdef456abc"


async def test_updates_pane_sase_dev_update_shows_all_commit_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _multi_root_dev_plan()
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt: pbp._DevUpdatePreview(plan=plan, subject="sase"),
    )

    def _fake_fetch_groups(
        specs: tuple[tuple[str, object], ...],
        **_kwargs: object,
    ) -> tuple[RepoIncomingCommits, ...]:
        return tuple(
            RepoIncomingCommits(
                label,
                IncomingCommits(
                    total=1,
                    commits=(CommitSummary("abc1234", f"{label} update"),),
                    source="git",
                ),
            )
            for label, _spec in specs
        )

    monkeypatch.setattr(pbp, "_fetch_incoming_commit_groups", _fake_fetch_groups)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        assert modal._incoming_commits_loader is not None

        body = modal.query_one("#plugin-action-commits-body", Static)
        await page.wait_for(
            lambda _s: (
                "↑ sase — 1 incoming commit" in _render(body.content)
                and "↑ sase-core — 1 incoming commit" in _render(body.content)
                and "↑ sase-github — 1 incoming commit" in _render(body.content)
            )
        )


async def test_updates_pane_sase_update_dev_skipped_reason_is_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan(status="skipped")
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt: pbp._DevUpdatePreview(plan=plan, subject="sase"),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        pane.action_update_sase()

        await page.wait_for(lambda _s: bool(messages))
        assert page.app.screen.__class__.__name__ == "ConfigCenterModal"
        assert messages[0][1] == "error"
        assert "checkout has local changes" in messages[0][0]


async def test_updates_pane_skipped_editables_with_wheel_core_open_mixed_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    preview = _mixed_preview(_dev_plan(status="skipped"))
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt: preview,
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")

        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        rendered = _render(modal._preview_renderable())
        assert "skip sase-github: checkout has local changes" in rendered
        assert "upgrade sase-core-rs from 0.4.0" in rendered
        assert "--upgrade-package sase-core-rs" in rendered
        assert messages == []


async def test_updates_pane_mixed_core_only_success_restarts_once_and_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan(status="skipped")
    preview = _mixed_preview(plan)
    monkeypatch.setattr(pbp, "_make_sase_dev_update_preview", lambda _receipt: preview)
    monkeypatch.setattr(
        pbp,
        "_execute_tui_dev_update",
        lambda plan_arg: _dev_result(plan_arg, changed=False),
    )
    managed_calls: list[tuple[tuple[str, ...], tuple[PlannedPackage, ...]]] = []

    def _fake_managed(
        argv: tuple[str, ...], packages: tuple[PlannedPackage, ...]
    ) -> tuple[UpdateSummary, float]:
        managed_calls.append((argv, packages))
        return _core_summary(changed=True), 0.2

    monkeypatch.setattr(pbp, "run_planned_sase_update_summary", _fake_managed)
    receipt_file = tmp_path / "pending_update_toast.json"
    monkeypatch.setattr(update_receipt, "_PENDING_UPDATE_TOAST_FILE", receipt_file)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(managed_calls) and bool(restart_calls))
        assert restart_calls == [True]
        assert managed_calls == [(preview.managed_argv, preview.managed_packages)]
        receipt = update_receipt.read_and_clear_pending_update_toast()
        assert receipt is not None
        assert receipt.kind == "managed"
        assert receipt.primary is None
        assert receipt.plugins == ()
        assert receipt.dependency_count == 1


async def test_updates_pane_mixed_true_noop_does_not_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan(status="skipped")
    preview = _mixed_preview(plan)
    monkeypatch.setattr(pbp, "_make_sase_dev_update_preview", lambda _receipt: preview)
    monkeypatch.setattr(
        pbp,
        "_execute_tui_dev_update",
        lambda plan_arg: _dev_result(plan_arg, changed=False),
    )
    monkeypatch.setattr(
        pbp,
        "run_planned_sase_update_summary",
        lambda _argv, _packages: (_core_summary(changed=False), 0.1),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(messages))
        assert restart_calls == []
        assert messages == [(pbsu._SASE_UPDATE_NOOP_MESSAGE, "error")]


async def test_updates_pane_mixed_managed_failure_notifies_once_without_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan(status="skipped")
    preview = _mixed_preview(plan)
    monkeypatch.setattr(pbp, "_make_sase_dev_update_preview", lambda _receipt: preview)
    monkeypatch.setattr(
        pbp,
        "_execute_tui_dev_update",
        lambda plan_arg: _dev_result(plan_arg, changed=False),
    )

    def _fail(argv: tuple[str, ...], _packages: tuple[PlannedPackage, ...]) -> None:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="core conflict")

    monkeypatch.setattr(pbp, "run_planned_sase_update_summary", _fail)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(messages))
        assert restart_calls == []
        assert len(messages) == 1
        assert messages[0][1] == "error"
        assert "sase update failed" in messages[0][0]
        assert "core conflict" in messages[0][0]


async def test_updates_pane_mixed_cancel_is_non_mutating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    preview = _mixed_preview(_dev_plan(status="skipped"))
    monkeypatch.setattr(pbp, "_make_sase_dev_update_preview", lambda _receipt: preview)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        submitted: list[int] = []
        monkeypatch.setattr(
            pane, "_submit_combined_update_task", lambda _preview: submitted.append(1)
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_cancel()

        await page.expect_modal("ConfigCenterModal")
        assert submitted == []


async def test_updates_pane_sase_update_managed_confirm_closes_admin_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        submitted: list[int] = []
        monkeypatch.setattr(
            pane, "_submit_sase_update_task", lambda: submitted.append(1)
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        # The task is submitted first, then the Admin Center closes immediately.
        await page.wait_for(lambda _s: bool(submitted))
        await page.expect_no_modal()
        assert submitted == [1]


async def test_updates_pane_sase_update_dev_confirm_closes_admin_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan()
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt: pbp._DevUpdatePreview(plan=plan, subject="sase"),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        submitted: list[int] = []
        monkeypatch.setattr(
            pane,
            "_submit_dev_update_task",
            lambda *_a, **_kw: submitted.append(1),
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(submitted))
        await page.expect_no_modal()
        assert submitted == [1]


async def test_updates_pane_sase_update_cancel_keeps_admin_center_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        submitted: list[int] = []
        monkeypatch.setattr(
            pane, "_submit_sase_update_task", lambda: submitted.append(1)
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_cancel()

        # Cancelling dismisses only the confirm modal; the Admin Center stays.
        await page.expect_modal("ConfigCenterModal")
        assert submitted == []
