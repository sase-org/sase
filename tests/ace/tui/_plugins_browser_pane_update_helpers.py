"""Shared fixtures for plugin-browser update tests."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals import plugins_browser_pane as pbp
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
from sase.version._models import VersionPackageRecord
from tests.ace.tui._plugins_browser_pane_helpers import _NOW, _entry


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
