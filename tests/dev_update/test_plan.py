"""Tests for dev-update planning."""

from __future__ import annotations

import subprocess
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


@pytest.fixture(autouse=True)
def _stub_fetch_git_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", lambda _status: None)


def test_plan_dev_update_fetches_before_classifying_root_actionability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _record("sase", role="host", source_root="/repo")
    fetched = False
    classify_calls: list[tuple[str, bool]] = []

    def classify(root: Path) -> GitUpstreamStatus:
        classify_calls.append((str(root), fetched))
        return _status("/repo", behind=2 if fetched else 0)

    def fetch(status: GitUpstreamStatus) -> None:
        nonlocal fetched
        assert status.behind == 0
        fetched = True

    monkeypatch.setattr(plan_mod, "classify_git_upstream", classify)
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fetch)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([host], host_record=host)

    assert classify_calls == [("/repo", False), ("/repo", True)]
    assert plan.roots[0].status == "actionable"
    assert plan.roots[0].behind == 2
    assert [pkg.record.name for pkg in plan.actionable] == ["sase"]


def test_plan_dev_update_fetches_once_per_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _record("sase", role="host", source_root="/repo")
    plugin = _record("sase-github", role="plugin", source_root="/repo/plugins/github")
    fetches: list[GitUpstreamStatus] = []

    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: _status("/repo")
    )
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fetches.append)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([host, plugin], host_record=host)

    assert len(fetches) == 1
    assert plan.roots[0].packages == ("sase", "sase-github")


def test_plan_dev_update_reuses_only_explicitly_refreshed_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _record("sase", role="host", source_root="/repo/fresh")
    plugin = _record("sase-github", role="plugin", source_root="/repo/other")
    fetched: set[str] = set()
    classified: list[str] = []

    def classify(root: Path) -> GitUpstreamStatus:
        root_text = str(root)
        classified.append(root_text)
        behind = 2 if root_text == "/repo/fresh" or root_text in fetched else 0
        return _status(root_text, behind=behind)

    def fetch(status: GitUpstreamStatus) -> None:
        fetched.add(status.root)

    monkeypatch.setattr(plan_mod, "classify_git_upstream", classify)
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fetch)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update(
        [host, plugin],
        host_record=host,
        already_refreshed_roots={"/repo/fresh"},
    )

    assert fetched == {"/repo/other"}
    assert classified == ["/repo/fresh", "/repo/other", "/repo/other"]
    assert [root.status for root in plan.roots] == ["actionable", "actionable"]
    assert [root.behind for root in plan.roots] == [2, 2]


def test_plan_dev_update_fetch_failure_degrades_honestly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _record("sase", role="host", source_root="/repo/current")
    behind = _record("sase-github", role="plugin", source_root="/repo/behind")
    statuses = {
        "/repo/current": _status("/repo/current", behind=0),
        "/repo/behind": _status("/repo/behind", behind=3),
    }

    def classify(root: Path) -> GitUpstreamStatus:
        return statuses[str(root)]

    def fail_fetch(_status: GitUpstreamStatus) -> None:
        raise subprocess.CalledProcessError(1, ["git"], stderr="network down")

    monkeypatch.setattr(plan_mod, "classify_git_upstream", classify)
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fail_fetch)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([current, behind], host_record=current)

    current_root = plan.roots[0]
    behind_root = plan.roots[1]
    assert current_root.status == "skipped"
    assert "fetch failed; using cached upstream ref: network down" in (
        current_root.reason
    )
    assert current_root.fetch_error == "network down"
    assert plan.packages[0].fetch_error == "network down"
    assert behind_root.status == "actionable"
    assert behind_root.reason == "behind upstream by 3 commit(s)"
    assert behind_root.fetch_error == "network down"
    assert plan.packages[1].status == "actionable"
    assert plan.packages[1].fetch_error == "network down"


def test_plan_dev_update_does_not_fetch_no_upstream_or_detached_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_upstream = _record("sase", role="host", source_root="/repo/no-upstream")
    detached = _record("sase-core-rs", role="core", source_root="/repo/detached")
    statuses = {
        "/repo/no-upstream": _status(
            "/repo/no-upstream", upstream=None, ahead=None, behind=None
        ),
        "/repo/detached": _status(
            "/repo/detached",
            detached=True,
            upstream=None,
            ahead=None,
            behind=None,
        ),
    }

    def classify(root: Path) -> GitUpstreamStatus:
        return statuses[str(root)]

    def fail_fetch(_status: GitUpstreamStatus) -> None:
        raise AssertionError("no-upstream and detached roots must not fetch")

    monkeypatch.setattr(plan_mod, "classify_git_upstream", classify)
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", fail_fetch)
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([no_upstream, detached], host_record=no_upstream)

    assert plan.actionable == ()
    assert [root.fetch_error for root in plan.roots] == [None, None]
    assert "no upstream" in plan.roots[0].reason
    assert "detached" in plan.roots[1].reason


def test_plan_dev_update_dedupes_roots_and_builds_uv_reconcile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "sase"
    plugin_root = host_root / "plugins" / "github"
    plugin_root.mkdir(parents=True)
    host = _record("sase", role="host", source_root=str(host_root))
    plugin = _record("sase-github", role="plugin", source_root=str(plugin_root))
    receipt = parse_receipt(
        f"""
        [tool]
        requirements = [
            {{ name = "sase", editable = "{host_root}" }},
            {{ name = "sase-github", editable = "{plugin_root}" }},
        ]
        """
    )
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: _status(str(host_root))
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([host, plugin], host_record=host, receipt=receipt)

    assert len(plan.roots) == 1
    assert plan.roots[0].packages == ("sase", "sase-github")
    assert [pkg.record.name for pkg in plan.actionable] == ["sase", "sase-github"]
    assert plan.skipped == ()
    assert len(plan.reconcile_steps) == 1
    assert plan.reconcile_steps[0].kind == "uv_tool_install"
    command = plan.reconcile_steps[0].command
    assert command[:9] == (
        "uv",
        "tool",
        "install",
        "--color",
        "never",
        "--editable",
        str(host_root),
        "--with-editable",
        str(plugin_root),
    )
    assert command[-2] == "--overrides"
    overrides_path = Path(command[-1])
    assert overrides_path.read_text(encoding="utf-8") == (
        f"-e {host_root}\n-e {plugin_root}\nsase-core-rs\n"
    )


def test_plan_dev_update_marks_uv_reconcile_unavailable_for_missing_plugin_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "sase"
    host_root.mkdir()
    missing = tmp_path / "missing-plugin"
    host = _record("sase", role="host", source_root=str(host_root))
    receipt = parse_receipt(
        f"""
        [tool]
        requirements = [
            {{ name = "sase", editable = "{host_root}" }},
            {{ name = "sase-github", editable = "{missing}" }},
        ]
        """
    )
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: _status(str(host_root))
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([host], host_record=host, receipt=receipt)

    step = plan.reconcile_steps[0]
    assert step.kind == "uv_tool_install"
    assert step.available is False
    assert step.command == ()
    assert "plugin 'sase-github'" in str(step.reason)
    assert str(missing) in str(step.reason)
    assert "sase plugin uninstall sase-github" in str(step.reason)


def test_plan_dev_update_core_only_uses_rust_rebuild(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("SASE_RUST_DEV_PROFILE", raising=False)
    host_root = tmp_path / "sase"
    host_root.mkdir()
    (host_root / "pyproject.toml").write_text(
        """
        [project]
        dependencies = [
            "sase-core-rs>=0.3.2,<0.4.0",
        ]
        """,
        encoding="utf-8",
    )
    host = _record("sase", role="host", source_root=str(host_root))
    core = _record("sase-core-rs", role="core", source_root="/repo/sase-core")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: _status("/repo/sase-core")
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([core], host_record=host, tool_python="/tool/bin/python")

    assert [step.kind for step in plan.reconcile_steps] == [
        "rust_dev_install",
        "rust_health_check",
    ]
    assert plan.reconcile_steps[0].command == ("just", "rust-dev-install-uv-tool")
    assert plan.reconcile_steps[0].cwd == str(host_root)
    assert plan.reconcile_steps[0].env == {"SASE_RUST_DEV_PROFILE": "dev-update"}
    assert plan.reconcile_steps[1].command == (
        "/tool/bin/python",
        "-c",
        "import importlib.metadata as m; import sase_core_rs; "
        "print(m.version('sase-core-rs'))",
    )
    assert plan.reconcile_steps[1].repair_command == (
        "uv",
        "pip",
        "install",
        "--python",
        "/tool/bin/python",
        "--force-reinstall",
        "sase-core-rs<0.4.0,>=0.3.2",
    )


def test_plan_dev_update_threads_rust_dev_profile_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_RUST_DEV_PROFILE", "release")
    host_root = tmp_path / "sase"
    host_root.mkdir()
    (host_root / "pyproject.toml").write_text(
        """
        [project]
        dependencies = [
            "sase-core-rs>=0.3.2,<0.4.0",
        ]
        """,
        encoding="utf-8",
    )
    host = _record("sase", role="host", source_root=str(host_root))
    core = _record("sase-core-rs", role="core", source_root="/repo/sase-core")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: _status("/repo/sase-core")
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([core], host_record=host, tool_python="/tool/bin/python")

    assert plan.reconcile_steps[0].env == {"SASE_RUST_DEV_PROFILE": "release"}


def test_plan_dev_update_rebuilds_current_dev_core_after_uv_tool_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _record("sase", role="host", source_root="/repo/sase")
    core = _record("sase-core-rs", role="core", source_root="/repo/sase-core")
    statuses = {
        "/repo/sase": _status("/repo/sase", behind=2),
        "/repo/sase-core": _status("/repo/sase-core", behind=0),
    }
    receipt = parse_receipt(
        """
        [tool]
        requirements = [
            { name = "sase", editable = "/repo/sase" },
        ]
        """
    )
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda root: statuses[str(root)]
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update(
        [host, core],
        host_record=host,
        receipt=receipt,
        tool_python="/tool/bin/python",
    )

    assert [step.kind for step in plan.reconcile_steps] == [
        "uv_tool_install",
        "rust_dev_install",
        "rust_health_check",
    ]


def test_plan_dev_update_restores_stale_core_from_buildable_checkout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "sase"
    core_root = tmp_path / "sase-core"
    host_root.mkdir()
    core_root.mkdir()
    (host_root / "pyproject.toml").write_text(
        """
        [project]
        dependencies = [
            "sase-core-rs>=0.3.2,<0.4.0",
        ]
        """,
        encoding="utf-8",
    )
    (core_root / "Cargo.toml").write_text(
        '[workspace.package]\nversion = "0.5.0"\n',
        encoding="utf-8",
    )
    host = _record("sase", role="host", source_root=str(host_root))
    stale_core = _record(
        "sase-core-rs",
        role="core",
        source_root=None,
        display_version="0.4.1",
        install_type="wheel",
    )
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: _status(str(host_root))
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)
    monkeypatch.setattr(plan_mod.shutil, "which", lambda _name: "/usr/bin/cargo")
    monkeypatch.delenv("SASE_CORE_DIR", raising=False)

    plan = plan_dev_update(
        [host],
        host_record=host,
        tool_python="/tool/bin/python",
        stale_core_record=stale_core,
    )

    core_plans = [pkg for pkg in plan.packages if pkg.record.role == "core"]
    assert len(core_plans) == 1
    assert core_plans[0].status == "actionable"
    assert "published wheel" in core_plans[0].reason
    assert core_plans[0].current_version == "0.4.1"
    assert core_plans[0].latest_version == "0.5.0+4.gbbbbbbbbb"
    assert core_plans[0].git_root is None
    assert [step.kind for step in plan.reconcile_steps] == [
        "uv_tool_install",
        "rust_dev_install",
        "rust_health_check",
    ]


def test_plan_dev_update_stale_core_without_checkout_or_cargo_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "sase"
    host_root.mkdir()
    host = _record("sase", role="host", source_root=str(host_root))
    stale_core = _record(
        "sase-core-rs",
        role="core",
        source_root=None,
        display_version="0.4.1",
        install_type="wheel",
    )
    monkeypatch.setattr(
        plan_mod,
        "classify_git_upstream",
        lambda _root: _status(str(host_root), behind=0),
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)
    monkeypatch.delenv("SASE_CORE_DIR", raising=False)

    monkeypatch.setattr(plan_mod.shutil, "which", lambda _name: "/usr/bin/cargo")
    no_checkout = plan_dev_update(
        [host], host_record=host, stale_core_record=stale_core
    )

    core_root = tmp_path / "sase-core"
    core_root.mkdir()
    (core_root / "Cargo.toml").write_text(
        '[workspace.package]\nversion = "0.5.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(plan_mod.shutil, "which", lambda _name: None)
    no_cargo = plan_dev_update([host], host_record=host, stale_core_record=stale_core)

    for plan, expected in ((no_checkout, "no local"), (no_cargo, "cargo is not")):
        core_plans = [pkg for pkg in plan.packages if pkg.record.role == "core"]
        assert len(core_plans) == 1
        assert core_plans[0].status == "skipped"
        assert expected in core_plans[0].reason
        assert plan.reconcile_steps == ()


def test_plan_dev_update_core_rebuild_steps_need_host_source_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = _record("sase", role="host", source_root=None)
    core = _record("sase-core-rs", role="core", source_root="/repo/sase-core")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: _status("/repo/sase-core")
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", _probe)

    plan = plan_dev_update([core], host_record=host, tool_python="/tool/bin/python")

    assert [step.kind for step in plan.reconcile_steps] == [
        "rust_dev_install",
        "rust_health_check",
    ]
    assert plan.reconcile_steps[0].available is False
    assert plan.reconcile_steps[0].reason == "host checkout source root unavailable"


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
