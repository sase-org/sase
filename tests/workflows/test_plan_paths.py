"""Tests for stable SASE_PLAN metadata path formatting."""

import subprocess
from pathlib import Path

from sase.sdd.store import SddStore
from sase.workflows.commit.plan_paths import (
    format_sase_plan_reference,
    format_sase_plan_link,
    format_sase_plan_tag_value,
    is_sase_plan_in_repo,
)


def test_format_sase_plan_reference_uses_repo_relative_symlink_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    plan = repo / "sdd" / "plans" / "202605" / "my_plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")

    repo_link = tmp_path / "repo-link"
    repo_link.symlink_to(repo, target_is_directory=True)
    linked_plan = repo_link / "sdd" / "plans" / "202605" / "my_plan.md"

    assert format_sase_plan_reference(str(linked_plan), repo_root=repo) == (
        "sdd/plans/202605/my_plan.md"
    )
    assert is_sase_plan_in_repo(str(linked_plan), repo)


def test_format_sase_plan_reference_uses_local_sdd_reference(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    local_plan = tmp_path / "primary" / ".sase" / "sdd" / "plans" / "202605"
    local_plan.mkdir(parents=True)
    plan = local_plan / "my_plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")

    assert format_sase_plan_reference(str(plan), repo_root=repo) == (
        ".sase/sdd/plans/202605/my_plan.md"
    )


def test_format_sase_plan_reference_shortens_home_path(tmp_path: Path) -> None:
    home = tmp_path / "home"
    plan = home / ".sase" / "plans" / "my_plan.md"

    assert (
        format_sase_plan_reference(
            str(plan), repo_root=tmp_path / "repo", home_dir=home
        )
        == "~/.sase/plans/my_plan.md"
    )


def test_format_sase_plan_reference_preserves_external_path(tmp_path: Path) -> None:
    assert (
        format_sase_plan_reference("/opt/plans/my_plan.md", repo_root=tmp_path)
        == "/opt/plans/my_plan.md"
    )


def test_format_sase_plan_tag_value_uses_store_relative_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    store_root = repo / ".sase" / "sdd"
    plan = store_root / "plans" / "202607" / "my_plan.md"
    store = SddStore("separate_repo", store_root, store_root)

    assert (
        format_sase_plan_tag_value(str(plan), repo_root=repo, store=store)
        == "plans/202607/my_plan.md"
    )


def test_format_sase_plan_tag_value_detects_sibling_store_clone(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo_2"
    store_root = repo / ".sase" / "sdd"
    sibling_plan = (
        tmp_path / "repo_1" / ".sase" / "sdd" / "plans" / "202607" / "my_plan.md"
    )
    store = SddStore("separate_repo", store_root, store_root)

    assert (
        format_sase_plan_tag_value(str(sibling_plan), repo_root=repo, store=store)
        == "plans/202607/my_plan.md"
    )


def test_format_sase_plan_tag_value_preserves_non_store_fallback(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    store_root = repo / ".sase" / "sdd"
    plan = repo / "plans" / "my_plan.md"
    store = SddStore("local", store_root, store_root)

    assert (
        format_sase_plan_tag_value(str(plan), repo_root=repo, store=store)
        == "plans/my_plan.md"
    )


def test_format_sase_plan_tag_value_keeps_in_tree_sdd_prefix(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    store_root = repo / "sdd"
    plan = store_root / "plans" / "202607" / "my_plan.md"
    store = SddStore("in_tree", store_root, store_root)

    assert (
        format_sase_plan_tag_value(str(plan), repo_root=repo, store=store)
        == "sdd/plans/202607/my_plan.md"
    )


def test_format_sase_plan_link_uses_github_remote_branch_and_encoded_path(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "plans"
    _git(store_root, "init", "-q", "-b", "feature/plan-links")
    store = SddStore(
        "sidecar_repos",
        store_root,
        store_root,
        provider="github",
        remote_url="git@github.com:sase-org/sase--plans.git",
    )

    assert format_sase_plan_link("202607/a plan #1.md", store=store) == (
        "https://github.com/sase-org/sase--plans/blob/"
        "feature%2Fplan-links/202607/a%20plan%20%231.md"
    )


def test_format_sase_plan_link_detached_clone_uses_local_origin_default(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "plans"
    _git(store_root, "init", "-q", "-b", "main")
    _git(store_root, "config", "user.name", "Test")
    _git(store_root, "config", "user.email", "test@example.com")
    _git(store_root, "commit", "--allow-empty", "-qm", "initial")
    _git(store_root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(
        store_root,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/main",
    )
    _git(store_root, "checkout", "-q", "--detach")
    store = SddStore(
        "separate_repo",
        store_root,
        store_root,
        provider="github",
        remote_url="https://github.example.test/acme/plans.git",
    )

    assert format_sase_plan_link("plans/202607/p.md", store=store) == (
        "https://github.example.test/acme/plans/blob/main/plans/202607/p.md"
    )


def test_format_sase_plan_link_falls_back_for_unsupported_or_unknown_store(
    tmp_path: Path,
) -> None:
    store_root = tmp_path / "not-a-repo"
    store_root.mkdir()
    unknown_branch = SddStore(
        "separate_repo",
        store_root,
        store_root,
        provider="github",
        remote_url="git@github.com:acme/plans.git",
    )
    assert format_sase_plan_link("plans/p.md", store=unknown_branch) is None

    _git(store_root, "init", "-q", "-b", "main")
    non_github = SddStore(
        "separate_repo",
        store_root,
        store_root,
        provider="gitlab",
        remote_url="git@gitlab.example.test:acme/plans.git",
    )
    assert format_sase_plan_link("plans/p.md", store=non_github) is None


def _git(cwd: Path, *args: str) -> None:
    cwd.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
