"""Tests for linked repository clone paths and sidecar materialization."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.linked_repos import (
    linked_repo_clone_dir,
    materialize_linked_repo_workspace,
    sidecar_repo_clone_dir,
)
from tests._linked_repo_resolution_helpers import _set_github_origin
from tests.sdd_store._helpers import clone, commit_all, init_bare_repo


def test_clone_path_helpers_split_linked_and_sidecar_namespaces(
    tmp_path: Path,
) -> None:
    host = tmp_path / "main_10"
    assert linked_repo_clone_dir(host, "core") == str(
        (host / "sase" / "repos" / "linked" / "core").resolve()
    )
    assert sidecar_repo_clone_dir(host, "plans") == str(
        (host / "sase" / "repos" / "plans").resolve()
    )


def test_sidecar_materialization_normalizes_protocol_in_place(
    tmp_path: Path,
) -> None:
    target = tmp_path / "workspace" / "sase" / "repos" / "research"
    target.mkdir(parents=True)
    _set_github_origin(
        target,
        "https://github.com/acme/widget--research.git",
    )
    local = target / "local.md"
    local.write_text("preserve me\n", encoding="utf-8")
    commit_all(target, "Local research commit")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=target,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    for _ in range(2):
        result = materialize_linked_repo_workspace(
            primary_dir=str(target),
            workspace_dir=str(target),
            workspace_num=10,
            expected_remote_url="git@github.com:acme/widget--research.git",
        )
        assert result == str(target.resolve())

    assert local.read_text(encoding="utf-8") == "preserve me\n"
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=target,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        == head
    )
    assert (
        subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=target,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        == "git@github.com:acme/widget--research.git"
    )


def test_sidecar_materialization_preserves_dirty_mismatched_workspace(
    tmp_path: Path,
) -> None:
    target = tmp_path / "workspace" / "sase" / "repos" / "research"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(tmp_path / "wrong.git")],
        cwd=target,
        check=True,
    )
    local = target / "local.md"
    local.write_text("uncommitted research\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="has local changes"):
        materialize_linked_repo_workspace(
            primary_dir=str(tmp_path / "primary"),
            workspace_dir=str(target),
            workspace_num=10,
            expected_remote_url=str(tmp_path / "expected.git"),
        )

    assert local.read_text(encoding="utf-8") == "uncommitted research\n"


def test_sidecar_materialization_replaces_mismatched_primary_origin(
    tmp_path: Path,
) -> None:
    expected_remote = tmp_path / "expected.git"
    wrong_remote = tmp_path / "wrong.git"
    expected_seed = tmp_path / "expected-seed"
    wrong_seed = tmp_path / "wrong-seed"
    target = tmp_path / "primary" / "sase" / "repos" / "research"
    init_bare_repo(expected_remote)
    init_bare_repo(wrong_remote)
    clone(expected_remote, expected_seed)
    (expected_seed / "README.md").write_text("# Shared research\n", encoding="utf-8")
    commit_all(expected_seed, "Initialize shared research")
    subprocess.run(["git", "push", "origin", "main"], cwd=expected_seed, check=True)
    clone(wrong_remote, wrong_seed)
    (wrong_seed / "stale.txt").write_text("old project research\n", encoding="utf-8")
    commit_all(wrong_seed, "Initialize old research")
    subprocess.run(["git", "push", "origin", "main"], cwd=wrong_seed, check=True)
    clone(wrong_remote, target)

    result = materialize_linked_repo_workspace(
        primary_dir=str(target),
        workspace_dir=str(target),
        workspace_num=0,
        expected_remote_url=str(expected_remote),
    )

    assert result == str(target.resolve())
    assert not (target / "stale.txt").exists()
    assert (target / "README.md").read_text(encoding="utf-8") == ("# Shared research\n")
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=target,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert origin == str(expected_remote)


def test_sidecar_materialization_preserves_dirty_mismatched_primary(
    tmp_path: Path,
) -> None:
    target = tmp_path / "primary" / "sase" / "repos" / "research"
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=target, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(tmp_path / "wrong.git")],
        cwd=target,
        check=True,
    )
    local = target / "local.md"
    local.write_text("uncommitted research\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="has local changes"):
        materialize_linked_repo_workspace(
            primary_dir=str(target),
            workspace_dir=str(target),
            workspace_num=0,
            expected_remote_url=str(tmp_path / "expected.git"),
        )

    assert local.read_text(encoding="utf-8") == "uncommitted research\n"
