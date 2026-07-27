"""Workspace-preparation regressions for sidecar bead commits."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.axe.runner_workspace import prepare_workspace
from sase.bead.project import BeadProject
from sase.bead.sync import commit_bead_claim
from sase.sdd._repository_recovery_reaper import safe_reap_sdd_recovery_snapshots
from sase.vcs_provider import VCS_DEFAULT_REVISION

from .test_sync_conflict_regressions import _git, _seed_claim_soak_remote


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
