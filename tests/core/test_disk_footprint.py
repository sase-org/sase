"""Tests for SASE disk-footprint inventory."""

from __future__ import annotations

import json
import os
import subprocess
from types import SimpleNamespace
from dataclasses import dataclass
from pathlib import Path

from sase.core.disk_footprint import collect_disk_footprint, run_disk_reap
from sase.core.disk_footprint_models import DiskReapResult, DiskReapStep
from sase.core.disk_footprint_inventory import cargo_stray_rows
from sase.core.disk_footprint_utils import InventoryScanBudget
from sase.core.disk_footprint_reap import managed_tmp_reap_step
from sase.procs import ProcLogRetentionResult


@dataclass(frozen=True)
class _ProjectInfo:
    project: str
    project_key: str
    root_dir: str
    cleanup_ttl_days: int
    primary_workspace_dir: str | None = None
    share_git_objects: bool = True


@dataclass(frozen=True)
class _Issue:
    project: str
    message: str


@dataclass(frozen=True)
class _Inventory:
    projects: tuple[_ProjectInfo, ...]
    issues: tuple[_Issue, ...] = ()


@dataclass(frozen=True)
class _ProcRuntimeRetentionStub:
    runtime_root: Path
    apply: bool
    scanned: int
    selected: int
    removed: int
    skipped: int
    errors: int
    reclaimable_bytes: int
    reclaimed_bytes: int
    capped: bool

    def describe(self) -> str:
        suffix = " (removal budget reached)" if self.capped else ""
        verb = "removed" if self.apply else "would remove"
        return (
            f"{verb} {self.removed if self.apply else self.selected} proc runtime "
            f"dir(s) under {self.runtime_root}; scanned={self.scanned}, "
            f"reclaimable={self.reclaimable_bytes}, reclaimed={self.reclaimed_bytes}"
            f"{suffix}"
        )


def _write(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_collect_disk_footprint_attributes_owned_paths_and_strays(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    managed = tmp_path / "managed-tmp"
    sase_home = tmp_path / ".sase"
    projects = sase_home / "projects"
    workspace_root = tmp_path / "workspaces" / "proj"
    core = tmp_path / "sase-core"

    _write(managed / "cargo-targets" / "agent" / "build.o", "build")
    _write(sase_home / "procs" / "runtime" / "proc-1" / "state", "runtime")
    _write(sase_home / "cache" / "rust-prebuild" / "sets" / "a", "cache")
    _write(projects / "proj" / "artifacts" / "ace-run" / "202609" / "run", "run")
    _write(workspace_root / "sase_10" / "file", "workspace")
    _write(core / "Cargo.toml", "[workspace]\n")
    _write(core / "target" / "uv-tool-py" / "deps" / "lib", "deps")
    _write(
        core
        / "target"
        / "uv-tool-py"
        / "build"
        / "dev-update"
        / "incremental"
        / "session",
        "incremental",
    )

    stray = home / "forgotten-cargo-target"
    _write(stray / ".rustc_info.json", "{}")
    _write(stray / "debug" / "obj", "orphan")
    repo_target = home / "repo" / "target"
    _write(home / "repo" / ".git" / "HEAD", "ref: main\n")
    _write(repo_target / ".rustc_info.json", "{}")

    monkeypatch.setattr("sase.core.disk_footprint.managed_tmpdir_root", lambda: managed)
    monkeypatch.setattr("sase.core.disk_footprint.sase_home", lambda: sase_home)
    monkeypatch.setattr("sase.core.disk_footprint.sase_projects_dir", lambda: projects)
    monkeypatch.setattr(
        "sase.core.disk_footprint.procs_dir", lambda: sase_home / "procs"
    )
    monkeypatch.setattr("sase.core.disk_footprint._resolve_sase_core_dir", lambda: core)

    report = collect_disk_footprint(
        home=home,
        workspace_inventory_fn=lambda **_kwargs: _Inventory(
            projects=(
                _ProjectInfo(
                    project="SASE",
                    project_key="proj",
                    root_dir=str(workspace_root),
                    cleanup_ttl_days=14,
                ),
            )
        ),
    )

    rows_by_path = {Path(row.path): row for row in report.rows}
    assert rows_by_path[managed / "cargo-targets"].owner == "managed_tmp_reaper"
    assert rows_by_path[projects / "proj" / "artifacts" / "ace-run"].owner == (
        "artifact_run_retention"
    )
    assert rows_by_path[workspace_root].owner == "workspace_cleanup_and_compact"
    assert rows_by_path[stray].status == "unowned"
    assert repo_target not in rows_by_path
    assert all(row.owner and row.horizon for row in report.rows)


def test_collect_disk_footprint_uses_configured_managed_tmp_horizons(
    tmp_path: Path,
    monkeypatch,
) -> None:
    managed = tmp_path / "managed-tmp"
    sase_home = tmp_path / ".sase"
    _write(managed / "muse-prompts" / "prompt", "prompt")
    monkeypatch.setattr("sase.core.disk_footprint.managed_tmpdir_root", lambda: managed)
    monkeypatch.setattr("sase.core.disk_footprint.sase_home", lambda: sase_home)
    monkeypatch.setattr(
        "sase.core.disk_footprint.procs_dir", lambda: sase_home / "procs"
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint.sase_projects_dir",
        lambda: sase_home / "projects",
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_inventory.current_managed_tmp_horizons",
        lambda: {"muse-prompts": 7 * 24 * 3600},
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_inventory.get_managed_tmp_handoff_horizon_seconds",
        lambda: 3 * 24 * 3600,
    )
    monkeypatch.setattr("sase.core.disk_footprint._resolve_sase_core_dir", lambda: None)

    report = collect_disk_footprint(
        include_strays=False,
        tree_size_fn=lambda _path: 0,
        workspace_inventory_fn=lambda **_kwargs: _Inventory(projects=()),
    )

    row = next(row for row in report.rows if row.path == str(managed / "muse-prompts"))
    assert row.horizon == "7d"


def test_workspace_inventory_failures_remain_visible(
    tmp_path: Path,
    monkeypatch,
) -> None:
    managed = tmp_path / "managed-tmp"
    sase_home = tmp_path / ".sase"
    monkeypatch.setattr("sase.core.disk_footprint.managed_tmpdir_root", lambda: managed)
    monkeypatch.setattr("sase.core.disk_footprint.sase_home", lambda: sase_home)
    monkeypatch.setattr(
        "sase.core.disk_footprint.procs_dir", lambda: sase_home / "procs"
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint.sase_projects_dir",
        lambda: sase_home / "projects",
    )
    monkeypatch.setattr("sase.core.disk_footprint._resolve_sase_core_dir", lambda: None)

    def fail_inventory(**_kwargs):
        raise RuntimeError("registry offline")

    report = collect_disk_footprint(
        include_strays=False,
        tree_size_fn=lambda _path: 0,
        workspace_inventory_fn=fail_inventory,
    )

    row = next(row for row in report.rows if row.name == "<workspace inventory>")
    assert row.coverage == "unresolved"
    assert report.coverage_status == "partial"
    assert report.unresolved_owner_coverage
    assert any(
        "registry offline" in diagnostic for diagnostic in report.scan_diagnostics
    )


def test_overlapping_workspace_and_primary_rows_count_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_root = tmp_path / "workspaces" / "proj"
    primary = workspace_root / "primary"
    monkeypatch.setattr(
        "sase.core.disk_footprint.managed_tmpdir_root", lambda: tmp_path / "managed"
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint.sase_home", lambda: tmp_path / ".sase"
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint.procs_dir", lambda: tmp_path / ".sase" / "procs"
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint.sase_projects_dir",
        lambda: tmp_path / ".sase" / "projects",
    )
    monkeypatch.setattr("sase.core.disk_footprint._resolve_sase_core_dir", lambda: None)

    def sizes(path: Path) -> int:
        if path == workspace_root:
            return 100
        if path == primary:
            return 40
        return 0

    report = collect_disk_footprint(
        include_strays=False,
        tree_size_fn=sizes,
        workspace_inventory_fn=lambda **_kwargs: _Inventory(
            projects=(
                _ProjectInfo(
                    project="SASE",
                    project_key="proj",
                    root_dir=str(workspace_root),
                    primary_workspace_dir=str(primary),
                    cleanup_ttl_days=14,
                    share_git_objects=True,
                ),
            )
        ),
    )

    rows_by_path = {Path(row.path): row for row in report.rows if row.path}
    assert rows_by_path[workspace_root].exclusive_size_bytes == 60
    assert rows_by_path[primary].exclusive_size_bytes == 40
    assert rows_by_path[primary].overlap_parent_path == str(workspace_root)
    assert report.logical_total_bytes == 140
    assert report.total_bytes == 100


def test_cargo_stray_scan_shares_a_bounded_listing_budget(tmp_path: Path) -> None:
    home = tmp_path / "home"
    for index in range(20):
        _write(home / f"wide-{index}" / "target" / ".rustc_info.json", "{}")

    _rows, visited, truncated = cargo_stray_rows(
        home,
        excludes=(),
        tree_size_fn=lambda _path: 0,
        budget=InventoryScanBudget(max_nodes=4, max_seconds=60.0),
    )

    assert truncated is True
    assert visited <= 2


def test_disk_reap_proc_preview_uses_runtime_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        "sase.core.disk_footprint._managed_tmp_reap_step",
        lambda *, apply, **_kwargs: DiskReapStep(
            owner="managed_tmp_reaper",
            mode="dry_run" if not apply else "apply",
            summary="tmp",
        ),
    )

    def fake_sweep(**kwargs):
        assert kwargs["apply"] is False
        return _ProcRuntimeRetentionStub(
            runtime_root=Path("/tmp/runtime"),
            apply=False,
            scanned=12,
            selected=3,
            removed=0,
            skipped=9,
            errors=0,
            reclaimable_bytes=1234,
            reclaimed_bytes=0,
            capped=True,
        )

    monkeypatch.setattr(
        "sase.core.disk_footprint.sweep_orphan_proc_runtime_dirs",
        fake_sweep,
    )

    result = run_disk_reap(
        apply=False,
        include_artifact_runs=False,
        include_workspace_compact=False,
    )

    proc_step = next(
        step for step in result.steps if step.owner == "proc_runtime_sweep"
    )
    assert proc_step.reclaimed_bytes == 1234
    assert "would remove 3 proc runtime dir(s)" in proc_step.summary


def test_managed_tmp_reap_step_reports_age_only_bytes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    managed = tmp_path / "managed"
    stale = managed / "editors" / "note.md"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"x" * 512)
    ancient = 1_800_000_000.0 - 400 * 24 * 3600
    os.utime(stale, (ancient, ancient))
    monkeypatch.setattr(
        "sase.core.managed_tmp_reaper.managed_tmpdir_root", lambda: managed
    )

    step = managed_tmp_reap_step(
        apply=False,
        filesystem_available_bytes=64 * 1024**3,
    )

    assert stale.exists()
    assert step.reclaimed_bytes == 512


def test_managed_tmp_reap_step_uses_classifier_floor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    managed = tmp_path / "managed"
    managed.mkdir()
    policy = SimpleNamespace(free_bytes=8 * 1024, warn_free_bytes=16 * 1024)

    def fake_reap_managed_tmpdir(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            root=managed,
            apply=False,
            scanned=0,
            selected=0,
            removed=0,
            selected_bytes=0,
            removed_bytes=0,
            selected_by_subdir={},
            removed_by_subdir={},
            deindexed=0,
            capped=False,
            ordinary_selected=0,
            ordinary_removed=0,
            ordinary_reclaimable_bytes=0,
            ordinary_reclaimed_bytes=0,
            launch_selected=0,
            launch_removed=0,
            launch_reclaimable_bytes=0,
            launch_reclaimed_bytes=0,
            pressure_selected=0,
            pressure_removed=0,
            pressure_reclaimable_bytes=0,
            pressure_reclaimed_bytes=0,
            pressure_trigger=None,
            pressure_root_size_bytes=0,
            pressure_available_bytes=policy.free_bytes,
            pressure_recovery_available_bytes=policy.warn_free_bytes,
            pressure_effective_min_age_seconds=None,
            skipped=0,
            failed=0,
            incomplete_observations=0,
            skip_reasons=(),
            removal_errors=(),
            describe=lambda: "nothing stale",
        )

    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.managed_tmpdir_root",
        lambda: managed,
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.filesystem_pressure_policy",
        lambda **_kwargs: policy,
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.reap_managed_tmpdir",
        fake_reap_managed_tmpdir,
    )

    step = managed_tmp_reap_step(apply=False)

    assert captured["root"] == managed
    assert captured["filesystem_available_bytes"] == 8 * 1024
    assert captured["pressure_min_available_bytes"] == 16 * 1024
    assert captured["pressure_recovery_available_bytes"] == 16 * 1024
    assert step.details["pressure_available_bytes"] == 8 * 1024


def test_proc_reap_apply_includes_pruned_runtime_effects(monkeypatch) -> None:
    from sase.core.disk_footprint_reap import proc_runtime_reap_step

    pruned = _ProcRuntimeRetentionStub(
        runtime_root=Path("/tmp/runtime"),
        apply=True,
        scanned=1,
        selected=1,
        removed=1,
        skipped=0,
        errors=0,
        reclaimable_bytes=10,
        reclaimed_bytes=10,
        capped=False,
    )
    orphan = _ProcRuntimeRetentionStub(
        runtime_root=Path("/tmp/runtime"),
        apply=True,
        scanned=2,
        selected=2,
        removed=2,
        skipped=0,
        errors=1,
        reclaimable_bytes=20,
        reclaimed_bytes=15,
        capped=True,
    )

    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.prune_procs",
        lambda: SimpleNamespace(runtime_retention=pruned),
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.sweep_orphan_proc_runtime_dirs",
        lambda *, apply: orphan,
    )

    step = proc_runtime_reap_step(apply=True)

    assert step.reclaimed_bytes == 25
    assert step.changed is True
    assert step.exit_code == 1
    assert step.details["removed"] == 3
    assert step.details["errors"] == 1
    assert len(step.details["phases"]) == 2


def test_reap_result_uses_core_outcome_for_partial_failure() -> None:
    result = DiskReapResult(
        apply=True,
        project=None,
        steps=(
            DiskReapStep(
                owner="workspace_compact",
                mode="apply",
                summary="changed before failure",
                reclaimed_bytes=512,
                changed=True,
                owner_error="workspace JSON reported errors",
            ),
            DiskReapStep(
                owner="managed_tmp_reaper",
                mode="apply",
                summary="active scratch protected",
                protective_skip="active scratch",
            ),
        ),
    )

    payload = result.to_json_dict()

    assert result.failed is True
    assert result.changed is True
    assert result.reclaimed_bytes == 512
    assert payload["status"] == "failed"
    assert payload["cleanup_outcome"]["known_reclaimed_bytes"] == 512
    assert payload["cleanup_outcome"]["protective_skips"] == 1


def test_managed_tmp_reap_failure_is_a_step_and_group_continues(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from sase.core import disk_footprint_reap as reap

    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.managed_tmp_reap_step",
        managed_tmp_reap_step,
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.managed_tmpdir_root",
        lambda: tmp_path / "managed",
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.reap_managed_tmpdir",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("scratch broken")),
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.proc_runtime_reap_step",
        lambda *, apply: DiskReapStep(
            owner="proc_runtime_sweep",
            mode="apply" if apply else "dry_run",
            summary="proc ok",
        ),
    )

    result = reap.run_disk_reap(
        apply=True,
        include_artifact_runs=False,
        include_workspace_compact=False,
        filesystem_available_bytes=1,
        managed_tmp_pressure_min_available_bytes=1,
        managed_tmp_pressure_recovery_available_bytes=1,
    )

    assert [step.owner for step in result.steps] == [
        "managed_tmp_reaper",
        "proc_runtime_sweep",
    ]
    assert result.steps[0].owner_error is not None
    assert result.failed is True


def test_workspace_discovery_failure_is_not_empty_success(monkeypatch) -> None:
    from sase.core.disk_footprint_reap import workspace_compact_steps

    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.collect_workspace_inventory",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("registry offline")),
    )

    steps = workspace_compact_steps(
        apply=False,
        project=None,
        subprocess_run=subprocess.run,
    )

    assert len(steps) == 1
    assert steps[0].mode == "error"
    assert "registry offline" in steps[0].summary
    assert "no workspace projects found" not in steps[0].summary


def test_workspace_json_errors_fail_but_preserve_effects() -> None:
    from sase.core.disk_footprint_reap import workspace_compact_steps

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["sase", "workspace", "compact"],
            returncode=0,
            stdout=json.dumps(
                {
                    "rows": [{"status": "compacted"}],
                    "errors": 1,
                    "reclaimed_bytes": 4096,
                    "changed": True,
                }
            ),
            stderr="",
        )

    step = workspace_compact_steps(
        apply=True,
        project="gh_sase-org__sase",
        subprocess_run=fake_run,
    )[0]

    result = DiskReapResult(apply=True, project=None, steps=(step,))
    assert step.changed is True
    assert step.reclaimed_bytes == 4096
    assert step.owner_error == "workspace compact reported 1 error(s)"
    assert result.failed is True
    assert result.changed is True
    assert result.reclaimed_bytes == 4096


def test_workspace_invalid_json_field_type_is_failed_step() -> None:
    from sase.core.disk_footprint_reap import workspace_compact_steps

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=["sase", "workspace", "compact"],
            returncode=0,
            stdout=json.dumps({"rows": [], "errors": "one"}),
            stderr="",
        )

    step = workspace_compact_steps(
        apply=False,
        project="gh_sase-org__sase",
        subprocess_run=fake_run,
    )[0]

    assert step.mode == "error"
    assert step.invalid_result == "errors must be an integer"
    assert DiskReapResult(apply=False, project=None, steps=(step,)).failed is True


def test_proc_reap_preserves_pruned_effects_when_orphan_sweep_fails(
    monkeypatch,
) -> None:
    from sase.core.disk_footprint_reap import proc_runtime_reap_step

    log_retention = ProcLogRetentionResult(
        log_root=Path("/tmp/proc-logs"),
        apply=True,
        scanned=2,
        selected=1,
        removed=1,
        skipped=1,
        reclaimable_bytes=10,
        reclaimed_bytes=10,
    )
    runtime_retention = _ProcRuntimeRetentionStub(
        runtime_root=Path("/tmp/runtime"),
        apply=True,
        scanned=1,
        selected=1,
        removed=1,
        skipped=0,
        errors=0,
        reclaimable_bytes=20,
        reclaimed_bytes=20,
        capped=False,
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.prune_procs",
        lambda: SimpleNamespace(
            log_retention=log_retention,
            runtime_retention=runtime_retention,
            state_retention=SimpleNamespace(errors=()),
        ),
    )

    def fake_sweep(*, apply):
        if not apply:
            return _ProcRuntimeRetentionStub(
                runtime_root=Path("/tmp/runtime"),
                apply=False,
                scanned=0,
                selected=0,
                removed=0,
                skipped=0,
                errors=0,
                reclaimable_bytes=0,
                reclaimed_bytes=0,
                capped=False,
            )
        raise RuntimeError("late orphan failure")

    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.sweep_orphan_proc_runtime_dirs",
        fake_sweep,
    )

    step = proc_runtime_reap_step(apply=True)

    assert step.changed is True
    assert step.reclaimed_bytes == 30
    assert step.exit_code == 1
    assert "late orphan failure" in step.owner_error
    assert step.details["removed"] == 2
    assert step.details["reclaimed_bytes"] == 30
    assert len(step.details["phases"]) == 2


def test_artifact_reap_apply_errors_fail_step(monkeypatch) -> None:
    from sase.core.disk_footprint_reap import artifact_run_reap_step

    plan = SimpleNamespace(
        sources_unavailable=(),
        reclaimable_bytes=32,
        counts=SimpleNamespace(selected=1, empty_out_of_range_shards=0),
    )
    execution = SimpleNamespace(
        removed_runs=0,
        removed_empty_shards=0,
        bytes_reclaimed=0,
        deindexed=0,
        skipped=(),
        errors=("permission denied",),
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.collect_ace_run_retention_protections",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.plan_ace_run_retention",
        lambda *_args, **_kwargs: plan,
    )
    monkeypatch.setattr(
        "sase.core.disk_footprint_reap.apply_ace_run_retention",
        lambda _plan: execution,
    )

    step = artifact_run_reap_step(apply=True, project=None)

    assert step.mode == "blocked"
    assert step.exit_code == 1
    assert step.failed is True
    assert step.details["errors"] == ["permission denied"]
    assert step.details["preview_reclaimable_bytes"] == 32
