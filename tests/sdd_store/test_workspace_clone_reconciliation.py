from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from sase.sdd.store import _write_sdd_store_record, ensure_workspace_sdd_clone
from tests.sdd_store._helpers import (
    build_separate_repo_clones,
    clone,
    commit_all,
    git,
    init_bare_repo,
)


def test_ensure_workspace_sdd_clone_in_tree_noop(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    (tmp_path / "repo").mkdir()
    workspace.mkdir()
    provider_patch("bare_git")

    ensure_workspace_sdd_clone(workspace, 2)

    assert not (workspace / ".sase" / "sdd").exists()


def test_ensure_workspace_sdd_clone_local_noop(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    provider_patch(None)

    ensure_workspace_sdd_clone(workspace, 1)

    assert not (workspace / ".sase" / "sdd").exists()


def test_ensure_workspace_sdd_clone_preserves_non_store_real_dir(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    workspace_sdd = workspace / ".sase" / "sdd"
    workspace_sdd.mkdir(parents=True)
    (workspace_sdd / "keep.md").write_text("# Keep\n", encoding="utf-8")
    provider_patch("github")

    ensure_workspace_sdd_clone(workspace, 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "keep.md").read_text(encoding="utf-8") == "# Keep\n"


def test_ensure_workspace_sdd_clone_pulls_stale_clean_clone(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(sidecar),
            "discovery": "found",
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "plans" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"
    assert not workspace_sdd.with_name("sdd.stale-backup").exists()


def test_ensure_workspace_sdd_clone_is_idempotent(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(sidecar),
            "discovery": "found",
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)
    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert not list((tmp_path / "repo_2" / ".sase").glob("sdd.stale-backup*"))


def test_ensure_workspace_sdd_clone_store_clone_with_commits_ahead_is_rebased(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    (workspace_sdd / "local_work.md").write_text("wip\n", encoding="utf-8")
    commit_all(workspace_sdd, "Local work")
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(sidecar),
            "discovery": "found",
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "local_work.md").read_text(encoding="utf-8") == "wip\n"
    assert (workspace_sdd / "plans" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"


def test_ensure_workspace_sdd_clone_store_clone_with_dirty_tree_is_preserved(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    (workspace_sdd / "local_notes.md").write_text("draft\n", encoding="utf-8")
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(sidecar),
            "discovery": "found",
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "local_notes.md").read_text(encoding="utf-8") == "draft\n"
    assert (workspace_sdd / "plans" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"


def test_ensure_workspace_sdd_clone_non_matching_remote_clone_is_preserved(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    shutil.rmtree(workspace_sdd)
    other = tmp_path / "other.git"
    init_bare_repo(other)
    clone(other, workspace_sdd)
    (workspace_sdd / "unrelated.md").write_text("unrelated\n", encoding="utf-8")
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(sidecar),
            "discovery": "found",
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "unrelated.md").read_text(encoding="utf-8") == "unrelated\n"


def test_ensure_workspace_sdd_clone_stale_clone_makes_relative_prompt_ref_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_patch,
) -> None:
    from sase.file_references import process_file_references

    sidecar, _primary_sdd, _workspace_sdd = build_separate_repo_clones(tmp_path)
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(sidecar),
            "discovery": "found",
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)
    monkeypatch.chdir(tmp_path / "repo_2")

    prompt = "@.sase/sdd/plans/202607/feature.md\nImplement it now."
    assert process_file_references(prompt) == prompt


def test_ensure_workspace_sdd_clone_replaces_stale_symlink(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    shutil.rmtree(workspace_sdd)
    stale_target = tmp_path / "old-sdd"
    stale_target.mkdir()
    workspace_sdd.parent.mkdir(parents=True, exist_ok=True)
    workspace_sdd.symlink_to(stale_target, target_is_directory=True)
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(sidecar),
            "discovery": "found",
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)
    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "plans" / "202607" / "feature.md").exists()


def test_ensure_workspace_sdd_clone_remote_failure_uses_primary_fallback(
    tmp_path: Path,
    provider_patch,
) -> None:
    _sidecar, primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    shutil.rmtree(workspace_sdd)
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(tmp_path / "missing.git"),
            "discovery": "found",
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(tmp_path / "repo_2", 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "plans" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"
    assert git(["remote", "get-url", "origin"], workspace_sdd).stdout.strip() == str(
        tmp_path / "missing.git"
    )
    assert (primary_sdd / "plans" / "202607" / "feature.md").exists()


def test_ensure_workspace_sdd_clone_missing_store_is_best_effort(
    tmp_path: Path,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    workspace.mkdir()
    provider_patch("github")

    ensure_workspace_sdd_clone(workspace, 2)

    assert not (workspace / ".sase" / "sdd").exists()
