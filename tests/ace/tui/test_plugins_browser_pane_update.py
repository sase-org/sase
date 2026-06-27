"""Update action tests for the Plugins pane."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.dev_update.models import (
    DevReconcileStep,
    DevUpdateOutcome,
    DevUpdatePackagePlan,
    DevUpdatePlan,
    DevUpdateResult,
    DevUpdateRootPlan,
)
from sase.plugins.catalog import PluginCatalog
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.plugins.operations import NoPlugins, UpdateOutcome, UpdateReady, UpdateUnknown
from sase.uv_tool.render import UpdateOutcome as SaseUpdateOutcome
from sase.uv_tool.render import UpdateSummary
from sase.uv_tool.runner import ChangeKind, UvChangeSet, UvPackageChange
from sase.version._models import VersionPackageRecord
from tests.ace.tui._plugins_browser_pane_helpers import (
    _NOW,
    _catalog,
    _entry,
    _highlight,
    _not_uv_tool,
    _open_plugins_pane,
    _patch_catalog,
    _patch_catalog_recording,
    _patch_other_panes,
    _render,
    _spy_notify,
    _update_ready,
)


def _version_record(
    name: str = "sase-github", *, role: str = "plugin"
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,  # type: ignore[arg-type]
        display_version="0.1.0+1.gabc123def",
        distribution_version="0.1.0",
        source_version="0.1.0",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root=f"/repo/{name}",
        distribution_location=None,
        install_type="editable",
        git=None,
    )


def _dev_plan(*, status: str = "actionable") -> DevUpdatePlan:
    record = _version_record()
    package = DevUpdatePackagePlan(
        record=record,
        status=status,  # type: ignore[arg-type]
        reason=(
            "behind upstream by 1 commit(s)"
            if status == "actionable"
            else "checkout has local changes"
        ),
        current_version="0.1.0+1.gabc123def",
        latest_version="0.1.0+2.gdef456abc",
        git_root="/repo/sase-github",
        upstream="origin/main",
        remote="origin",
        remote_branch="main",
        behind=1,
    )
    root = DevUpdateRootPlan(
        git_root="/repo/sase-github",
        status=status,  # type: ignore[arg-type]
        reason=package.reason,
        upstream="origin/main",
        remote="origin",
        remote_branch="main",
        packages=("sase-github",),
        behind=1,
    )
    steps: tuple[DevReconcileStep, ...] = ()
    if status == "actionable":
        steps = (
            DevReconcileStep(
                kind="uv_tool_install",
                label="Reinstall uv-tool editable Python packages",
                command=("uv", "tool", "install", "sase"),
            ),
        )
    return DevUpdatePlan(packages=(package,), roots=(root,), reconcile_steps=steps)


def _dev_result(plan: DevUpdatePlan, *, changed: bool = True) -> DevUpdateResult:
    package = plan.packages[0]
    return DevUpdateResult(
        changed=changed,
        outcomes=(
            DevUpdateOutcome(
                record=package.record,
                status="updated" if changed else "skipped",
                reason=package.reason,
                old_version=package.current_version,
                new_version=package.latest_version,
                git_root=package.git_root,
            ),
        ),
    )


def _editable_catalog() -> PluginCatalog:
    github = _entry(
        "github",
        owner="sase-org",
        description="GitHub VCS and workspace provider.",
        installed=InstalledInfo(installed=True, version="0.1.0+1.gabc123def"),
        latest=LatestInfo(
            checked=True,
            version="0.1.0+2.gdef456abc",
            source="editable",
            install_type="editable",
            current_version="0.1.0+1.gabc123def",
            update_available=True,
            state="update_available",
            reason="behind upstream by 1 commit(s)",
        ),
    )
    return PluginCatalog(
        fetched_at=_NOW,
        entries=(github,),
        from_cache=True,
        stale=False,
    )


def _patch_sase_update_managed_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pbp,
        "_make_sase_dev_update_preview",
        lambda _receipt: pbp._DevUpdatePreview(plan=None, subject="sase"),
    )


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
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)
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
        monkeypatch.setattr(page.app, "_count_running_tasks", lambda: 2)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(executed) and bool(restart_calls))
        assert restart_calls == [True]
        assert calls  # initial load happened; changed update does not need a reload
        assert any("restarting ACE" in message for message, _severity in messages)
        assert any("2 background tasks" in message for message, _severity in messages)


async def test_updates_pane_sase_update_noop_refreshes_without_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    _patch_sase_update_managed_fallback(monkeypatch)

    def _fake_run(_install: object | None) -> tuple[UpdateSummary, float]:
        return (UpdateSummary(outcomes=()), 0.1)

    monkeypatch.setattr(pbp, "run_sase_update_summary", _fake_run)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        initial = len(calls)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()

        await page.wait_for(lambda _s: len(calls) > initial)
        assert restart_calls == []


async def test_updates_pane_sase_update_dev_preview_and_restart(
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
        preview = _render(modal._preview_renderable())
        assert "fetch + fast-forward origin/main" in preview
        assert "Reinstall uv-tool editable Python packages" in preview
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(executed) and bool(restart_calls))
        assert executed == [plan]
        assert restart_calls == [True]


async def test_plugins_pane_update_opens_preview_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight(pane, "github")  # installed, update available
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        # Update offers a single variant; no index/git source toggle.
        assert [v.key for v in modal._variants] == ["update"]
        preview = _render(modal._preview_renderable())
        assert "--upgrade-package" in preview
        assert "Upgrades sase-github" in preview
        assert "sase core stays pinned" in preview


async def test_plugins_pane_update_hint_gated_on_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        # Installed + update available: emphasized hint, plus update-all.
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        assert "u update ↑" in pane._hints()
        assert "U update-all" in pane._hints()
        # Installed but current: hint present, not emphasized.
        _highlight(pane, "telegram")
        await page.wait_for(lambda _s: pane._highlighted_name() == "telegram")
        telegram_hints = pane._hints()
        assert "u update" in telegram_hints
        assert "↑" not in telegram_hints
        # Not installed: no single-update hint (install is offered instead).
        _highlight(pane, "nvim")
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        assert "u update" not in pane._hints()


async def test_plugins_pane_update_not_installed_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "nvim")  # not installed
        pane.action_update()
        await page.pause()
        assert not planned  # short-circuited before planning
        assert messages and "not installed" in messages[0][0]
        assert messages[0][1] == "warning"


async def test_plugins_pane_update_disabled_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    planned: list[int] = []
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: planned.append(1))
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._uv_tool = _not_uv_tool()
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed + update available
        pane.action_update()
        await page.pause()
        assert pane._update_plan_worker is None
        assert not planned
        assert messages and messages[0][1] == "warning"
        assert "uv tool install" in messages[0][0]
        # Update affordances are dropped from the hints.
        assert "u update" not in pane._hints()
        assert "U update-all" not in pane._hints()
        # Update-all is gated too.
        pane.action_update_all()
        await page.pause()
        assert not planned


async def test_plugins_pane_update_all_no_plugins_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=NoPlugins()),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        pane.action_update_all()
        await page.wait_for(lambda _s: bool(messages))
        assert "No plugins are installed" in messages[0][0]


async def test_plugins_pane_update_unknown_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    preview = pbp._UpdatePreview(plan=UpdateUnknown(query="github", suggestions=()))
    monkeypatch.setattr(pbp, "_plan_update_preview", lambda *a, **k: preview)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")  # installed -> proceeds to plan
        pane.action_update()
        await page.wait_for(lambda _s: bool(messages))
        message, severity = messages[0]
        assert "No plugin named 'github'" in message
        assert severity == "error"


async def test_plugins_pane_update_confirm_executes_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    calls = _patch_catalog_recording(monkeypatch, catalog=_catalog())
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    executed: list[UpdateReady] = []

    def _fake_execute(plan_arg: UpdateReady, **_kw: object) -> UpdateOutcome:
        executed.append(plan_arg)
        return UpdateOutcome(
            plan=plan_arg,
            change_set=UvChangeSet(
                changes=(
                    UvPackageChange(
                        name="sase-github",
                        kind=ChangeKind.UPGRADED,
                        old_version="1.2.0",
                        new_version="1.3.0",
                    ),
                )
            ),
            elapsed=1.0,
        )

    monkeypatch.setattr(pbp, "execute_update", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        restart_calls: list[bool] = []
        monkeypatch.setattr(
            page.app,
            "_restart_tui",
            lambda *, restart_axe: restart_calls.append(restart_axe),
        )
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        modal.action_confirm()
        # The tracked task runs execute_update, then restarts ACE + axe.
        await page.wait_for(lambda _s: bool(executed) and bool(restart_calls))
        assert executed[0].targets == ("sase-github",)
        assert not executed[0].all_plugins
        assert restart_calls == [True]
        assert calls  # initial load happened


async def test_plugins_pane_editable_update_uses_dev_preview_and_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan()
    monkeypatch.setattr(
        pbp,
        "_make_plugin_dev_update_preview",
        lambda query, *, all_plugins, receipt: pbp._DevUpdatePreview(
            plan=plan,
            subject=str(query),
        ),
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
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        assert "v0.1.0+1.gabc123def → v0.1.0+2.gdef456abc  dev" in (
            pane._row_text(pane._current_entry()).plain  # type: ignore[arg-type]
        )
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        preview = _render(modal._preview_renderable())
        assert "dev update" in preview
        assert "fetch + fast-forward origin/main" in preview
        modal.action_confirm()

        await page.wait_for(lambda _s: bool(executed) and bool(restart_calls))
        assert executed == [plan]
        assert restart_calls == [True]


async def test_plugins_pane_editable_update_skipped_reason_toasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_editable_catalog())
    plan = _dev_plan(status="skipped")
    monkeypatch.setattr(
        pbp,
        "_make_plugin_dev_update_preview",
        lambda query, *, all_plugins, receipt: pbp._DevUpdatePreview(
            plan=plan,
            subject=str(query),
        ),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        messages = _spy_notify(monkeypatch, pane)
        _highlight(pane, "github")
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()

        await page.wait_for(lambda _s: bool(messages))
        assert messages[0][1] == "warning"
        assert "checkout has local changes" in messages[0][0]


async def test_plugins_pane_update_all_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    plan = _update_ready(("github", "telegram"), all_plugins=True)
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )
    executed: list[UpdateReady] = []

    def _fake_execute(plan_arg: UpdateReady, **_kw: object) -> UpdateOutcome:
        executed.append(plan_arg)
        return UpdateOutcome(plan=plan_arg, change_set=UvChangeSet(), elapsed=0.3)

    monkeypatch.setattr(pbp, "execute_update", _fake_execute)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_update_all()
        await page.expect_modal("PluginActionConfirmModal")
        modal = page.app.screen
        assert isinstance(modal, PluginActionConfirmModal)
        # A single variant; the preview names every installed plugin.
        assert [v.key for v in modal._variants] == ["update"]
        preview = _render(modal._preview_renderable())
        assert "every installed plugin" in preview
        modal.action_confirm()
        await page.wait_for(lambda _s: bool(executed))
        assert executed[0].all_plugins
