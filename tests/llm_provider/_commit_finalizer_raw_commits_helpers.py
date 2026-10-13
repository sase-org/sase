"""Shared public helpers for raw local-commit finalizer tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME

#: Sentinel for writing a legacy baseline record with no ``head`` key at all.
NO_HEAD = object()


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    run_git(path, "init", "-q", "-b", "main")
    run_git(path, "config", "user.name", "SASE Test")
    run_git(path, "config", "user.email", "sase-test@example.invalid")
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    run_git(path, "add", "-A")
    run_git(path, "commit", "-q", "-m", "initial")
    return path


def commit_file(repo: Path, filename: str, content: str, message: str) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)
    return run_git(repo, "rev-parse", "HEAD")


def repo_head(repo: Path) -> str:
    return run_git(repo, "rev-parse", "HEAD")


def repo_state(repo: Path) -> tuple[str, str, str, str, str]:
    """Capture HEAD, index, status, and both worktree/index diffs."""

    return (
        repo_head(repo),
        run_git(repo, "write-tree"),
        run_git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
        run_git(repo, "diff", "--binary", "HEAD"),
        run_git(repo, "diff", "--cached", "--binary"),
    )


def write_baseline(
    artifacts_dir: Path,
    records: list[dict[str, object]],
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps({"schema_version": 1, "repositories": records}),
        encoding="utf-8",
    )


def baseline_record(
    *,
    repo_id: str,
    repo: Path,
    kind: str,
    name: str,
    scope: str,
    head: object,
    fingerprints: dict[str, tuple[str, str | None]] | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "repo_id": repo_id,
        "path": finalizer_git.normalize_path(str(repo)),
        "kind": kind,
        "name": name,
        "scope": scope,
        "captured_at": "2026-10-13T12:00:00+00:00",
        "fingerprints": {
            path: list(fingerprint)
            for path, fingerprint in (fingerprints or {}).items()
        },
    }
    if head is not NO_HEAD:
        record["head"] = head
    return record


def record_host_stitch(
    artifacts_dir: Path, repo: Path, sha: str, *, pushed: bool = False
) -> None:
    tree = run_git(repo, "rev-parse", f"{sha}^{{tree}}")
    (artifacts_dir / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "cwd": str(repo),
                    "result": sha,
                    "commit_sha": sha,
                    "commit_tree": tree,
                    "pushed": pushed,
                }
            ]
        ),
        encoding="utf-8",
    )
