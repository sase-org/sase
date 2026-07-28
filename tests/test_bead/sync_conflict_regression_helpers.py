"""Shared fixture-repository helpers for bead sync conflict regressions."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any

from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.core import bead_conflict_facade, bead_mutation_facade

from .sync_test_helpers import configure_git_identity, init_git_repo


def _git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        capture_output=True,
        text=True,
    )


def _commit(repo: Path, message: str, *paths: str) -> None:
    _git(repo, "add", "--", *(paths or (".",)))
    _git(repo, "commit", "-m", message)


def _clone(remote: Path, target: Path) -> None:
    subprocess.run(
        ["git", "clone", str(remote), str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    configure_git_identity(target)


def _seed_same_stream_remote(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str, str, str]:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    init_git_repo(seed)
    _git(seed, "branch", "-M", "main")
    (seed / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    (seed / "notes.txt").write_text("base\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname="beads") as project:
        epic = project.create("Epic", IssueType.PLAN)
        first = project.create("First", IssueType.PHASE, parent_id=epic.id)
        second = project.create("Second", IssueType.PHASE, parent_id=epic.id)
    _commit(seed, "seed bead stream")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    left = tmp_path / "left"
    right = tmp_path / "right"
    _clone(remote, left)
    _clone(remote, right)
    return remote, left, right, epic.id, first.id, second.id


def _seed_replay_divergence(
    tmp_path: Path,
) -> tuple[Path, Path, Path, tuple[str, str], str]:
    """Create two clones ready for deterministic, multi-stream divergence."""
    remote = tmp_path / "replay.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "replay-seed"
    seed.mkdir()
    init_git_repo(seed)
    _git(seed, "branch", "-M", "main")
    (seed / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname="beads"):
        pass
    first, _outcome = bead_mutation_facade.create(
        seed / "beads",
        title="First contested stream",
        issue_type=IssueType.PLAN,
        now="2026-07-27T00:00:00Z",
    )
    second, _outcome = bead_mutation_facade.create(
        seed / "beads",
        title="Second contested stream",
        issue_type=IssueType.PLAN,
        now="2026-07-27T00:00:01Z",
    )
    quiet, _outcome = bead_mutation_facade.create(
        seed / "beads",
        title="Quiét — untouched",
        issue_type=IssueType.PLAN,
        now="2026-07-27T00:00:02Z",
    )
    _commit(seed, "seed replay streams")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    local = tmp_path / "replay-local"
    upstream = tmp_path / "replay-upstream"
    _clone(remote, local)
    _clone(remote, upstream)
    return remote, local, upstream, (first.id, second.id), quiet.id


def _build_replay_histories(
    local: Path,
    upstream: Path,
    contested_ids: tuple[str, str],
) -> None:
    """Write the incident shape: four local commits over interleaved upstream."""
    first_id, second_id = contested_ids
    local_updates = [
        (
            first_id,
            "2026-07-27T00:04:00Z",
            {"title": "First from local commit one"},
        ),
        (
            second_id,
            "2026-07-27T00:06:00Z",
            {"notes": "Second from local commit two"},
        ),
        (
            first_id,
            "2026-07-27T00:08:00Z",
            {"description": "First from local commit three"},
        ),
        (
            second_id,
            "2026-07-27T00:10:00Z",
            {"design": "Second from local commit four"},
        ),
    ]
    for index, (issue_id, now, fields) in enumerate(local_updates, start=1):
        bead_mutation_facade.update(
            local / "beads",
            issue_id,
            **fields,
            now=now,
        )
        _commit(local, f"local bead mutation {index}", "beads")

    upstream_updates = [
        (
            first_id,
            "2026-07-27T00:03:00Z",
            {"notes": "First from upstream"},
        ),
        (
            second_id,
            "2026-07-27T00:05:00Z",
            {"description": "Second from upstream"},
        ),
    ]
    for index, (issue_id, now, fields) in enumerate(upstream_updates, start=1):
        bead_mutation_facade.update(
            upstream / "beads",
            issue_id,
            **fields,
            now=now,
        )
        _commit(upstream, f"upstream bead mutation {index}", "beads")


def _read_streams(repo: Path) -> list[dict[str, Any]]:
    streams = []
    for path in sorted((repo / "beads/events/streams").glob("*.jsonl")):
        streams.append(
            {
                "stream_id": path.stem,
                "root_issue_id": path.stem,
                "events": [
                    json.loads(line)
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ],
            }
        )
    return streams


def _event_records_by_id(repo: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for stream in _read_streams(repo):
        for event in stream["events"]:
            assert isinstance(event, dict)
            event_id = str(event["event_id"])
            assert event_id not in records
            records[event_id] = event
    return records


def _bead_artifact_bytes(repo: Path) -> dict[str, bytes]:
    beads_dir = repo / "beads"
    paths = [
        *sorted((beads_dir / "events/streams").glob("*.jsonl")),
        beads_dir / "events/manifest.json",
        beads_dir / "issues.jsonl",
    ]
    return {path.relative_to(beads_dir).as_posix(): path.read_bytes() for path in paths}


def _assert_store_matches_fresh_reduction(repo: Path) -> None:
    streams = _read_streams(repo)
    expected_issues = bead_conflict_facade.reduce_event_streams(streams)
    expected_issue_bytes = "".join(
        json.dumps(issue, separators=(",", ":"), ensure_ascii=False) + "\n"
        for issue in expected_issues
    ).encode()
    expected_manifest_bytes = json.dumps(
        bead_conflict_facade.event_store_manifest(streams),
        indent=2,
        ensure_ascii=False,
    ).encode()
    assert (repo / "beads/issues.jsonl").read_bytes() == expected_issue_bytes
    assert (repo / "beads/events/manifest.json").read_bytes() == expected_manifest_bytes


def _opposite_direction_workspace(
    tmp_path: Path,
    *,
    name: str,
    upstream_repo: Path,
    local_repo: Path,
) -> tuple[Path, Path]:
    """Put one divergence direction on a fresh remote and working clone."""
    remote = tmp_path / f"{name}.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    upstream_head = _git(upstream_repo, "rev-parse", "HEAD").stdout.strip()
    local_head = _git(local_repo, "rev-parse", "HEAD").stdout.strip()
    _git(
        upstream_repo,
        "push",
        str(remote),
        f"{upstream_head}:refs/heads/main",
    )
    workspace = tmp_path / name
    _clone(remote, workspace)
    _git(workspace, "fetch", str(local_repo), local_head)
    _git(workspace, "reset", "--hard", "FETCH_HEAD")
    return remote, workspace


def _seed_claim_soak_remote(
    tmp_path: Path,
    *,
    phase_count: int,
    beads_dirname: str = "beads",
) -> tuple[Path, Path, Path, list[str]]:
    remote = tmp_path / "claim-soak.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "claim-soak-seed"
    seed.mkdir()
    init_git_repo(seed)
    _git(seed, "branch", "-M", "main")
    bead_prefix = "" if beads_dirname == BEADS_DIRNAME_ROOT else f"{beads_dirname}/"
    (seed / ".gitignore").write_text(
        f"{bead_prefix}beads.db*\n",
        encoding="utf-8",
    )
    with BeadProject.init(seed, beads_dirname=beads_dirname) as project:
        epic = project.create("Concurrent claim soak", IssueType.PLAN)
        phase_ids = [
            project.create(
                f"Concurrent phase {index}",
                IssueType.PHASE,
                parent_id=epic.id,
            ).id
            for index in range(phase_count)
        ]
    _commit(seed, "seed concurrent claim graph")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    local = tmp_path / "claim-soak-local"
    upstream_writer = tmp_path / "claim-soak-upstream"
    _clone(remote, local)
    _clone(remote, upstream_writer)
    return remote, local, upstream_writer, phase_ids


def _status_snapshot(repo: Path) -> tuple[str, str, str]:
    return (
        _git(repo, "symbolic-ref", "--short", "HEAD").stdout,
        _git(repo, "rev-parse", "HEAD").stdout,
        _git(
            repo,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ).stdout,
    )


def _log_records(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
