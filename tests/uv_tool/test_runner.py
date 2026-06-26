"""Tests for the uv subprocess runner and its output parser."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest

from sase.uv_tool.errors import UvCommandFailedError, UvNotFoundError
from sase.uv_tool.runner import (
    ChangeKind,
    UvChangeSet,
    UvPackageChange,
    parse_uv_output,
    run_uv,
)

# Real `uv tool install` stderr (captured from uv 0.11.24): a fresh install with
# a hardlink warning and Resolved/Prepared/Installed summary lines surrounding
# the `+` change lines.
_FRESH_INSTALL_STDERR = """\
Resolved 2 packages in 133ms
Prepared 1 package in 117ms
warning: Failed to hardlink files; falling back to full copy.
Installed 2 packages in 33ms
 + cowsay==6.1
 + six==1.10.0
Installed 1 executable: cowsay
"""

# Real `--upgrade-package` stderr: one package is replaced (old -> new).
_UPGRADE_STDERR = """\
Resolved 2 packages in 112ms
Uninstalled 1 package in 0.36ms
Installed 1 package in 48ms
 - six==1.10.0
 + six==1.17.0
Installed 1 executable: cowsay
"""

# A git-sourced package carries a trailing `(from git+...)` annotation.
_GIT_INSTALL_STDERR = (
    " + six==1.17.0 (from git+https://github.com/benjaminp/six@c8e3940)\n"
)


# --- parse_uv_output -----------------------------------------------------------


def test_parse_fresh_install_classifies_additions() -> None:
    changeset = parse_uv_output(_FRESH_INSTALL_STDERR)
    assert not changeset.is_noop
    assert [(c.name, c.kind, c.new_version) for c in changeset.changes] == [
        ("cowsay", ChangeKind.ADDED, "6.1"),
        ("six", ChangeKind.ADDED, "1.10.0"),
    ]


def test_parse_upgrade_classifies_old_to_new() -> None:
    changeset = parse_uv_output(_UPGRADE_STDERR)
    assert len(changeset.changes) == 1
    change = changeset.changes[0]
    assert change.kind is ChangeKind.UPGRADED
    assert change.old_version == "1.10.0"
    assert change.new_version == "1.17.0"


def test_parse_ignores_git_source_annotation() -> None:
    change = parse_uv_output(_GIT_INSTALL_STDERR).changes[0]
    assert change.name == "six"
    assert change.new_version == "1.17.0"


def test_parse_removal_only() -> None:
    change = parse_uv_output(" - gone==1.0\n").changes[0]
    assert change.kind is ChangeKind.REMOVED
    assert change.old_version == "1.0"
    assert change.new_version is None


def test_parse_preserves_first_appearance_order() -> None:
    text = " + b==2\n + a==1\n - a==0\n"
    changeset = parse_uv_output(text)
    assert [c.name for c in changeset.changes] == ["b", "a"]
    assert changeset.get("a").kind is ChangeKind.UPGRADED


@pytest.mark.parametrize(
    "text",
    ["`sase` is already installed\n", "Nothing to upgrade\n", "", "Resolved 0\n"],
)
def test_parse_noop_outputs(text: str) -> None:
    assert parse_uv_output(text).is_noop


def test_parse_preserves_raw_output() -> None:
    assert parse_uv_output(_UPGRADE_STDERR).raw_output == _UPGRADE_STDERR


# --- UvChangeSet helpers -------------------------------------------------------


def test_changeset_by_kind_and_properties() -> None:
    changeset = UvChangeSet(
        changes=(
            UvPackageChange("a", ChangeKind.ADDED, new_version="1"),
            UvPackageChange("b", ChangeKind.REMOVED, old_version="2"),
            UvPackageChange("c", ChangeKind.UPGRADED, old_version="1", new_version="2"),
        )
    )
    assert [c.name for c in changeset.added] == ["a"]
    assert [c.name for c in changeset.removed] == ["b"]
    assert [c.name for c in changeset.upgraded] == ["c"]
    assert changeset.by_kind(ChangeKind.UNCHANGED) == ()


def test_changeset_get_normalizes_name() -> None:
    changeset = UvChangeSet(
        changes=(UvPackageChange("Sase_GitHub", ChangeKind.ADDED, new_version="1"),)
    )
    assert changeset.get("sase-github") is not None
    assert changeset.get("missing") is None


# --- run_uv --------------------------------------------------------------------


def _completed(
    *, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["uv"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_run_uv_parses_stderr_on_success() -> None:
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed(stderr=_UPGRADE_STDERR)

    changeset = run_uv(["uv", "tool", "upgrade", "sase"], run_fn=_run)
    assert changeset.upgraded[0].name == "six"


def test_run_uv_passes_expected_subprocess_kwargs() -> None:
    captured: dict[str, Any] = {}

    def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _completed(stderr="Nothing to upgrade\n")

    run_uv(["uv", "tool", "upgrade", "sase"], run_fn=_run, timeout=12.5)
    assert captured["args"] == ["uv", "tool", "upgrade", "sase"]
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["timeout"] == 12.5


def test_run_uv_missing_binary_raises_uv_not_found() -> None:
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("uv")

    with pytest.raises(UvNotFoundError):
        run_uv(["uv", "tool", "upgrade", "sase"], run_fn=_run)


def test_run_uv_timeout_raises_command_failed() -> None:
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="uv", timeout=300.0)

    with pytest.raises(UvCommandFailedError) as excinfo:
        run_uv(["uv", "tool", "upgrade", "sase"], run_fn=_run)
    assert excinfo.value.timeout == 300.0
    assert "timed out" in str(excinfo.value)


def test_run_uv_os_error_raises_command_failed() -> None:
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("boom")

    with pytest.raises(UvCommandFailedError):
        run_uv(["uv", "tool", "upgrade", "sase"], run_fn=_run)


def test_run_uv_nonzero_exit_raises_with_detail() -> None:
    def _run(_args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed(returncode=2, stderr="error: No solution found")

    with pytest.raises(UvCommandFailedError) as excinfo:
        run_uv(["uv", "tool", "install", "sase"], run_fn=_run)
    assert excinfo.value.returncode == 2
    assert "No solution found" in str(excinfo.value)
