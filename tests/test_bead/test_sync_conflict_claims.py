"""Regression tests for concurrent bead claims during repository sync."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import threading

import pytest

from sase.bead.claims import claim_bead_for_waiting_agent
from sase.bead.model import Status
from sase.bead.project import BeadProject
from sase.bead.sync import bead_sync_diagnostics, commit_bead_claim
from sase.sdd._repository_transaction import (
    SddIntegrationOutcome,
    SddIntegrationStatus,
)
from sase.sdd._store_link import _pull_sdd_clone

from .sync_conflict_regression_helpers import (
    _git,
    _seed_claim_soak_remote,
)


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
