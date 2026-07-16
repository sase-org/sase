from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_setup import (
    capture_sdd_base_sha,
    prepare_workspace_if_needed,
)
from sase.sdd.store import SddStore


def test_prepare_workspace_if_needed_invokes_strict_sdd_clone_after_clear() -> None:
    calls: list[tuple[str, object]] = []

    def prepare_workspace(*args: object, **kwargs: object) -> bool:
        calls.append(("prepare", args))
        return True

    def ensure_workspace_sdd_clone(
        workspace_dir: str, workspace_num: int, *, strict: bool = False
    ) -> None:
        calls.append(("clone", (workspace_dir, workspace_num, strict)))

    def clear_workspace_repos(workspace_dir: str, workspace_num: int) -> None:
        calls.append(("clear", (workspace_dir, workspace_num)))

    with (
        patch(
            "sase.axe.run_agent_runner_setup.prepare_workspace",
            side_effect=prepare_workspace,
        ),
        patch(
            "sase.sdd.store.ensure_workspace_sdd_clone",
            side_effect=ensure_workspace_sdd_clone,
        ),
        patch(
            "sase.linked_repos.clear_workspace_repos",
            side_effect=clear_workspace_repos,
        ),
    ):
        prepare_workspace_if_needed(
            workspace_dir="/tmp/workspace",
            workspace_num=7,
            cl_name="feature",
            update_target="main",
            project_name="sase",
            is_home_mode=False,
            retry_handoff=None,
        )

    assert calls == [
        ("prepare", ("/tmp/workspace", "feature", "main")),
        ("clear", ("/tmp/workspace", 7)),
        ("clone", ("/tmp/workspace", 7, True)),
    ]


def test_prepare_workspace_if_needed_skips_sdd_clone_for_home_mode() -> None:
    with (
        patch("sase.axe.run_agent_runner_setup.prepare_workspace") as prepare,
        patch("sase.sdd.store.ensure_workspace_sdd_clone") as ensure_clone,
        patch("sase.linked_repos.clear_workspace_repos") as clear_repos,
    ):
        prepare_workspace_if_needed(
            workspace_dir="/tmp/workspace",
            workspace_num=7,
            cl_name="feature",
            update_target="main",
            project_name="sase",
            is_home_mode=True,
            retry_handoff=None,
        )

    prepare.assert_not_called()
    clear_repos.assert_not_called()
    ensure_clone.assert_not_called()


def test_prepare_workspace_if_needed_skips_sdd_clone_for_retry_handoff() -> None:
    with (
        patch("sase.axe.run_agent_runner_setup.prepare_workspace") as prepare,
        patch("sase.sdd.store.ensure_workspace_sdd_clone") as ensure_clone,
        patch("sase.linked_repos.clear_workspace_repos") as clear_repos,
    ):
        prepare_workspace_if_needed(
            workspace_dir="/tmp/workspace",
            workspace_num=7,
            cl_name="feature",
            update_target="main",
            project_name="sase",
            is_home_mode=False,
            retry_handoff=object(),
        )

    prepare.assert_not_called()
    clear_repos.assert_not_called()
    ensure_clone.assert_not_called()


def test_capture_sdd_base_sha_for_sidecar_repo(tmp_path: Path) -> None:
    sdd_repo = tmp_path / "workspace" / ".sase" / "sdd"
    sdd_repo.mkdir(parents=True)
    _git(sdd_repo, "git", "init")
    _git(sdd_repo, "git", "config", "user.email", "test@example.com")
    _git(sdd_repo, "git", "config", "user.name", "Test User")
    (sdd_repo / "README.md").write_text("# SDD\n")
    _git(sdd_repo, "git", "add", ".")
    _git(sdd_repo, "git", "commit", "-m", "base")
    expected = _git(sdd_repo, "git", "rev-parse", "HEAD")

    with patch(
        "sase.sdd.store.resolve_sdd_store",
        return_value=SddStore("separate_repo", sdd_repo, sdd_repo),
    ):
        assert capture_sdd_base_sha(str(tmp_path / "workspace"), 1) == expected


def test_capture_sdd_base_sha_skips_in_tree_and_missing_clone(
    tmp_path: Path,
) -> None:
    with patch(
        "sase.sdd.store.resolve_sdd_store",
        return_value=SddStore("in_tree", tmp_path / "sdd", tmp_path),
    ):
        assert capture_sdd_base_sha(str(tmp_path), 1) is None

    missing = tmp_path / ".sase" / "sdd"
    with patch(
        "sase.sdd.store.resolve_sdd_store",
        return_value=SddStore("local", missing, missing),
    ):
        assert capture_sdd_base_sha(str(tmp_path), 1) is None


def _git(cwd: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()
