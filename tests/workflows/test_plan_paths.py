"""Tests for stable SASE_PLAN metadata path formatting."""

from pathlib import Path

from sase.sdd.store import SddStore
from sase.workflows.commit.plan_paths import (
    format_sase_plan_reference,
    format_sase_plan_tag_value,
    is_sase_plan_in_repo,
)


def test_format_sase_plan_reference_uses_repo_relative_symlink_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    plan = repo / "sdd" / "tales" / "202605" / "my_plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")

    repo_link = tmp_path / "repo-link"
    repo_link.symlink_to(repo, target_is_directory=True)
    linked_plan = repo_link / "sdd" / "tales" / "202605" / "my_plan.md"

    assert format_sase_plan_reference(str(linked_plan), repo_root=repo) == (
        "sdd/tales/202605/my_plan.md"
    )
    assert is_sase_plan_in_repo(str(linked_plan), repo)


def test_format_sase_plan_reference_uses_local_sdd_reference(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    local_plan = tmp_path / "primary" / ".sase" / "sdd" / "tales" / "202605"
    local_plan.mkdir(parents=True)
    plan = local_plan / "my_plan.md"
    plan.write_text("# Plan\n", encoding="utf-8")

    assert format_sase_plan_reference(str(plan), repo_root=repo) == (
        ".sase/sdd/tales/202605/my_plan.md"
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
    plan = store_root / "tales" / "202607" / "my_plan.md"
    store = SddStore("separate_repo", store_root, store_root)

    assert (
        format_sase_plan_tag_value(str(plan), repo_root=repo, store=store)
        == "tales/202607/my_plan.md"
    )


def test_format_sase_plan_tag_value_detects_sibling_store_clone(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo_2"
    store_root = repo / ".sase" / "sdd"
    sibling_plan = (
        tmp_path / "repo_1" / ".sase" / "sdd" / "tales" / "202607" / "my_plan.md"
    )
    store = SddStore("separate_repo", store_root, store_root)

    assert (
        format_sase_plan_tag_value(str(sibling_plan), repo_root=repo, store=store)
        == "tales/202607/my_plan.md"
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
    plan = store_root / "tales" / "202607" / "my_plan.md"
    store = SddStore("in_tree", store_root, store_root)

    assert (
        format_sase_plan_tag_value(str(plan), repo_root=repo, store=store)
        == "sdd/tales/202607/my_plan.md"
    )
