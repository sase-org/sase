"""Workspace-preparation regressions for sidecar bead commits."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.axe.runner_workspace import _top_level_beads_dir, prepare_workspace
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead.sync import (
    commit_bead_claim,
    push_bead_work_launch,
    unpushed_bead_commit_count,
)
from sase.sdd._repository_recovery_reaper import safe_reap_sdd_recovery_snapshots
from sase.vcs_provider import VCS_DEFAULT_REVISION

from .sync_conflict_regression_helpers import _git, _seed_claim_soak_remote


@pytest.mark.parametrize(
    "beads_dirname",
    ["beads", BEADS_DIRNAME_ROOT],
    ids=["plans-embedded", "repo-root"],
)
def test_prepare_workspace_rescues_unpushed_bead_commits_before_sidecar_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    beads_dirname: str,
) -> None:
    _remote, local, upstream_writer, phase_ids = _seed_claim_soak_remote(
        tmp_path,
        phase_count=2,
        beads_dirname=beads_dirname,
    )
    local_phase, upstream_phase = phase_ids
    local_beads = local / beads_dirname
    upstream_beads = upstream_writer / beads_dirname
    with BeadProject(local, beads_dirname=beads_dirname) as project:
        _issue, changed = project.claim_for_agent_wait(local_phase, "local-agent")
    assert changed
    assert commit_bead_claim(local_beads, local_phase, "local-agent")
    local_commit = _git(local, "rev-parse", "HEAD").stdout.strip()

    with BeadProject(upstream_writer, beads_dirname=beads_dirname) as project:
        _issue, changed = project.claim_for_agent_wait(
            upstream_phase,
            "upstream-agent",
        )
    assert changed
    assert commit_bead_claim(
        upstream_beads,
        upstream_phase,
        "upstream-agent",
    )
    _git(upstream_writer, "push")
    _git(local, "fetch", "origin")
    assert unpushed_bead_commit_count(local, local_beads) == 1

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

    assert sync_attempts == [local_beads]
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


def test_top_level_beads_dir_recognizes_supported_store_layouts(
    tmp_path: Path,
) -> None:
    embedded = tmp_path / "embedded"
    (embedded / "beads").mkdir(parents=True)
    assert _top_level_beads_dir(embedded) == embedded / "beads"

    config_root = tmp_path / "config-root"
    config_root.mkdir()
    (config_root / "config.json").write_text("{}\n", encoding="utf-8")
    assert _top_level_beads_dir(config_root) == config_root

    events_root = tmp_path / "events-root"
    (events_root / "events").mkdir(parents=True)
    assert _top_level_beads_dir(events_root) == events_root

    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "issues.jsonl").write_text("", encoding="utf-8")
    assert _top_level_beads_dir(plain) is None


def test_push_bead_work_launch_publishes_root_layout_store(tmp_path: Path) -> None:
    remote, local, _upstream_writer, phase_ids = _seed_claim_soak_remote(
        tmp_path,
        phase_count=1,
        beads_dirname=BEADS_DIRNAME_ROOT,
    )
    phase_id = phase_ids[0]
    with BeadProject(local, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        _issue, changed = project.claim_for_agent_wait(phase_id, "local-agent")
    assert changed
    assert commit_bead_claim(local, phase_id, "local-agent")
    assert unpushed_bead_commit_count(local, local) == 1

    outcome = push_bead_work_launch(local)

    assert outcome.pushed is True
    assert outcome.error is None
    assert unpushed_bead_commit_count(local, local) == 0
    branch = _git(local, "symbolic-ref", "--short", "HEAD").stdout.strip()
    assert (
        _git(remote, "rev-parse", f"refs/heads/{branch}").stdout.strip()
        == _git(local, "rev-parse", "HEAD").stdout.strip()
    )
