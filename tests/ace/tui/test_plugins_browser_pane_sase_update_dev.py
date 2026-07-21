"""Editable-development SASE-wide update tests for the Plugins pane."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from textual.widgets import Static

import sase.dev_update.plan as plan_mod
from sase.ace import update_receipt
from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_dev_update as pbdu
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.plugin_action_confirm_modal import PluginActionConfirmModal
from sase.dev_update.models import DevUpdatePlan, DevUpdateResult
from sase.updates.incoming_commits import (
    CommitSummary,
    IncomingCommits,
    RepoIncomingCommits,
)
from sase.uv_tool.receipt import parse_receipt
from sase.version._git import GitUpstreamStatus
from sase.version._models import GitProbeResult, GitVersionMetadata
from sase.version.inventory import RuntimeVersionInventory
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


def test_sase_preview_routes_transitive_wheel_core_to_dev_restore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dev install plans the wheel core as a dev-leg restore, never managed work."""
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
    seen_kwargs: dict[str, Any] = {}

    def _plan(records: tuple[Any, ...], **kwargs: Any) -> DevUpdatePlan:
        seen.extend(record.name for record in records)
        seen_kwargs.update(kwargs)
        return _dev_plan(status="skipped")

    monkeypatch.setattr(
        pbdu, "collect_runtime_version_inventory", lambda **_kw: inventory
    )
    monkeypatch.setattr(pbdu, "plan_dev_update", _plan)

    preview = pbdu.make_sase_dev_update_preview(receipt)

    assert preview.error is None
    assert seen == ["sase", "sase-github", "sase-telegram"]
    assert seen_kwargs["stale_core_record"] is core
    assert preview.managed_packages == ()
    assert preview.managed_argv == ()


def test_sase_preview_preflights_missing_managed_plugin_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    host = _version_record("sase", role="host")
    inventory = RuntimeVersionInventory(
        executable="sase",
        python_executable="/tool/bin/python",
        python_version="3.14",
        packages=(host,),
    )
    missing = tmp_path / "missing-plugin"
    receipt = parse_receipt(
        f"""
[tool]
requirements = [
    {{ name = "sase", editable = "/repo/sase" }},
    {{ name = "sase-acme", directory = "{missing}" }},
]
"""
    )
    monkeypatch.setattr(
        pbdu, "collect_runtime_version_inventory", lambda **_kw: inventory
    )

    preview = pbdu.make_sase_dev_update_preview(receipt)

    assert preview.plan is None
    assert preview.error is not None
    assert "plugin 'sase-acme'" in preview.error
    assert str(missing) in preview.error
    assert "sase plugin uninstall sase-acme" in preview.error


async def test_updates_pane_manual_update_reuses_load_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh load evidence reaches confirmation without another remote fetch."""
    _patch_other_panes(monkeypatch)
    fresh_root = "/repo/sase"
    _patch_catalog(
        monkeypatch,
        catalog=_editable_catalog(),
        fresh_editable_roots=frozenset({fresh_root}),
    )
    host = _version_record("sase", role="host")
    inventory = RuntimeVersionInventory(
        executable="sase",
        python_executable="/tool/bin/python",
        python_version="3.14",
        packages=(host,),
    )
    monkeypatch.setattr(
        pbdu, "collect_runtime_version_inventory", lambda **_kw: inventory
    )
    classifications: list[str] = []
    fetches: list[str] = []

    def _classify(root: Any) -> GitUpstreamStatus:
        root_text = str(root)
        classifications.append(root_text)
        return GitUpstreamStatus(
            root=root_text,
            upstream="origin/main",
            remote="origin",
            remote_branch="main",
            detached=False,
            dirty=False,
            ahead=0,
            behind=1,
        )

    monkeypatch.setattr(plan_mod, "classify_git_upstream", _classify)
    monkeypatch.setattr(
        plan_mod,
        "fetch_git_upstream",
        lambda status: fetches.append(status.root),
    )
    monkeypatch.setattr(
        plan_mod,
        "probe_git_metadata_at_ref",
        lambda *_a, **_kw: GitProbeResult(
            GitVersionMetadata(
                root=fresh_root,
                commit="def456abcdef456abcdef456abcdef456abcdef4",
                short_commit="def456abc",
                tag="v0.1.0",
                distance=2,
                dirty=False,
            )
        ),
    )
    real_plan = pbdu.plan_dev_update

    def _plan(*args: Any, **kwargs: Any) -> DevUpdatePlan:
        planned = real_plan(*args, **kwargs)
        return replace(planned, reconcile_steps=_dev_plan().reconcile_steps)

    monkeypatch.setattr(pbdu, "plan_dev_update", _plan)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")

        assert fetches == []
        assert classifications == [fresh_root]


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
