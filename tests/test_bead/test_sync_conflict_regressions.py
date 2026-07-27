"""Fixture-repository regressions for concurrent bead event writers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest

from sase.axe.runner_workspace import prepare_workspace
from sase.bead.claims import claim_bead_for_waiting_agent
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.sync import (
    bead_sync_diagnostics,
    commit_bead_claim,
)
from sase.bead.sync_worker import run_managed_sync_worker
from sase.sdd._commit_store import push_sdd_store_after_commit
from sase.sdd._repository_transaction import (
    SddIntegrationOutcome,
    SddIntegrationStatus,
    integrate_sdd_repository,
)
from sase.sdd._repository_recovery_reaper import safe_reap_sdd_recovery_snapshots
from sase.sdd._store_link import _pull_sdd_clone
from sase.sdd.store import SddStore
from sase.vcs_provider import VCS_DEFAULT_REVISION

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


def _seed_claim_soak_remote(
    tmp_path: Path,
    *,
    phase_count: int,
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
    (seed / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname="beads") as project:
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


def test_concurrent_claim_soak_preserves_commits_without_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claims wait at the historical post-resolution/pre-continue race window."""
    _remote, local, upstream_writer, phase_ids = _seed_claim_soak_remote(
        tmp_path,
        phase_count=9,
    )
    upstream_phase, initial_local_phase, *concurrent_phases = phase_ids

    with BeadProject(upstream_writer, beads_dirname="beads") as project:
        _issue, changed = project.claim_for_agent_wait(
            upstream_phase,
            "upstream-agent",
        )
    assert changed
    assert commit_bead_claim(
        upstream_writer / "beads",
        upstream_phase,
        "upstream-agent",
    )
    _git(upstream_writer, "push")

    with BeadProject(local, beads_dirname="beads") as project:
        _issue, changed = project.claim_for_agent_wait(
            initial_local_phase,
            "local-agent-0",
        )
    assert changed
    assert commit_bead_claim(
        local / "beads",
        initial_local_phase,
        "local-agent-0",
    )

    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: local / "beads",
    )
    concurrent_materialized = threading.Event()
    original_claim = BeadProject.claim_for_agent_wait

    def observe_materialization(
        self: BeadProject,
        bead_id: str,
        agent_name: str,
    ) -> tuple[object, bool]:
        result = original_claim(self, bead_id, agent_name)
        if self.root_dir == local.resolve() and bead_id in concurrent_phases:
            concurrent_materialized.set()
        return result

    monkeypatch.setattr(
        BeadProject,
        "claim_for_agent_wait",
        observe_materialization,
    )

    from sase.sdd import _repository_transaction

    continue_ready = threading.Event()
    allow_continue = threading.Event()
    real_runner = _repository_transaction.default_git_runner

    def pause_before_rebase_continue(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if repo_root.resolve() == local.resolve() and args == [
            "-c",
            "core.editor=true",
            "rebase",
            "--continue",
        ]:
            continue_ready.set()
            assert allow_continue.wait(10.0)
        return real_runner(repo_root, args, op=op, network=network)

    monkeypatch.setattr(
        _repository_transaction,
        "default_git_runner",
        pause_before_rebase_continue,
    )
    outcomes: list[SddIntegrationOutcome] = []
    real_integrate = _repository_transaction.integrate_machine_managed_sdd_repository

    def capture_outcome(*args: object, **kwargs: object) -> SddIntegrationOutcome:
        outcome = real_integrate(*args, **kwargs)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(
        _repository_transaction,
        "integrate_machine_managed_sdd_repository",
        capture_outcome,
    )
    axe_errors: list[dict[str, object]] = []
    monkeypatch.setattr("sase.axe.state.append_error", axe_errors.append)

    with ThreadPoolExecutor(max_workers=len(concurrent_phases) + 1) as pool:
        integration = pool.submit(_pull_sdd_clone, local, fresh=True)
        assert continue_ready.wait(10.0)
        claims = [
            pool.submit(
                claim_bead_for_waiting_agent,
                project_name="hermetic-claim-soak",
                bead_id=bead_id,
                agent_name=f"local-agent-{index}",
            )
            for index, bead_id in enumerate(concurrent_phases, start=1)
        ]

        # Before the fix, these mutations landed in the resolved rebase
        # worktree and made ``rebase --continue`` report unstaged changes.
        assert not concurrent_materialized.wait(0.2)
        allow_continue.set()

        assert integration.result(timeout=20.0)
        assert all(claim.result(timeout=20.0) for claim in claims)

    assert outcomes
    assert outcomes[0].status is SddIntegrationStatus.REPAIRED_BEAD_CONFLICTS
    assert outcomes[0].status is not SddIntegrationStatus.UNRECOVERABLE
    assert axe_errors == []
    assert (
        _git(
            local,
            "for-each-ref",
            "--format=%(refname)",
            "refs/sase/recovery/",
        ).stdout
        == ""
    )
    assert (
        "sase recovery refs/sase/recovery/"
        not in _git(
            local,
            "stash",
            "list",
            "--format=%gs",
        ).stdout
    )
    assert _git(local, "status", "--porcelain").stdout == ""

    expected_claims = {
        upstream_phase: "upstream-agent",
        initial_local_phase: "local-agent-0",
        **{
            bead_id: f"local-agent-{index}"
            for index, bead_id in enumerate(concurrent_phases, start=1)
        },
    }
    with BeadProject(local, beads_dirname="beads") as project:
        for bead_id, agent_name in expected_claims.items():
            issue = project.show(bead_id)
            assert (issue.status, issue.assignee) == (Status.CLAIMED, agent_name)

    subjects = _git(local, "log", "--format=%s").stdout.splitlines()
    for bead_id, agent_name in expected_claims.items():
        assert f"chore(beads): claim {bead_id} for {agent_name}" in subjects


def test_bead_sync_diagnostics_reports_recovery_residue_and_local_commits(
    tmp_path: Path,
) -> None:
    _remote, local, _upstream_writer, phase_ids = _seed_claim_soak_remote(
        tmp_path,
        phase_count=1,
    )
    phase_id = phase_ids[0]
    with BeadProject(local, beads_dirname="beads") as project:
        _issue, changed = project.claim_for_agent_wait(phase_id, "local-agent")
    assert changed
    assert commit_bead_claim(local / "beads", phase_id, "local-agent")

    recovery_ref = "refs/sase/recovery/20260726T120000Z-main-test"
    _git(local, "update-ref", recovery_ref, "HEAD")
    (local / "recovery-note.txt").write_text("retained\n", encoding="utf-8")
    _git(
        local,
        "stash",
        "push",
        "--include-untracked",
        "-m",
        f"sase recovery {recovery_ref}",
    )

    messages = bead_sync_diagnostics(local / "beads")

    assert "WARNING: bead store has 1 unpushed local bead commit(s)" in messages
    assert "WARNING: bead store retains 1 recovery ref(s)" in messages
    assert "WARNING: bead store retains 1 recovery stash(es)" in messages


def test_prepare_workspace_rescues_unpushed_bead_commits_before_sidecar_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _remote, local, upstream_writer, phase_ids = _seed_claim_soak_remote(
        tmp_path,
        phase_count=2,
    )
    local_phase, upstream_phase = phase_ids
    with BeadProject(local, beads_dirname="beads") as project:
        _issue, changed = project.claim_for_agent_wait(local_phase, "local-agent")
    assert changed
    assert commit_bead_claim(local / "beads", local_phase, "local-agent")
    local_commit = _git(local, "rev-parse", "HEAD").stdout.strip()

    with BeadProject(upstream_writer, beads_dirname="beads") as project:
        _issue, changed = project.claim_for_agent_wait(
            upstream_phase,
            "upstream-agent",
        )
    assert changed
    assert commit_bead_claim(
        upstream_writer / "beads",
        upstream_phase,
        "upstream-agent",
    )
    _git(upstream_writer, "push")
    _git(local, "fetch", "origin")

    sync_log = tmp_path / "failed-sync.log"
    sync_attempts: list[Path] = []

    def fail_publish(beads_dir: Path) -> SimpleNamespace:
        sync_attempts.append(beads_dir)
        return SimpleNamespace(
            pushed=False,
            error="injected managed sync failure",
            log_path=sync_log,
        )

    class ResettingProvider:
        checkout_revisions: list[str]

        def __init__(self) -> None:
            self.checkout_revisions = []

        def get_default_parent_revision(self, cwd: str) -> str:
            return "origin/main"

        def checkout(self, revision: str, cwd: str) -> tuple[bool, str | None]:
            self.checkout_revisions.append(revision)
            _git(Path(cwd), "reset", "--hard", revision)
            return True, None

        def sync_workspace(self, cwd: str) -> tuple[bool, str | None]:
            return True, None

    provider = ResettingProvider()
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fail_publish)
    monkeypatch.setattr(
        "sase.workflows.commit_utils.run_sase_hg_clean",
        lambda *_args: (True, ""),
    )
    monkeypatch.setattr(
        "sase.axe.runner_workspace.get_vcs_provider",
        lambda _cwd: provider,
    )

    assert prepare_workspace(
        str(local),
        "sidecar",
        VCS_DEFAULT_REVISION,
    )

    assert sync_attempts == [local / "beads"]
    assert provider.checkout_revisions == ["origin/main"]
    assert _git(local, "rev-parse", "HEAD").stdout.strip() != local_commit
    recovery_refs = [
        line.split("\0")
        for line in _git(
            local,
            "for-each-ref",
            "--format=%(refname)%00%(objectname)",
            "refs/sase/recovery/",
        )
        .stdout.strip()
        .splitlines()
        if line.strip()
    ]
    assert len(recovery_refs) == 1
    assert recovery_refs[0][1] == local_commit
    recovery_ref = recovery_refs[0][0]

    safe_reap_sdd_recovery_snapshots(
        local,
        now=4_102_444_800.0,
        logger=lambda _message: None,
    )

    assert (
        _git(local, "rev-parse", "--verify", recovery_ref).stdout.strip()
        == local_commit
    )


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
