"""Tests for doctor resource checks."""

from __future__ import annotations

from collections import namedtuple
from datetime import datetime
from pathlib import Path

import pytest

from sase.axe.config import AxeConfig
from sase.doctor.checks_resources import (
    _DISK_ERROR_FREE_BYTES,
    _DISK_WARN_FREE_BYTES,
    _INOTIFY_MIN_USER_INSTANCES,
    _check_ace_run_watches,
    _check_chezmoi,
    _check_disk_free,
    _check_inotify,
    _check_ulimits,
    resource_check_specs,
)
from sase.doctor.runner import DoctorContext

_DiskUsage = namedtuple("_DiskUsage", "total used free")


def _context(cwd: Path, sase_home: Path) -> DoctorContext:
    return DoctorContext(
        cwd=cwd,
        project=None,
        sase_home=sase_home,
        env={},
    )


def _disk_usage(free_by_path: dict[str, int]):
    def fake_disk_usage(path: str) -> _DiskUsage:
        free = free_by_path[path]
        total = 10 * 1024**3
        return _DiskUsage(total=total, used=total - free, free=free)

    return fake_disk_usage


def test_resource_check_specs_registers_chezmoi_as_deep(tmp_path: Path) -> None:
    specs = resource_check_specs(_context(tmp_path, tmp_path / ".sase"))

    assert [spec.id for spec in specs] == [
        "resources.disk_free",
        "resources.chezmoi",
        "resources.ulimits",
        "resources.inotify",
        "resources.ace_run_watches",
    ]
    assert [spec.id for spec in specs if spec.deep] == [
        "resources.chezmoi",
        "resources.ulimits",
        "resources.inotify",
    ]


def test_disk_free_ok_includes_workspace_root_and_sase_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    sase_home = tmp_path / ".sase"
    sase_home.mkdir()
    monkeypatch.setattr(
        "sase.doctor.checks_resources.workspace_root_path",
        lambda _context: (workspace_root, None),
    )

    check = _check_disk_free(
        _context(tmp_path, sase_home),
        disk_usage_fn=_disk_usage(
            {
                str(workspace_root): _DISK_WARN_FREE_BYTES,
                str(sase_home): _DISK_WARN_FREE_BYTES + 1,
            }
        ),
    )

    assert check.id == "resources.disk_free"
    assert check.group == "resources"
    assert check.status == "OK"
    assert [row["label"] for row in check.data["paths"]] == [
        "workspace_root",
        "sase_home",
    ]
    assert check.data["paths"][1]["role"] == "secondary"


def test_disk_free_warns_below_three_gib(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    sase_home = tmp_path / ".sase"
    sase_home.mkdir()
    monkeypatch.setattr(
        "sase.doctor.checks_resources.workspace_root_path",
        lambda _context: (workspace_root, None),
    )

    check = _check_disk_free(
        _context(tmp_path, sase_home),
        disk_usage_fn=_disk_usage(
            {
                str(workspace_root): _DISK_WARN_FREE_BYTES - 1,
                str(sase_home): _DISK_WARN_FREE_BYTES + 1,
            }
        ),
    )

    assert check.status == "WARN"
    assert "less than 3 GB" in check.summary
    assert "sase workspace cleanup" in check.next_steps[0]
    assert "hundreds of MB" in check.next_steps[1]


def test_disk_free_errors_below_one_gib(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    sase_home = tmp_path / ".sase"
    sase_home.mkdir()
    monkeypatch.setattr(
        "sase.doctor.checks_resources.workspace_root_path",
        lambda _context: (workspace_root, None),
    )

    check = _check_disk_free(
        _context(tmp_path, sase_home),
        disk_usage_fn=_disk_usage(
            {
                str(workspace_root): _DISK_ERROR_FREE_BYTES - 1,
                str(sase_home): _DISK_WARN_FREE_BYTES + 1,
            }
        ),
    )

    assert check.status == "ERROR"
    assert "less than 1 GB" in check.summary
    assert check.data["paths"][0]["status"] == "ERROR"


def test_disk_free_reports_workspace_root_resolution_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_resources.workspace_root_path",
        lambda _context: (None, "RuntimeError: bad workspace config"),
    )

    check = _check_disk_free(_context(tmp_path, tmp_path / ".sase"))

    assert check.status == "ERROR"
    assert "could not be checked" in check.summary
    assert check.data["workspace_error"] == "RuntimeError: bad workspace config"


def test_chezmoi_skips_when_disabled_and_no_source_tree(tmp_path: Path) -> None:
    check = _check_chezmoi(
        use_chezmoi=False,
        source_home=tmp_path / "missing" / "home",
        command_resolver=lambda _command: None,
    )

    assert check.id == "resources.chezmoi"
    assert check.group == "resources"
    assert check.status == "SKIP"
    assert "disabled" in check.summary
    assert check.data["source_exists"] is False


def test_chezmoi_errors_when_enabled_but_command_missing(tmp_path: Path) -> None:
    source_home = tmp_path / "chezmoi" / "home"
    source_home.mkdir(parents=True)
    (source_home / "dot_config").mkdir()

    check = _check_chezmoi(
        use_chezmoi=True,
        source_home=source_home,
        command_resolver=lambda _command: None,
    )

    assert check.status == "ERROR"
    assert "command is missing" in check.summary
    assert "Install `chezmoi`" in check.next_steps[0]
    assert check.data["command_found"] is False


def test_chezmoi_warns_for_source_tree_without_command_when_disabled(
    tmp_path: Path,
) -> None:
    source_home = tmp_path / "chezmoi" / "home"
    source_home.mkdir(parents=True)
    (source_home / "dot_config").mkdir()

    check = _check_chezmoi(
        use_chezmoi=False,
        source_home=source_home,
        command_resolver=lambda _command: None,
    )

    assert check.status == "WARN"
    assert "source tree exists" in check.details[0]
    assert any("Install `chezmoi`" in step for step in check.next_steps)


def test_chezmoi_ok_when_enabled_with_command_and_source(tmp_path: Path) -> None:
    source_home = tmp_path / "chezmoi" / "home"
    source_home.mkdir(parents=True)
    (source_home / "dot_config").mkdir()

    check = _check_chezmoi(
        use_chezmoi=True,
        source_home=source_home,
        command_resolver=lambda _command: "/usr/bin/chezmoi",
    )

    assert check.status == "OK"
    assert "look usable" in check.summary
    assert check.data["source_entry_count"] == 1


class _FakeResource:
    RLIMIT_NOFILE = 1
    RLIMIT_NPROC = 2
    RLIM_INFINITY = -1


def test_ulimits_ok_when_soft_limits_meet_concurrency_floor() -> None:
    limits = {
        _FakeResource.RLIMIT_NOFILE: (2048, 4096),
        _FakeResource.RLIMIT_NPROC: (256, 512),
    }

    check = _check_ulimits(
        axe_config=AxeConfig(max_hook_runners=3, max_agent_runners=3),
        getrlimit_fn=lambda constant: limits[constant],
        resource_module=_FakeResource,
    )

    assert check.id == "resources.ulimits"
    assert check.group == "resources"
    assert check.status == "OK"
    assert check.data["configured_runner_concurrency"] == 6
    assert check.data["floors"]["nofile"] == 1024


def test_ulimits_warns_when_soft_limits_are_below_floor() -> None:
    limits = {
        _FakeResource.RLIMIT_NOFILE: (512, 4096),
        _FakeResource.RLIMIT_NPROC: (64, 512),
    }

    check = _check_ulimits(
        axe_config=AxeConfig(max_hook_runners=4, max_agent_runners=4),
        getrlimit_fn=lambda constant: limits[constant],
        resource_module=_FakeResource,
    )

    assert check.status == "WARN"
    assert "2 resource limit(s)" in check.summary
    assert any("RLIMIT_NOFILE soft limit 512" in detail for detail in check.details)
    assert any("RLIMIT_NPROC soft limit 64" in detail for detail in check.details)
    assert "LimitNOFILE" in check.next_steps[0]


def test_ulimits_skips_when_resource_module_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.doctor.checks_resources.import_resource_module",
        lambda: None,
    )

    check = _check_ulimits()

    assert check.status == "SKIP"
    assert check.data["available"] is False


def _write_inotify_limits(proc_dir: Path, **values: int) -> None:
    proc_dir.mkdir(parents=True, exist_ok=True)
    for name, value in values.items():
        (proc_dir / name).write_text(f"{value}\n", encoding="utf-8")


def test_inotify_skips_on_non_linux(tmp_path: Path) -> None:
    check = _check_inotify(platform="darwin", proc_dir=tmp_path)

    assert check.status == "SKIP"
    assert "Linux-only" in check.summary


def test_inotify_ok_when_limits_meet_ace_floors(tmp_path: Path) -> None:
    _write_inotify_limits(
        tmp_path,
        max_user_watches=8192,
        max_user_instances=_INOTIFY_MIN_USER_INSTANCES,
        max_queued_events=16384,
    )

    check = _check_inotify(platform="linux", proc_dir=tmp_path)

    assert check.status == "OK"
    assert check.data["limits"][0]["value"] == 8192


def test_inotify_warns_when_watch_or_instance_limits_are_low(tmp_path: Path) -> None:
    _write_inotify_limits(
        tmp_path,
        max_user_watches=256,
        max_user_instances=2,
        max_queued_events=1024,
    )

    check = _check_inotify(platform="linux", proc_dir=tmp_path)

    assert check.status == "WARN"
    assert "force ACE event refresh back to polling" in check.summary
    assert any("max_user_watches=256" in detail for detail in check.details)
    assert any("max_user_instances=2" in detail for detail in check.details)


_PINNED_ACE_NOW = datetime(2026, 8, 28, 12, 0, 0)


def _ace_run_project(sase_home: Path, project: str) -> Path:
    workflow = sase_home / "projects" / project / "artifacts" / "ace-run"
    workflow.mkdir(parents=True, exist_ok=True)
    return workflow


def test_ace_run_watches_ok_for_healthy_project(tmp_path: Path) -> None:
    sase_home = tmp_path / ".sase"
    workflow = _ace_run_project(sase_home, "proj")
    (workflow / "202608" / "28").mkdir(parents=True)
    (workflow / "202607" / "31").mkdir(parents=True)

    check = _check_ace_run_watches(
        _context(tmp_path, sase_home),
        now=_PINNED_ACE_NOW,
        enabled_projects=("proj",),
    )

    assert check.id == "resources.ace_run_watches"
    assert check.status == "OK"
    assert check.data["future_month_shard_count"] == 0
    assert check.data["projects"][0]["live_month_watched"] is True
    assert check.data["projects"][0]["live_day_watched"] is True


def test_ace_run_watches_warns_when_future_shards_can_starve(
    tmp_path: Path,
) -> None:
    sase_home = tmp_path / ".sase"
    workflow = _ace_run_project(sase_home, "proj")
    (workflow / "202608" / "28").mkdir(parents=True)
    (workflow / "213601" / "09").mkdir(parents=True)
    (workflow / "213510" / "22").mkdir(parents=True)

    check = _check_ace_run_watches(
        _context(tmp_path, sase_home),
        now=_PINNED_ACE_NOW,
        enabled_projects=("proj",),
    )

    assert check.status == "WARN"
    assert check.data["future_month_shard_count"] == 2
    assert "213601" not in " ".join(check.data["projects"][0]["selected_watch_paths"])
    assert any("future-dated" in step for step in check.next_steps)
    assert check.data["projects"][0]["live_month_watched"] is True


def test_ace_run_watches_warns_when_live_shard_is_not_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / ".sase"
    workflow = _ace_run_project(sase_home, "proj")
    (workflow / "202608" / "28").mkdir(parents=True)
    monkeypatch.setattr(
        "sase.doctor.checks_resources_ace_run_watches."
        "iter_startup_ace_run_shard_watch_paths",
        lambda _workflow_dir, **_kwargs: (),
    )

    check = _check_ace_run_watches(
        _context(tmp_path, sase_home),
        now=_PINNED_ACE_NOW,
        enabled_projects=("proj",),
    )

    assert check.status == "WARN"
    assert check.data["starved_projects"] == ("proj",)
    assert "outside ACE's startup watch budget" in check.summary
