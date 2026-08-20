"""Regression tests for bead sync repair and exact repository rollback."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.bead.sync_worker import run_managed_sync_worker
from sase.core import bead_mutation_facade
from sase.sdd._repository_transaction import (
    SddIntegrationStatus,
    integrate_sdd_repository,
)

from .sync_conflict_regression_helpers import (
    _clone,
    _commit,
    _git,
    _log_records,
    _seed_same_stream_remote,
    _status_snapshot,
)
from .sync_test_helpers import init_git_repo


def _generated_issue_artifacts(root: Path, title: str) -> tuple[str, str, Path]:
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
        tmp_path / "generated-base", "Base"
    )
    left_id, left_line, left_stream = _generated_issue_artifacts(
        tmp_path / "generated-left", "Left"
    )
    right_id, right_line, right_stream = _generated_issue_artifacts(
        tmp_path / "generated-right", "Right"
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


def test_managed_sync_worker_reports_duplicate_create_relocation_and_rewrites_subject(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "duplicate-create.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "duplicate-seed"
    seed.mkdir()
    init_git_repo(seed)
    _git(seed, "branch", "-M", "main")
    (seed / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname="beads"):
        pass
    _commit(seed, "seed empty bead store")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    left = tmp_path / "left-duplicate"
    right = tmp_path / "right-duplicate"
    _clone(remote, left)
    _clone(remote, right)

    upstream, _ = bead_mutation_facade.create(
        right / "beads",
        title="Upstream wins",
        issue_type=IssueType.PLAN,
        now="2026-08-20T00:00:00Z",
    )
    _commit(right, f"right creates {upstream.id}", "beads")
    _git(right, "push")

    local, _ = bead_mutation_facade.create(
        left / "beads",
        title="Local relocates",
        issue_type=IssueType.PLAN,
        now="2026-08-20T00:00:01Z",
    )
    assert local.id == upstream.id
    _commit(left, f"chore(beads): create {local.id}", "beads")

    log_path = tmp_path / "duplicate-create-sync.log"
    outcome = run_managed_sync_worker(left, left / "beads", log_path=log_path)

    assert outcome.pushed is True
    assert outcome.integrated is True
    assert len(outcome.bead_relocations) == 1
    relocation = outcome.bead_relocations[0]
    assert relocation.old_id == local.id
    assert relocation.new_id == f"{local.id.rsplit('-', 1)[0]}-2"
    assert relocation.kind == "top_level_duplicate"
    assert _git(left, "log", "-1", "--format=%s").stdout.strip() == (
        f"chore(beads): create {relocation.new_id}"
    )
    assert _git(left, "status", "--porcelain").stdout == ""
    with BeadProject(left, beads_dirname="beads") as project:
        assert project.show(upstream.id).title == "Upstream wins"
        assert project.show(relocation.new_id).title == "Local relocates"
    records = _log_records(log_path)
    rewrite = next(
        record for record in records if record["event"] == "relocation_subject_rewrite"
    )
    assert rewrite["rewritten"] is True
    completed = records[-1]
    assert completed["event"] == "completed"
    assert completed["bead_relocations"] == [
        {
            "old_id": relocation.old_id,
            "new_id": relocation.new_id,
            "kind": "top_level_duplicate",
        }
    ]


@pytest.mark.parametrize("invalid_kind", ["rewrite", "corrupt"])
def test_managed_sync_worker_invalid_stream_restores_exact_starting_state(
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

    outcome = run_managed_sync_worker(
        left,
        left / "beads",
        log_path=tmp_path / f"{invalid_kind}-sync.log",
    )

    assert outcome.pushed is False
    assert outcome.integrated is False
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


def test_concurrently_minted_bead_id_relocates_instead_of_wedging_sync(
    tmp_path: Path,
) -> None:
    """Two clones minting the same id must not deadlock the shared store.

    Both clones allocate from their own ``next_counter``, so each new bead
    lands on the same id and the same stream file. Before relocation the
    merged stream held two ``issue_created`` events for that id, every sync
    worker failed reducing it, and the store stayed wedged behind the retry.
    """
    _remote, left, right, _epic_id, _first_id, _second_id = _seed_same_stream_remote(
        tmp_path
    )
    with BeadProject(left, beads_dirname="beads") as project:
        left_bead = project.create(
            "Left task", IssueType.TASK, task_type="bug", size="small"
        )
    _commit(left, "left mints a bead", "beads")
    with BeadProject(right, beads_dirname="beads") as project:
        right_bead = project.create(
            "Right task", IssueType.TASK, task_type="bug", size="small"
        )
    _commit(right, "right mints a bead", "beads")
    _git(right, "push")
    assert left_bead.id == right_bead.id

    outcome = run_managed_sync_worker(
        left,
        left / "beads",
        log_path=tmp_path / "duplicate-id-sync.log",
    )

    assert outcome.error is None
    assert outcome.pushed is True
    assert outcome.integrated is True
    assert _git(left, "status", "--porcelain").stdout == ""
    assert not (left / ".git/rebase-merge").exists()

    titles = {
        json.loads(line)["title"]
        for line in (left / "beads/issues.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    }
    assert {"Left task", "Right task"} <= titles

    resolution = next(
        record
        for record in _log_records(tmp_path / "duplicate-id-sync.log")
        if record["event"] == "conflict_resolution"
    )
    assert f"relocated duplicate beads: {left_bead.id} -> " in str(
        resolution["message"]
    )

    # The relocated bead must be a real, mintable id: the next create in
    # either clone has to land past it rather than colliding all over again.
    with BeadProject(left, beads_dirname="beads") as project:
        follow_up = project.create(
            "Follow up", IssueType.TASK, task_type="bug", size="small"
        )
    assert follow_up.id not in {
        json.loads(line)["id"]
        for line in (left / "beads/issues.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and json.loads(line)["title"] != "Follow up"
    }
