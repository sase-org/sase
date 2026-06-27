"""Tests for dev-update planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.dev_update.plan import plan_dev_update
import sase.dev_update.plan as plan_mod
from sase.uv_tool.receipt import parse_receipt
from sase.version._git import GitUpstreamStatus
from sase.version._models import (
    GitProbeResult,
    GitVersionMetadata,
    VersionPackageRecord,
)


def _record(
    name: str,
    *,
    role: str,
    source_root: str | None,
    display_version: str = "0.5.0+1.gaaaaaaaaa",
    install_type: str = "editable",
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,  # type: ignore[arg-type]
        display_version=display_version,
        distribution_version="0.5.0",
        source_version="0.5.0",
        import_module=None,
        import_path=None,
        code_directory=None,
        source_root=source_root,
        distribution_location=None,
        install_type=install_type,  # type: ignore[arg-type]
        git=None,
    )


def _status(
    root: str,
    *,
    dirty: bool = False,
    detached: bool = False,
    upstream: str | None = "origin/main",
    ahead: int | None = 0,
    behind: int | None = 2,
) -> GitUpstreamStatus:
    return GitUpstreamStatus(
        root=root,
        upstream=upstream,
        remote="origin" if upstream else None,
        remote_branch="main" if upstream else None,
        detached=detached,
        dirty=dirty,
        ahead=ahead,
        behind=behind,
    )


def _probe(_root: Path, _ref: str = "HEAD") -> GitProbeResult:
    return GitProbeResult(
        GitVersionMetadata(
            root="/repo",
            commit="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            short_commit="bbbbbbbbb",
            tag="v0.5.0",
            distance=4,
            dirty=False,
        )
    )


def test_plan_dev_update_dedupes_roots_and_builds_uv_reconcile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _record("sase", role="host", source_root="/repo/sase")
    plugin = _record(
        "sase-github", role="plugin", source_root="/repo/sase/plugins/github"
    )
    receipt = parse_receipt(
        """
        [tool]
        requirements = [
            { name = "sase", editable = "/repo/sase" },
            { name = "sase-github", editable = "/repo/sase/plugins/github" },
        ]
        """
    )
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: _status("/repo/sase")
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([host, plugin], host_record=host, receipt=receipt)

    assert len(plan.roots) == 1
    assert plan.roots[0].packages == ("sase", "sase-github")
    assert [pkg.record.name for pkg in plan.actionable] == ["sase", "sase-github"]
    assert plan.skipped == ()
    assert len(plan.reconcile_steps) == 1
    assert plan.reconcile_steps[0].kind == "uv_tool_install"
    assert plan.reconcile_steps[0].command == (
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "--editable",
        "/repo/sase",
        "--with-editable",
        "/repo/sase/plugins/github",
    )


def test_plan_dev_update_core_only_uses_rust_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _record("sase", role="host", source_root="/repo/sase")
    core = _record("sase-core-rs", role="core", source_root="/repo/sase-core")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: _status("/repo/sase-core")
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([core], host_record=host)

    assert [step.kind for step in plan.reconcile_steps] == ["rust_install_uv_tool"]
    assert plan.reconcile_steps[0].command == ("just", "rust-install-uv-tool")
    assert plan.reconcile_steps[0].cwd == "/repo/sase"


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        (_status("/repo", dirty=True), "local changes"),
        (_status("/repo", ahead=1, behind=1), "diverged"),
        (
            _status("/repo", detached=True, upstream=None, ahead=None, behind=None),
            "detached",
        ),
        (_status("/repo", upstream=None, ahead=None, behind=None), "no upstream"),
        (_status("/repo", ahead=0, behind=0), "already current"),
    ],
)
def test_plan_dev_update_skips_non_actionable_roots(
    monkeypatch: pytest.MonkeyPatch,
    status: GitUpstreamStatus,
    reason: str,
) -> None:
    host = _record("sase", role="host", source_root="/repo")
    monkeypatch.setattr(plan_mod, "classify_git_upstream", lambda _root: status)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([host], host_record=host)

    assert plan.actionable == ()
    assert len(plan.skipped) == 1
    assert reason in plan.skipped[0].reason
    assert plan.reconcile_steps == ()


def test_plan_dev_update_unknown_source_root_skips_without_git_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _record("sase", role="host", source_root=None)

    def fail_probe(_root: Path) -> GitUpstreamStatus:
        raise AssertionError("missing source roots must not call git")

    monkeypatch.setattr(plan_mod, "classify_git_upstream", fail_probe)

    plan = plan_dev_update([host], host_record=host)

    assert len(plan.skipped) == 1
    assert "no source root" in plan.skipped[0].reason


def test_plan_dev_update_receipt_absence_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _record("sase", role="host", source_root="/repo/sase")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: _status("/repo/sase")
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([host], host_record=host)

    assert len(plan.reconcile_steps) == 1
    assert plan.reconcile_steps[0].available is False
    assert plan.reconcile_steps[0].reason == "uv tool receipt unavailable"
