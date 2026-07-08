"""Tests for doctor resource checks."""

from __future__ import annotations

from collections import namedtuple
from pathlib import Path

import pytest

from sase.doctor.checks_resources import (
    _DISK_ERROR_FREE_BYTES,
    _DISK_WARN_FREE_BYTES,
    _check_disk_free,
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
