"""Tests for the managed_tmp_reap scanned-roots info line."""

from __future__ import annotations

from pathlib import Path

from sase.scripts.sase_chop_managed_tmp_reap import _managed_tmp_roots_info


def test_single_root_is_listed(tmp_path: Path) -> None:
    root = tmp_path / "effective"
    root.mkdir()

    info = _managed_tmp_roots_info([root])

    assert info == f"managed tmp reaper scans 1 root: {root}"


def test_every_scanned_root_is_listed(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    info = _managed_tmp_roots_info([first, second])

    assert info == f"managed tmp reaper scans 2 roots: {first}, {second}"
