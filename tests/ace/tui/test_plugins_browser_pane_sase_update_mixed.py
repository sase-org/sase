"""Mixed editable/wheel SASE-wide update tests for the Plugins pane."""

from __future__ import annotations

import pytest

from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals import plugins_browser_sase_update as pbsu
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.dev_update.models import DevUpdatePlan
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.render import PlannedPackage
from sase.uv_tool.render import UpdateOutcome as SaseUpdateOutcome
from sase.uv_tool.render import UpdateSummary
from sase.uv_tool.runner import ChangeKind
from tests.ace.tui._plugins_browser_pane_helpers import (
    _open_plugins_pane,
    _patch_catalog,
    _patch_other_panes,
    _render,
    _spy_notify,
)
from tests.ace.tui._plugins_browser_pane_update_helpers import (
    _dev_plan,
    _dev_result,
    _editable_catalog,
)


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
            pane, "_submit_combined_update_proc", lambda _preview: submitted.append(1)
        )
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_cancel()

        await page.expect_modal("ConfigCenterModal")
        assert submitted == []
