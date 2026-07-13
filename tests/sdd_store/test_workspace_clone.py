from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from sase.sdd._store_link import ensure_sidecar_sdd_clone
from sase.sdd.store import (
    _write_sdd_store_record,
    ensure_sdd_kind_clone,
    ensure_workspace_sdd_clone,
)
from tests.sdd_store._helpers import (
    build_separate_repo_clones,
    clone,
    commit_all,
    git,
    init_bare_repo,
)


def test_ensure_workspace_sdd_clone_managed_separate_repo(
    tmp_path: Path,
    provider_patch,
) -> None:
    sidecar, _primary_sdd, workspace_sdd = build_separate_repo_clones(tmp_path)
    shutil.rmtree(workspace_sdd)
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
    assert (workspace_sdd / ".git").is_dir()
    assert (workspace_sdd / "plans" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"


def test_ensure_workspace_sdd_clone_syncs_plans_sidecar_only(
    tmp_path: Path,
    provider_patch,
) -> None:
    plans_remote = tmp_path / "plans.git"
    research_remote = tmp_path / "research.git"
    seed = tmp_path / "seed"
    init_bare_repo(plans_remote)
    init_bare_repo(research_remote)
    clone(plans_remote, seed)
    plan = seed / "202607" / "feature.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    commit_all(seed, "Add plan")
    git(["push", "-u", "origin", "main"], seed)
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    primary.mkdir()
    workspace.mkdir()
    _write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "owner/repo--plans",
                    "remote_url": str(plans_remote),
                },
                "research": {
                    "repo": "owner/repo--research",
                    "remote_url": str(research_remote),
                },
            },
        },
    )
    provider_patch(None)

    ensure_workspace_sdd_clone(workspace, 2, strict=True)

    plans = workspace / "sase" / "repos" / "plans"
    research = workspace / "sase" / "repos" / "research"
    assert (plans / "202607" / "feature.md").read_text(encoding="utf-8") == "# Plan\n"
    assert git(["remote", "get-url", "origin"], plans).stdout.strip() == str(
        plans_remote
    )
    assert not research.exists()

    assert ensure_sdd_kind_clone(workspace, 2, "research", strict=True) == research
    assert (research / ".git").is_dir()


def test_moved_sidecar_clone_with_matching_remote_is_accepted(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    old_clone = tmp_path / "repo--plans"
    moved_clone = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, old_clone)
    old_clone.rename(moved_clone)
    (moved_clone / "local-untracked.md").write_text("keep\n", encoding="utf-8")

    ensure_sidecar_sdd_clone(moved_clone, str(remote), strict=True)

    assert not old_clone.exists()
    assert (moved_clone / "local-untracked.md").read_text(encoding="utf-8") == "keep\n"
    assert git(["remote", "get-url", "origin"], moved_clone).stdout.strip() == str(
        remote
    )


def test_sidecar_clone_uses_matching_local_source_and_refreshes_from_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    local_source = tmp_path / "primary" / "sase" / "repos" / "plans"
    clone_dir = tmp_path / "workspace" / "sase" / "repos" / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, local_source)
    (seed / "fresh.md").write_text("fresh\n", encoding="utf-8")
    commit_all(seed, "Add fresh plan")
    git(["push"], seed)
    monkeypatch.setattr(
        "sase.sdd._store_link._clone_sdd_store",
        lambda *_args: pytest.fail("matching local source fell back to remote clone"),
    )

    ensure_sidecar_sdd_clone(
        clone_dir,
        str(remote),
        local_source=local_source,
        strict=True,
    )

    assert (clone_dir / "fresh.md").read_text(encoding="utf-8") == "fresh\n"
    assert git(["remote", "get-url", "origin"], clone_dir).stdout.strip() == str(remote)


def test_sidecar_clone_skips_mismatched_local_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "plans.git"
    other_remote = tmp_path / "other.git"
    seed = tmp_path / "seed"
    local_source = tmp_path / "primary-plans"
    clone_dir = tmp_path / "workspace-plans"
    init_bare_repo(remote)
    init_bare_repo(other_remote)
    clone(remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    clone(other_remote, local_source)
    monkeypatch.setattr(
        "sase.sdd._store_link._clone_sdd_store_from_primary",
        lambda *_args: pytest.fail("mismatched local source was trusted"),
    )

    ensure_sidecar_sdd_clone(
        clone_dir,
        str(remote),
        local_source=local_source,
        strict=True,
    )

    assert (clone_dir / "README.md").read_text(encoding="utf-8") == "# Plans\n"
    assert git(["remote", "get-url", "origin"], clone_dir).stdout.strip() == str(remote)


def test_sidecar_clone_falls_back_to_remote_when_local_source_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "workspace-plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("# Plans\n", encoding="utf-8")
    commit_all(seed, "Initialize plans")
    git(["push", "-u", "origin", "main"], seed)
    monkeypatch.setattr(
        "sase.sdd._store_link._clone_sdd_store_from_primary",
        lambda *_args: pytest.fail("missing local source was used"),
    )

    ensure_sidecar_sdd_clone(
        clone_dir,
        str(remote),
        local_source=tmp_path / "missing-primary-plans",
        strict=True,
    )

    assert (clone_dir / "README.md").is_file()


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
