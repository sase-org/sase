"""Tests for the managed_tmp_reap unmanaged-default-root warning."""

from __future__ import annotations

from pathlib import Path

from sase.scripts.sase_chop_managed_tmp_reap import _unmanaged_default_root_warning


def test_same_root_is_quiet(tmp_path: Path) -> None:
    root = tmp_path / "effective"
    root.mkdir()

    assert _unmanaged_default_root_warning(root, default_root=root) is None


def test_missing_default_root_is_quiet(tmp_path: Path) -> None:
    root = tmp_path / "effective"
    root.mkdir()

    assert (
        _unmanaged_default_root_warning(root, default_root=tmp_path / "absent") is None
    )


def test_empty_default_root_is_quiet(tmp_path: Path) -> None:
    root = tmp_path / "effective"
    root.mkdir()
    default = tmp_path / "default"
    default.mkdir()

    assert _unmanaged_default_root_warning(root, default_root=default) is None


def test_default_root_with_entries_warns_with_fix(tmp_path: Path) -> None:
    root = tmp_path / "effective"
    root.mkdir()
    default = tmp_path / "default"
    stray_targets = default / "cargo-targets" / "agent-ws0"
    stray_targets.mkdir(parents=True)
    (stray_targets / "build.o").write_bytes(b"x")

    warning = _unmanaged_default_root_warning(root, default_root=default)

    assert warning is not None
    assert str(root) in warning
    assert str(default) in warning
    assert "1 entry" in warning
    assert "sase service init --yes" in warning
