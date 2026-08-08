"""Tests for PARENT-target scoping in SDD plan validation and repair."""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.sdd.links import repair_sdd_links, validate_sdd_tree

CHILD_REF = "202607/parent.md"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_plans_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo--plans"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "plans@example.com")
    _git(repo, "config", "user.name", "Plan Tests")
    (repo / "README.md").write_text("# Plans\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "Seed plans store")
    return repo


def _write_child(repo: Path, name: str = "child") -> Path:
    plan = repo / "202607" / f"{name}.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        f"- **PROMPT:** [prompts/202607/{name}.md](https://example.test/{name})\n"
        f"- **PARENT:** [{CHILD_REF}](parent.md)\n\n"
        "# Plan\n",
        encoding="utf-8",
    )
    return plan


def _write_parent(repo: Path) -> Path:
    plan = repo / "202607" / "parent.md"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("---\ntier: epic\n---\n\n# Parent plan\n", encoding="utf-8")
    return plan


def test_published_plan_with_unpublished_parent_only_warns(tmp_path: Path) -> None:
    repo = _init_plans_repo(tmp_path)
    _write_child(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "Publish child plan")

    validation = validate_sdd_tree(str(repo))

    assert validation.ok
    assert [issue.code for issue in validation.warnings] == ["parent-unpublished"]
    assert CHILD_REF in validation.warnings[0].message


def test_locally_changed_plan_with_missing_parent_still_errors(tmp_path: Path) -> None:
    repo = _init_plans_repo(tmp_path)
    _write_child(repo)

    validation = validate_sdd_tree(str(repo))

    assert not validation.ok
    assert [issue.code for issue in validation.errors] == ["parent-missing-target"]


def test_published_plan_is_clean_once_the_parent_lands(tmp_path: Path) -> None:
    repo = _init_plans_repo(tmp_path)
    _write_child(repo)
    _write_parent(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "Publish both plans")

    validation = validate_sdd_tree(str(repo))

    assert validation.ok
    assert validation.issues == []


def test_non_git_plan_tree_keeps_the_strict_parent_error(tmp_path: Path) -> None:
    root = tmp_path / "plain--plans"
    _write_child(root)

    validation = validate_sdd_tree(str(root))

    assert [issue.code for issue in validation.errors] == ["parent-missing-target"]


def test_repair_reports_the_unpublished_parent(tmp_path: Path) -> None:
    repo = _init_plans_repo(tmp_path)
    _write_child(repo)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "Publish child plan")

    report = repair_sdd_links(str(repo))

    assert [issue.code for issue in report.issues] == ["parent-unpublished"]
    assert all(issue.severity == "warning" for issue in report.issues)


def test_repair_errors_on_a_locally_changed_missing_parent(tmp_path: Path) -> None:
    repo = _init_plans_repo(tmp_path)
    _write_child(repo)

    report = repair_sdd_links(str(repo))

    assert [issue.code for issue in report.issues] == ["parent-missing-target"]
    assert all(issue.severity == "error" for issue in report.issues)
