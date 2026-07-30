"""Tests for authorship-aware automatic artifact capture decisions."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from sase._repo_inventory_models import RepoCloneRecord, RepoInventory, RepoRecord
from sase.config import core as config_core
from sase.core.artifact_capture_policy import (
    CaptureCandidate,
    CaptureLimits,
    GitVcsProbe,
    decide_captures,
)
from tests._sdd_commit_helpers import init_test_git_repo


PROJECT = "widget"
WORKSPACE_NUM = 7
LIMITS = CaptureLimits(max_stored_per_agent=50, max_history_scan=20)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate(path: Path, origin: str = "changed") -> CaptureCandidate:
    return CaptureCandidate(
        path=str(path),
        origin=origin,  # type: ignore[arg-type]
        sha256=_digest(path),
        size_bytes=path.stat().st_size,
    )


def _pushed_repo(tmp_path: Path) -> tuple[Path, str]:
    bare = tmp_path / "remote.git"
    repo = tmp_path / "workspace"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    init_test_git_repo(repo)
    _git(repo, "branch", "-M", "main")
    tracked = repo / "tracked.png"
    tracked.write_bytes(b"tracked-v1")
    _git(repo, "add", "tracked.png")
    _git(repo, "commit", "-qm", "seed")
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-qu", "origin", "main")
    _git(repo, "remote", "set-head", "origin", "-a")
    return repo, _git(repo, "rev-parse", "HEAD")


def _install_inventory(monkeypatch: Any, repo: Path, *, include: bool = True) -> None:
    records: tuple[RepoRecord, ...] = ()
    if include:
        clone = RepoCloneRecord(WORKSPACE_NUM, str(repo), True)
        records = (
            RepoRecord(
                name=PROJECT,
                kind="primary",
                project=PROJECT,
                project_key=PROJECT,
                path=str(repo),
                exists=True,
                auto_clone=False,
                description=None,
                source="test",
                env_name=None,
                clones=(clone,),
            ),
        )
    monkeypatch.setattr(
        "sase.core.artifact_capture_policy.collect_repo_inventory",
        lambda **_kwargs: RepoInventory(records),
    )


def _decide(
    candidates: list[CaptureCandidate],
    *,
    repo: Path,
    artifacts_dir: Path,
    run_started_at: float,
    limits: CaptureLimits = LIMITS,
) -> list[Any]:
    return decide_captures(
        candidates,
        artifacts_dir=artifacts_dir,
        workspace_dir=repo,
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        run_started_at=run_started_at,
        probe=GitVcsProbe(),
        limits=limits,
    )


@pytest.mark.parametrize("origin", ["changed", "mentioned"])
def test_pushed_exact_content_becomes_reference(
    monkeypatch: Any,
    tmp_path: Path,
    origin: str,
) -> None:
    repo, sha = _pushed_repo(tmp_path)
    _install_inventory(monkeypatch, repo)

    [decision] = _decide(
        [_candidate(repo / "tracked.png", origin)],
        repo=repo,
        artifacts_dir=tmp_path / "artifacts",
        run_started_at=time.time(),
    )

    assert decision.outcome == "reference"
    assert decision.reason == "vcs_reproducible"
    assert (decision.vcs_repo, decision.vcs_sha, decision.vcs_relpath) == (
        PROJECT,
        sha,
        "tracked.png",
    )


def test_uncommitted_and_unpushed_content_store_bytes(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    repo, _sha = _pushed_repo(tmp_path)
    _install_inventory(monkeypatch, repo)
    tracked = repo / "tracked.png"
    tracked.write_bytes(b"uncommitted")

    [uncommitted] = _decide(
        [_candidate(tracked)],
        repo=repo,
        artifacts_dir=tmp_path / "artifacts",
        run_started_at=time.time(),
    )
    assert (uncommitted.outcome, uncommitted.reason) == ("store", "changed")

    _git(repo, "add", "tracked.png")
    _git(repo, "commit", "-qm", "local only")
    [unpushed] = _decide(
        [_candidate(tracked)],
        repo=repo,
        artifacts_dir=tmp_path / "artifacts",
        run_started_at=time.time(),
    )
    assert (unpushed.outcome, unpushed.reason) == ("store", "changed")


def test_authorship_and_mentioned_file_matrix(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    repo, _sha = _pushed_repo(tmp_path)
    _install_inventory(monkeypatch, repo)
    run_started_at = time.time() - 1
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    artifact_file = artifacts_dir / "render.png"
    artifact_file.write_bytes(b"render")
    untracked = repo / "untracked.png"
    untracked.write_bytes(b"untracked")
    os.utime(untracked, (0, 0))
    recent = repo / "recent.png"
    recent.write_bytes(b"recent")
    external = tmp_path / "input.png"
    external.write_bytes(b"input")
    os.utime(external, (0, 0))

    decisions = _decide(
        [
            _candidate(untracked),
            _candidate(artifact_file, "mentioned"),
            _candidate(untracked, "mentioned"),
            _candidate(recent, "mentioned"),
            _candidate(external, "mentioned"),
        ],
        repo=repo,
        artifacts_dir=artifacts_dir,
        run_started_at=run_started_at,
    )

    assert [(row.outcome, row.reason) for row in decisions] == [
        ("store", "changed"),
        ("store", "artifacts_dir"),
        ("skip", "mentioned_repo"),
        ("store", "run_window"),
        ("store", "mentioned_external"),
    ]


def test_unknown_inventory_and_probe_errors_fail_safe_to_store(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    repo, _sha = _pushed_repo(tmp_path)
    _install_inventory(monkeypatch, repo, include=False)
    candidate = _candidate(repo / "tracked.png", "mentioned")
    [unknown] = _decide(
        [candidate],
        repo=repo,
        artifacts_dir=tmp_path / "artifacts",
        run_started_at=time.time(),
    )
    assert (unknown.outcome, unknown.reason) == ("store", "vcs_probe_failed")

    class RaisingProbe:
        def repo_toplevel(self, path: str) -> str | None:
            raise RuntimeError(path)

    [failed] = decide_captures(
        [candidate],
        artifacts_dir=tmp_path / "artifacts",
        workspace_dir=repo,
        project=PROJECT,
        workspace_num=WORKSPACE_NUM,
        run_started_at=time.time(),
        probe=RaisingProbe(),  # type: ignore[arg-type]
        limits=LIMITS,
    )
    assert (failed.outcome, failed.reason) == ("store", "vcs_probe_failed")


def test_store_cap_does_not_count_references(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    repo, _sha = _pushed_repo(tmp_path)
    _install_inventory(monkeypatch, repo)
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    os.utime(first, (0, 0))
    os.utime(second, (0, 0))

    decisions = _decide(
        [
            _candidate(first, "mentioned"),
            _candidate(repo / "tracked.png"),
            _candidate(second, "mentioned"),
        ],
        repo=repo,
        artifacts_dir=tmp_path / "artifacts",
        run_started_at=time.time(),
        limits=CaptureLimits(max_stored_per_agent=1, max_history_scan=20),
    )

    assert [row.outcome for row in decisions] == ["store", "reference", "skip"]
    assert decisions[-1].reason == "capture_cap"


@pytest.mark.parametrize(
    ("config", "stored", "history"),
    [
        ({}, 50, 20),
        ({"artifacts": {"capture": {"max_stored_per_agent": 7}}}, 7, 20),
        ({"artifacts": {"capture": {"max_history_scan": 3}}}, 50, 3),
        ({"artifacts": {"capture": {"max_stored_per_agent": 0}}}, 50, 20),
        ({"artifacts": {"capture": {"max_history_scan": True}}}, 50, 20),
        ({"artifacts": []}, 50, 20),
        ({"artifacts": {"capture": "invalid"}}, 50, 20),
    ],
)
def test_capture_config_accessors_validate_values(
    monkeypatch: Any,
    config: dict[str, Any],
    stored: int,
    history: int,
) -> None:
    monkeypatch.setattr(config_core, "load_merged_config", lambda: config)

    assert config_core.get_artifact_capture_max_stored_per_agent() == stored
    assert config_core.get_artifact_capture_max_history_scan() == history


def test_capture_config_default_and_schema() -> None:
    root = Path(__file__).parents[1]
    defaults = yaml.safe_load(
        (root / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (root / "src/sase/config/sase.schema.json").read_text(encoding="utf-8")
    )

    assert defaults["artifacts"]["capture"] == {
        "max_stored_per_agent": 50,
        "max_history_scan": 20,
    }
    capture = schema["properties"]["artifacts"]["properties"]["capture"]
    assert capture["additionalProperties"] is False
    assert capture["properties"]["max_stored_per_agent"] == {
        "type": "integer",
        "minimum": 1,
        "default": 50,
        "description": (
            "Maximum number of automatic artifact captures whose bytes are copied "
            "per agent run. Version-control-backed references are not counted and "
            "are not capped."
        ),
    }
    assert capture["properties"]["max_history_scan"]["minimum"] == 1
    assert capture["properties"]["max_history_scan"]["default"] == 20
