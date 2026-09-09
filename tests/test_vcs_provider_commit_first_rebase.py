"""Integration coverage for git commit-first rebase dispatch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sase.vcs_provider.plugins.bare_git import BareGitPlugin

LINK_PATH = "links/202609/a.md.json"
ARTIFACT_REF = "plan:202609/a.md"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _configure_user(cwd: Path) -> None:
    _git(cwd, "config", "user.email", "test@example.com")
    _git(cwd, "config", "user.name", "Test User")


def _link_row(source: str, description: str, created_at: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "source_ref": source,
        "relation": "cites",
        "target_ref": ARTIFACT_REF,
        "description": description,
        "origin": "manual",
        "created_by": source,
        "created_at": created_at,
        "uses": 1,
    }


def _link_index(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 2, "artifact_ref": ARTIFACT_REF, "rows": rows}


def _link_index_text(rows: list[dict[str, Any]]) -> str:
    return (
        json.dumps(
            _link_index(rows),
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _write_link_index(repo: Path, rows: list[dict[str, Any]]) -> None:
    path = repo / LINK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_link_index_text(rows), encoding="utf-8")


def _read_link_index(repo: Path) -> dict[str, Any]:
    return json.loads((repo / LINK_PATH).read_text(encoding="utf-8"))


def _clone_origin(
    tmp_path: Path,
    *,
    link_rows: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "worker"
    _git(tmp_path, "init", "--bare", "--initial-branch=master", str(origin))
    _git(tmp_path, "clone", str(origin), str(seed))
    _configure_user(seed)
    (seed / "data.txt").write_text("one\nthree\n", encoding="utf-8")
    if link_rows is not None:
        _write_link_index(seed, link_rows)
    _git(seed, "add", "data.txt")
    if link_rows is not None:
        _git(seed, "add", LINK_PATH)
    _git(seed, "commit", "-m", "base")
    _git(seed, "push", "origin", "master")
    _git(tmp_path, "clone", str(origin), str(clone))
    _configure_user(clone)
    return origin, seed, clone


def test_create_commit_rebases_clean_upstream_movement_first_try(
    tmp_path: Path,
) -> None:
    origin, _seed, worker = _clone_origin(tmp_path)
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(origin), str(peer))
    _configure_user(peer)

    (worker / "data.txt").write_text("ONE\nthree\n", encoding="utf-8")
    (peer / "peer.txt").write_text("peer\n", encoding="utf-8")
    _git(peer, "add", "peer.txt")
    _git(peer, "commit", "-m", "peer change")
    _git(peer, "push", "origin", "master")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker change", "files": ["data.txt"]},
        str(worker),
    )

    assert ok is True, err
    _git(worker, "fetch", "origin", "master")
    assert _git(worker, "status", "--short", "--branch").stdout.strip() == (
        "## master...origin/master"
    )
    assert (worker / "data.txt").read_text(encoding="utf-8") == "ONE\nthree\n"
    assert (worker / "peer.txt").read_text(encoding="utf-8") == "peer\n"


def test_create_commit_resolves_artifact_link_add_add_rebase_conflict(
    tmp_path: Path,
) -> None:
    origin, _seed, worker = _clone_origin(tmp_path)
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(origin), str(peer))
    _configure_user(peer)

    local_row = _link_row(
        "agent:local",
        "local citation",
        "2026-09-03T00:00:00Z",
    )
    upstream_row = _link_row(
        "agent:upstream",
        "upstream citation",
        "2026-09-02T00:00:00Z",
    )
    _write_link_index(worker, [local_row])
    _write_link_index(peer, [upstream_row])
    _git(peer, "add", LINK_PATH)
    _git(peer, "commit", "-m", "peer artifact link")
    _git(peer, "push", "origin", "master")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker artifact link", "files": [LINK_PATH]},
        str(worker),
    )

    assert ok is True, err
    _git(worker, "fetch", "origin", "master")
    assert _git(worker, "status", "--short", "--branch").stdout.strip() == (
        "## master...origin/master"
    )
    assert _git(worker, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert not (worker / ".git/rebase-merge").is_dir()
    assert not (worker / ".git/rebase-apply").is_dir()
    merged = _read_link_index(worker)
    assert [row["source_ref"] for row in merged["rows"]] == [
        "agent:upstream",
        "agent:local",
    ]


def test_create_commit_leaves_genuine_rebase_conflict_resumable(tmp_path: Path) -> None:
    origin, _seed, worker = _clone_origin(tmp_path)
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(origin), str(peer))
    _configure_user(peer)

    (worker / "data.txt").write_text("worker\nthree\n", encoding="utf-8")
    (peer / "data.txt").write_text("peer\nthree\n", encoding="utf-8")
    _git(peer, "add", "data.txt")
    _git(peer, "commit", "-m", "peer conflict")
    _git(peer, "push", "origin", "master")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker conflict", "files": ["data.txt"]},
        str(worker),
    )

    assert ok is False
    assert err is not None and "Conflicted files: data.txt" in err
    assert (worker / ".git/rebase-merge").is_dir() or (
        worker / ".git/rebase-apply"
    ).is_dir()
    assert _git(worker, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        "data.txt"
    )


def test_create_commit_leaves_ambiguous_artifact_link_rebase_conflict_resumable(
    tmp_path: Path,
) -> None:
    base_row = _link_row(
        "agent:base",
        "base citation",
        "2026-09-01T00:00:00Z",
    )
    origin, _seed, worker = _clone_origin(tmp_path, link_rows=[base_row])
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(origin), str(peer))
    _configure_user(peer)

    _write_link_index(worker, [dict(base_row, description="local edit")])
    _write_link_index(peer, [dict(base_row, description="upstream edit")])
    _git(peer, "add", LINK_PATH)
    _git(peer, "commit", "-m", "peer artifact link edit")
    _git(peer, "push", "origin", "master")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker artifact link edit", "files": [LINK_PATH]},
        str(worker),
    )

    assert ok is False
    assert err is not None and f"Conflicted files: {LINK_PATH}" in err
    assert (worker / ".git/rebase-merge").is_dir() or (
        worker / ".git/rebase-apply"
    ).is_dir()
    assert _git(worker, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        LINK_PATH
    )


def test_create_commit_records_unpushed_marker_when_push_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _origin, seed, worker = _clone_origin(tmp_path)
    _git(worker, "remote", "set-url", "origin", str(seed))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")

    (worker / "data.txt").write_text("local\nthree\n", encoding="utf-8")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker local commit", "files": ["data.txt"]},
        str(worker),
    )

    assert ok is False
    assert err is not None
    assert "created locally; git push failed" in err
    assert "refusing to update checked out branch" in err
    assert _git(worker, "status", "--short").stdout.strip() == ""
    sha = _git(worker, "rev-parse", "HEAD").stdout.strip()
    tree = _git(worker, "rev-parse", "HEAD^{tree}").stdout.strip()
    markers = json.loads((artifacts / "commit_results.json").read_text())
    assert len(markers) == 1
    assert markers[0]["cwd"] == str(worker)
    assert markers[0]["result"] == sha
    assert markers[0]["commit_sha"] == sha
    assert markers[0]["commit_tree"] == tree
    assert markers[0]["pushed"] is False


def test_finalize_commit_records_unpushed_marker_when_push_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _origin, seed, worker = _clone_origin(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")

    (worker / "data.txt").write_text("local\nthree\n", encoding="utf-8")
    _git(worker, "add", "data.txt")
    _git(worker, "commit", "-m", "worker local commit")
    _git(worker, "remote", "set-url", "origin", str(seed))

    ok, err = BareGitPlugin().vcs_finalize_commit(
        {"message": "worker local commit"},
        str(worker),
    )

    assert ok is False
    assert err is not None
    assert "created locally; git push failed" in err
    assert "refusing to update checked out branch" in err
    sha = _git(worker, "rev-parse", "HEAD").stdout.strip()
    tree = _git(worker, "rev-parse", "HEAD^{tree}").stdout.strip()
    markers = json.loads((artifacts / "commit_results.json").read_text())
    assert len(markers) == 1
    assert markers[0]["cwd"] == str(worker)
    assert markers[0]["result"] == sha
    assert markers[0]["commit_sha"] == sha
    assert markers[0]["commit_tree"] == tree
    assert markers[0]["pushed"] is False
    assert not (artifacts / "commit_result.json").exists()


def test_create_commit_reports_local_sha_when_push_to_checked_out_origin_refused(
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin"
    worker = tmp_path / "worker"
    origin.mkdir()
    _git(origin, "init", "--initial-branch=master")
    _configure_user(origin)
    (origin / "data.txt").write_text("base\n", encoding="utf-8")
    _git(origin, "add", "data.txt")
    _git(origin, "commit", "-m", "base")
    _git(tmp_path, "clone", str(origin), str(worker))
    _configure_user(worker)

    (worker / "data.txt").write_text("worker\n", encoding="utf-8")
    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker change", "files": ["data.txt"]},
        str(worker),
    )

    head = _git(worker, "rev-parse", "HEAD").stdout.strip()
    assert ok is False
    assert err is not None
    assert f"commit {head} created locally" in err
    assert "git push failed" in err
    assert _git(worker, "status", "--porcelain").stdout == ""
