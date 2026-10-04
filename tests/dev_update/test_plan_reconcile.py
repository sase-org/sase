"""Tests for dev-update reconciliation planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.dev_update.plan import plan_dev_update
import sase.dev_update._plan_roots as plan_mod
from sase.uv_tool.receipt import parse_receipt
from sase.version._git import GitUpstreamStatus
from tests.dev_update._plan_helpers import probe, record, status


@pytest.fixture(autouse=True)
def _stub_fetch_git_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_mod, "fetch_git_upstream", lambda _status: None)


def test_plan_dev_update_dedupes_roots_and_builds_uv_reconcile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "sase"
    plugin_root = host_root / "plugins" / "github"
    plugin_root.mkdir(parents=True)
    host = record("sase", role="host", source_root=str(host_root))
    plugin = record("sase-github", role="plugin", source_root=str(plugin_root))
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
        plan_mod, "classify_git_upstream", lambda _root: status(str(host_root))
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

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
    host = record("sase", role="host", source_root=str(host_root))
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
        plan_mod, "classify_git_upstream", lambda _root: status(str(host_root))
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

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
    host = record("sase", role="host", source_root=str(host_root))
    core = record("sase-core-rs", role="core", source_root="/repo/sase-core")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: status("/repo/sase-core")
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update([core], host_record=host, tool_python="/tool/bin/python")

    assert [step.kind for step in plan.reconcile_steps] == [
        "rust_prebuild_install",
        "rust_dev_install",
        "rust_health_check",
    ]
    assert plan.reconcile_steps[0].command == (
        "/tool/bin/python",
        "-m",
        "sase.dev_update.prebuild",
        "consume",
        "--core-root",
        "/repo/sase-core",
        "--host-root",
        str(host_root),
        "--python",
        "/tool/bin/python",
        "--profile",
        "dev-update",
    )
    assert plan.reconcile_steps[0].cwd == str(host_root)
    assert plan.reconcile_steps[0].env == {"SASE_RUST_DEV_PROFILE": "dev-update"}
    assert plan.reconcile_steps[1].command == ("just", "rust-dev-install-uv-tool")
    assert plan.reconcile_steps[1].cwd == str(host_root)
    assert plan.reconcile_steps[1].env == {"SASE_RUST_DEV_PROFILE": "dev-update"}
    # A prebuild miss makes this step a full cargo build, which routinely
    # outruns the generic dev-update command timeout.
    assert plan.reconcile_steps[1].timeout_seconds == 3600.0
    assert plan.reconcile_steps[0].timeout_seconds is None
    assert plan.reconcile_steps[2].command == (
        "/tool/bin/python",
        "-c",
        "import importlib.metadata as m; import sase_core_rs; "
        "print(m.version('sase-core-rs'))",
    )
    assert plan.reconcile_steps[2].repair_command == (
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
    host = record("sase", role="host", source_root=str(host_root))
    core = record("sase-core-rs", role="core", source_root="/repo/sase-core")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: status("/repo/sase-core")
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update([core], host_record=host, tool_python="/tool/bin/python")

    assert plan.reconcile_steps[0].env == {"SASE_RUST_DEV_PROFILE": "release"}
    assert plan.reconcile_steps[1].env == {"SASE_RUST_DEV_PROFILE": "release"}


def test_plan_dev_update_rebuilds_current_dev_core_after_uv_tool_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = record("sase", role="host", source_root="/repo/sase")
    core = record("sase-core-rs", role="core", source_root="/repo/sase-core")
    statuses = {
        "/repo/sase": status("/repo/sase", behind=2),
        "/repo/sase-core": status("/repo/sase-core", behind=0),
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
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update(
        [host, core],
        host_record=host,
        receipt=receipt,
        tool_python="/tool/bin/python",
    )

    assert [step.kind for step in plan.reconcile_steps] == [
        "uv_tool_install",
        "rust_prebuild_install",
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
    host = record("sase", role="host", source_root=str(host_root))
    stale_core = record(
        "sase-core-rs",
        role="core",
        source_root=None,
        display_version="0.4.1",
        install_type="wheel",
    )
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: status(str(host_root))
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)
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
        "rust_prebuild_install",
        "rust_dev_install",
        "rust_health_check",
    ]


def test_plan_dev_update_stale_core_without_checkout_or_cargo_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "sase"
    host_root.mkdir()
    host = record("sase", role="host", source_root=str(host_root))
    stale_core = record(
        "sase-core-rs",
        role="core",
        source_root=None,
        display_version="0.4.1",
        install_type="wheel",
    )
    monkeypatch.setattr(
        plan_mod,
        "classify_git_upstream",
        lambda _root: status(str(host_root), behind=0),
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)
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
    host = record("sase", role="host", source_root=None)
    core = record("sase-core-rs", role="core", source_root="/repo/sase-core")
    monkeypatch.setattr(
        plan_mod, "classify_git_upstream", lambda _root: status("/repo/sase-core")
    )
    monkeypatch.setattr(plan_mod, "probe_git_metadata_at_ref", probe)

    plan = plan_dev_update([core], host_record=host, tool_python="/tool/bin/python")

    assert [step.kind for step in plan.reconcile_steps] == [
        "rust_prebuild_install",
        "rust_dev_install",
        "rust_health_check",
    ]
    assert plan.reconcile_steps[0].available is False
    assert plan.reconcile_steps[0].reason == "host checkout source root unavailable"
    assert plan.reconcile_steps[1].available is False
    assert plan.reconcile_steps[1].reason == "host checkout source root unavailable"
