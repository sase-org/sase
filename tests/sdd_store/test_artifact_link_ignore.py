"""Sidecar lock-ignore coverage for artifact-link sentinels."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from sase.sdd._artifact_link_files import artifact_link_lock_path
from sase.sdd._artifact_link_ignore import (
    ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN,
    ensure_artifact_link_lock_gitignore,
)
from sase.sdd.artifact_link_store import ARTIFACT_LINK_ROW_SCHEMA_VERSION


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_git(repo: Path) -> None:
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )


def _write_index(repo: Path, stem: str) -> Path:
    path = repo / "links" / "202608" / f"{stem}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "artifact_ref": f"plan:202608/{stem}",
                "rows": [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_lock_ignore_appends_without_disturbing_existing_content(
    tmp_path: Path,
) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text("assets/cache/\n", encoding="utf-8")

    assert ensure_artifact_link_lock_gitignore(tmp_path) == gitignore
    assert gitignore.read_text(encoding="utf-8") == (
        f"assets/cache/\n{ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN}\n"
    )
    before = gitignore.read_bytes()
    assert ensure_artifact_link_lock_gitignore(tmp_path) is None
    assert gitignore.read_bytes() == before


def test_lock_ignore_is_byte_stable_on_rerun(tmp_path: Path) -> None:
    created = ensure_artifact_link_lock_gitignore(tmp_path)
    assert created is not None
    first = created.read_bytes()
    assert ensure_artifact_link_lock_gitignore(tmp_path) is None
    assert created.read_bytes() == first


def test_new_locks_stay_out_of_status_and_remain_usable(tmp_path: Path) -> None:
    repo = tmp_path / "plans"
    _init_git(repo)
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")

    index = _write_index(repo, "example.md")
    lock = artifact_link_lock_path(index)
    lock.write_bytes(b"")
    assert ensure_artifact_link_lock_gitignore(repo) is not None
    _run_git(repo, "add", ".gitignore", "links/202608/example.md.json")
    _run_git(repo, "commit", "-q", "-m", "add index")

    status = _run_git(repo, "status", "--porcelain", "--untracked-files=all")
    assert "example.md.lock" not in status
    assert lock.is_file()
    assert lock.stat().st_size == 0


def test_historically_tracked_locks_are_neither_deleted_nor_recommitted(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "plans"
    _init_git(repo)
    index = _write_index(repo, "legacy.md")
    lock = artifact_link_lock_path(index)
    lock.write_bytes(b"")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "historical lock")

    tracked_before = _run_git(repo, "ls-files", "links")
    assert "legacy.md.lock" in tracked_before
    assert ensure_artifact_link_lock_gitignore(repo) is not None
    _run_git(repo, "add", ".gitignore")
    _run_git(repo, "commit", "-q", "-m", "ignore future locks")

    assert lock.is_file()
    tracked_after = _run_git(repo, "ls-files", "links")
    assert "legacy.md.lock" in tracked_after
    status = _run_git(repo, "status", "--porcelain")
    assert status == ""
    log = _run_git(repo, "log", "--oneline", "--", str(lock.relative_to(repo)))
    assert len(log.splitlines()) == 1
