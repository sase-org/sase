"""Tests for ``sase init skills`` skill-source git integrity checks."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.main import _init_skills_source_integrity as source_integrity


def test_skill_source_integrity_allows_clean_merged_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    skills_dir = repo_root / "src" / "sase" / "xprompts" / "skills"
    skills_dir.mkdir(parents=True)
    calls: list[tuple[str, ...]] = []

    def fake_run_git(root: Path, *args: str) -> str:
        calls.append(args)
        if args == ("rev-parse", "--show-toplevel"):
            return str(repo_root)
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(
        source_integrity, "get_sase_package_skills_dir", lambda: skills_dir
    )
    monkeypatch.setattr(
        source_integrity, "get_default_branch", lambda _root: "origin/main"
    )
    monkeypatch.setattr(source_integrity, "run_git", fake_run_git)

    assert source_integrity.skill_source_integrity_error() is None
    assert (
        "status",
        "--porcelain=v1",
        "--",
        "src/sase/xprompts/skills",
    ) in calls
    assert (
        "merge-base",
        "--is-ancestor",
        "HEAD",
        "origin/main",
    ) in calls


def test_skill_source_integrity_reports_dirty_skill_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    skills_dir = repo_root / "src" / "sase" / "xprompts" / "skills"
    skills_dir.mkdir(parents=True)

    def fake_run_git(root: Path, *args: str) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return str(repo_root)
        if args[:2] == ("status", "--porcelain=v1"):
            return " M src/sase/xprompts/skills/foo.md"
        raise AssertionError(args)

    monkeypatch.setattr(
        source_integrity, "get_sase_package_skills_dir", lambda: skills_dir
    )
    monkeypatch.setattr(source_integrity, "run_git", fake_run_git)

    error = source_integrity.skill_source_integrity_error()

    assert error is not None
    assert "uncommitted changes" in error
    assert "src/sase/xprompts/skills/foo.md" in error
    assert "Land the skill source change" in error
    assert "--allow-dirty" in error


def test_skill_source_integrity_reports_commits_missing_from_canonical_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_root = tmp_path / "repo"
    skills_dir = repo_root / "src" / "sase" / "xprompts" / "skills"
    skills_dir.mkdir(parents=True)

    def fake_run_git(root: Path, *args: str) -> str:
        if args == ("rev-parse", "--show-toplevel"):
            return str(repo_root)
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args[:2] == ("merge-base", "--is-ancestor"):
            raise subprocess.CalledProcessError(1, ["git", *args])
        if args[:2] == ("log", "--format=%h %s"):
            return "abc1234 feat: unlanded skill source"
        raise AssertionError(args)

    monkeypatch.setattr(
        source_integrity, "get_sase_package_skills_dir", lambda: skills_dir
    )
    monkeypatch.setattr(
        source_integrity, "get_default_branch", lambda _root: "origin/master"
    )
    monkeypatch.setattr(source_integrity, "run_git", fake_run_git)

    error = source_integrity.skill_source_integrity_error()

    assert error is not None
    assert "HEAD is not an ancestor of origin/master" in error
    assert "abc1234 feat: unlanded skill source" in error
