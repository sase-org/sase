"""Fixture-repository regressions for concurrent bead event writers."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.bead.sync_worker import run_managed_sync_worker
from sase.sdd._commit_store import push_sdd_store_after_commit
from sase.sdd._repository_transaction import (
    SddIntegrationStatus,
    integrate_sdd_repository,
)
from sase.sdd.store import SddStore

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


def test_generic_sdd_push_reconciles_same_stream_and_derived_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, left, right, epic_id, first_id, second_id = _seed_same_stream_remote(
        tmp_path
    )
    with BeadProject(left, beads_dirname="beads") as project:
        project.update(first_id, title="First from left")
    _commit(left, "left same-stream append", "beads")
    with BeadProject(right, beads_dirname="beads") as project:
        project.update(second_id, title="Second from right")
    _commit(right, "right same-stream append", "beads")
    _git(right, "push")

    log_path = tmp_path / "generic-sdd-sync.log"
    monkeypatch.setattr(
        "sase.bead.sync._new_sync_log_path",
        lambda: log_path,
    )
    store = SddStore(
        storage="separate_repo",
        sdd_dir=left,
        repo_root=left,
        remote_url=str(remote),
    )

    push_sdd_store_after_commit(store, push_after_commit=True)

    assert _git(left, "status", "--porcelain").stdout == ""
    assert not (left / ".git/rebase-merge").exists()
    assert not (left / ".git/rebase-apply").exists()
    assert _git(left, "diff", "--name-only", "--diff-filter=U").stdout == ""
    stream_path = left / f"beads/events/streams/{epic_id}.jsonl"
    assert len(stream_path.read_text(encoding="utf-8").splitlines()) == 5
    projection = [
        json.loads(line)
        for line in (left / "beads/issues.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(projection) == 3
    assert len({row["id"] for row in projection}) == 3
    assert (
        json.loads((left / "beads/events/manifest.json").read_text(encoding="utf-8"))[
            "stream_count"
        ]
        == 1
    )

    verify = tmp_path / "verify-same-stream"
    _clone(remote, verify)
    with BeadProject(verify, beads_dirname="beads") as project:
        assert project.show(first_id).title == "First from left"
        assert project.show(second_id).title == "Second from right"

    records = _log_records(log_path)
    resolution = next(
        record for record in records if record["event"] == "conflict_resolution"
    )
    assert set(resolution["resolved_files"]) == {
        f"beads/events/streams/{epic_id}.jsonl",
        "beads/events/manifest.json",
        "beads/issues.jsonl",
    }
    integration = next(record for record in records if record["event"] == "integration")
    assert set(integration["resolved_files"]) == set(resolution["resolved_files"])


def _generated_issue_artifacts(
    root: Path, prefix: str, title: str
) -> tuple[str, str, Path]:
    root.mkdir()
    with BeadProject.init(root, beads_dirname="beads") as project:
        issue = project.create(title, IssueType.PLAN)
    beads_dir = root / "beads"
    issue_line = next(
        line
        for line in (beads_dir / "issues.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    )
    return issue.id, issue_line, beads_dir / f"events/streams/{issue.id}.jsonl"


def test_clean_rebase_repairs_stale_manifest_and_repeated_sync_is_noop(
    tmp_path: Path,
) -> None:
    base_id, base_line, base_stream = _generated_issue_artifacts(
        tmp_path / "generated-base", "base", "Base"
    )
    left_id, left_line, left_stream = _generated_issue_artifacts(
        tmp_path / "generated-left", "left", "Left"
    )
    right_id, right_line, right_stream = _generated_issue_artifacts(
        tmp_path / "generated-right", "right", "Right"
    )

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
    beads_dir = seed / "beads"
    streams_dir = beads_dir / "events/streams"
    streams_dir.mkdir(parents=True)
    shutil.copyfile(base_stream, streams_dir / f"{base_id}.jsonl")
    shutil.copyfile(
        tmp_path / "generated-base/beads/config.json",
        beads_dir / "config.json",
    )
    projection_lines = [""] * 31
    projection_lines[15] = base_line
    (beads_dir / "issues.jsonl").write_text(
        "\n".join(projection_lines) + "\n",
        encoding="utf-8",
    )
    (beads_dir / "events/manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stream_count": 1,
                "generated_from": "issues.jsonl",
                "migration_tool": "sase-core bead events",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (seed / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    _commit(seed, "seed padded projection")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    left = tmp_path / "left"
    right = tmp_path / "right"
    _clone(remote, left)
    _clone(remote, right)
    left_projection = (left / "beads/issues.jsonl").read_text().splitlines()
    left_projection[2] = left_line
    (left / "beads/issues.jsonl").write_text(
        "\n".join(left_projection) + "\n", encoding="utf-8"
    )
    shutil.copyfile(
        left_stream,
        left / f"beads/events/streams/{left_id}.jsonl",
    )
    manifest = json.loads((left / "beads/events/manifest.json").read_text())
    manifest["stream_count"] = 2
    (left / "beads/events/manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    _commit(left, "left adds a stream", "beads")

    right_projection = (right / "beads/issues.jsonl").read_text().splitlines()
    right_projection[27] = right_line
    (right / "beads/issues.jsonl").write_text(
        "\n".join(right_projection) + "\n", encoding="utf-8"
    )
    shutil.copyfile(
        right_stream,
        right / f"beads/events/streams/{right_id}.jsonl",
    )
    (right / "beads/events/manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    _commit(right, "right adds a stream", "beads")
    _git(right, "push")

    log_path = tmp_path / "clean-rebase-sync.log"
    outcome = run_managed_sync_worker(left, left / "beads", log_path=log_path)

    assert outcome.pushed is True
    assert outcome.integrated is True
    assert _git(left, "status", "--porcelain").stdout == ""
    assert _git(left, "log", "-1", "--format=%s").stdout.strip() == (
        "chore(beads): repair event manifest"
    )
    assert (
        json.loads((left / "beads/events/manifest.json").read_text(encoding="utf-8"))[
            "stream_count"
        ]
        == 3
    )
    assert {
        json.loads(line)["id"]
        for line in (left / "beads/issues.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    } == {base_id, left_id, right_id}
    records = _log_records(log_path)
    repair = next(
        record
        for record in records
        if record["event"] == "manifest_repair" and record["status"] == "repaired"
    )
    assert repair["repaired_files"] == ["beads/events/manifest.json"]
    integration = next(record for record in records if record["event"] == "integration")
    assert integration["resolved_files"] == ["beads/events/manifest.json"]

    second = run_managed_sync_worker(left, left / "beads", log_path=log_path)
    assert second.pushed is True
    assert second.integrated is False
    assert [
        record["status"]
        for record in _log_records(log_path)
        if record["event"] == "manifest_repair"
    ][-1] == "noop"


@pytest.mark.parametrize("invalid_kind", ["rewrite", "corrupt"])
def test_invalid_same_stream_aborts_to_exact_starting_state(
    tmp_path: Path,
    invalid_kind: str,
) -> None:
    _remote, left, right, epic_id, first_id, second_id = _seed_same_stream_remote(
        tmp_path
    )
    with BeadProject(left, beads_dirname="beads") as project:
        project.update(first_id, title="Left append")
    stream_path = left / f"beads/events/streams/{epic_id}.jsonl"
    lines = stream_path.read_text(encoding="utf-8").splitlines()
    if invalid_kind == "rewrite":
        rewritten = json.loads(lines[0])
        rewritten["actor"] = "rewriter@example.com"
        lines[0] = json.dumps(rewritten, separators=(",", ":"))
    else:
        lines[-1] = "not json"
    stream_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _commit(left, f"left {invalid_kind}", "beads")
    with BeadProject(right, beads_dirname="beads") as project:
        project.update(second_id, title="Right append")
    _commit(right, "right append", "beads")
    _git(right, "push")
    untracked = left / "keep-untracked.txt"
    untracked.write_text("keep\n", encoding="utf-8")
    starting = _status_snapshot(left)

    outcome = integrate_sdd_repository(left, beads_dir=left / "beads")

    assert outcome.status is SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS
    assert outcome.restored is True
    if invalid_kind == "rewrite":
        assert "non-append-only" in (outcome.error or "")
    else:
        assert "Expecting value" in (outcome.error or "")
    assert _status_snapshot(left) == starting
    assert untracked.read_text(encoding="utf-8") == "keep\n"
    assert not (left / ".git/rebase-merge").exists()
    assert not (left / ".git/rebase-apply").exists()
    assert _git(left, "diff", "--name-only", "--diff-filter=U").stdout == ""


def test_mixed_bead_and_non_bead_conflicts_abort_exactly(
    tmp_path: Path,
) -> None:
    _remote, left, right, _epic_id, first_id, second_id = _seed_same_stream_remote(
        tmp_path
    )
    with BeadProject(left, beads_dirname="beads") as project:
        project.update(first_id, title="Left append")
    (left / "notes.txt").write_text("left\n", encoding="utf-8")
    _commit(left, "left mixed changes")
    with BeadProject(right, beads_dirname="beads") as project:
        project.update(second_id, title="Right append")
    (right / "notes.txt").write_text("right\n", encoding="utf-8")
    _commit(right, "right mixed changes")
    _git(right, "push")
    untracked = left / "keep-untracked.txt"
    untracked.write_text("keep\n", encoding="utf-8")
    starting = _status_snapshot(left)

    outcome = integrate_sdd_repository(left, beads_dir=left / "beads")

    assert outcome.status is SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS
    assert outcome.restored is True
    assert "non-bead conflicts remain: notes.txt" in (outcome.error or "")
    assert _status_snapshot(left) == starting
    assert untracked.read_text(encoding="utf-8") == "keep\n"
    assert not (left / ".git/rebase-merge").exists()
    assert not (left / ".git/rebase-apply").exists()
    assert _git(left, "diff", "--name-only", "--diff-filter=U").stdout == ""


def test_clean_rebase_with_invalid_stream_resets_completed_integration(
    tmp_path: Path,
) -> None:
    _remote, left, right, _epic_id, _first_id, _second_id = _seed_same_stream_remote(
        tmp_path
    )
    (left / "local.md").write_text("local\n", encoding="utf-8")
    _commit(left, "local non-conflicting change", "local.md")
    corrupt_stream = right / "beads/events/streams/corrupt.jsonl"
    corrupt_stream.write_text("not json\n", encoding="utf-8")
    manifest_path = right / "beads/events/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["stream_count"] = 2
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _commit(right, "remote corrupt stream", "beads")
    _git(right, "push")
    untracked = left / "keep-untracked.txt"
    untracked.write_text("keep\n", encoding="utf-8")
    starting = _status_snapshot(left)

    outcome = integrate_sdd_repository(left, beads_dir=left / "beads")

    assert outcome.status is SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS
    assert outcome.restored is True
    assert "invalid bead event stream" in (outcome.error or "")
    assert _status_snapshot(left) == starting
    assert untracked.read_text(encoding="utf-8") == "keep\n"
    assert not (left / "beads/events/streams/corrupt.jsonl").exists()
    assert not (left / ".git/rebase-merge").exists()
    assert not (left / ".git/rebase-apply").exists()
    assert _git(left, "diff", "--name-only", "--diff-filter=U").stdout == ""
