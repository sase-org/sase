"""Tests for doctor resource checks."""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path

import pytest

from sase.doctor.checks_resources import (
    _DISK_ERROR_FREE_BYTES,
    _DISK_WARN_FREE_BYTES,
    _check_chezmoi,
    _check_disk_free,
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
    ]
    assert specs[1].deep is True


def test_disk_free_ok_includes_workspace_root_and_sase_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    sase_home = tmp_path / ".sase"
    sase_home.mkdir()
    monkeypatch.setattr(
        "sase.doctor.checks_resources._workspace_root_path",
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
        "sase.doctor.checks_resources._workspace_root_path",
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
        "sase.doctor.checks_resources._workspace_root_path",
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
        "sase.doctor.checks_resources._workspace_root_path",
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
