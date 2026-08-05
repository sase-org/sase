"""Launch-time eviction must never destroy unpublished sidecar bead commits."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.axe.runner_workspace import (
    WorkspaceBeadEvictionRefused,
    _workspace_bead_store_dirs,
    prepare_launch_workspace_repos,
)
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead.sync import commit_bead_claim, unpushed_bead_commit_count

from .sync_conflict_regression_helpers import _clone, _commit, _git
from .sync_test_helpers import init_git_repo

_WORKSPACE_NUM = 7


def _seed_workspace_sidecar_beads(tmp_path: Path) -> tuple[Path, Path, str]:
    """Build a numbered workspace whose beads sidecar clone tracks a remote."""
    remote = tmp_path / "beads-remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "beads-seed"
    seed.mkdir()
    init_git_repo(seed)
    _git(seed, "branch", "-M", "main")
    (seed / ".gitignore").write_text("beads.db*\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        epic = project.create("Sidecar eviction", IssueType.PLAN)
        phase_id = project.create(
            "Sidecar phase",
            IssueType.PHASE,
            parent_id=epic.id,
        ).id
    _commit(seed, "seed sidecar bead graph")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    workspace = tmp_path / f"project_{_WORKSPACE_NUM}"
    workspace.mkdir()
    init_git_repo(workspace)
    sidecar = workspace / "sase" / "repos" / "beads"
    sidecar.parent.mkdir(parents=True)
    _clone(remote, sidecar)
    return workspace, sidecar, phase_id


def _commit_unpushed_claim(sidecar: Path, phase_id: str) -> str:
    """Write and commit a canonical bead mutation that never reaches origin."""
    with BeadProject(sidecar, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        _issue, changed = project.claim_for_agent_wait(phase_id, "local-agent")
    assert changed
    assert commit_bead_claim(sidecar, phase_id, "local-agent")
    assert unpushed_bead_commit_count(sidecar, sidecar) == 1
    return _git(sidecar, "rev-parse", "HEAD").stdout.strip()


def _recovery_refs(repo: Path) -> list[tuple[str, str]]:
    listing = _git(
        repo,
        "for-each-ref",
        "--format=%(refname)%00%(objectname)",
        "refs/sase/recovery/",
    ).stdout
    return [
        (line.split("\0")[0], line.split("\0")[1])
        for line in listing.splitlines()
        if line.strip()
    ]


def _record_clone(clones: list[tuple[str, int, bool]]):
    def ensure_workspace_sdd_clone(
        workspace_dir: str, workspace_num: int, *, strict: bool = False
    ) -> None:
        clones.append((workspace_dir, workspace_num, strict))

    return ensure_workspace_sdd_clone


def _fail_publish(sync_log: Path, attempts: list[Path]):
    def publish(beads_dir: Path) -> SimpleNamespace:
        attempts.append(beads_dir)
        return SimpleNamespace(
            pushed=False,
            error="injected managed sync failure",
            log_path=sync_log,
        )

    return publish


def test_eviction_refuses_to_trash_unpublished_sidecar_bead_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, sidecar, phase_id = _seed_workspace_sidecar_beads(tmp_path)
    local_commit = _commit_unpushed_claim(sidecar, phase_id)

    sync_attempts: list[Path] = []
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        _fail_publish(tmp_path / "failed-sync.log", sync_attempts),
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    with pytest.raises(WorkspaceBeadEvictionRefused):
        prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert sync_attempts == [sidecar]
    # The clone that holds the only copy of the close is neither trashed nor
    # replaced, and its commit stays reachable through a recovery ref.
    assert clones == []
    assert not (workspace / ".sase" / "trash").exists()
    assert (sidecar / ".git").is_dir()
    assert _git(sidecar, "rev-parse", "HEAD").stdout.strip() == local_commit
    assert unpushed_bead_commit_count(sidecar, sidecar) == 1
    refs = _recovery_refs(sidecar)
    assert len(refs) == 1
    assert refs[0][1] == local_commit
    assert refs[0][0] in capsys.readouterr().err


def test_eviction_proceeds_for_a_fully_published_sidecar_bead_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, sidecar, phase_id = _seed_workspace_sidecar_beads(tmp_path)
    _commit_unpushed_claim(sidecar, phase_id)
    _git(sidecar, "push")
    assert unpushed_bead_commit_count(sidecar, sidecar) == 0

    sync_attempts: list[Path] = []
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        _fail_publish(tmp_path / "unused-sync.log", sync_attempts),
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    # Nothing was unpublished, so the barrier stays out of the launch path.
    assert sync_attempts == []
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert not (workspace / "sase" / "repos").exists()


def test_workspace_bead_store_dirs_finds_both_sidecar_layouts(
    tmp_path: Path,
) -> None:
    split = tmp_path / "split"
    (split / "sase" / "repos" / "beads" / "events").mkdir(parents=True)
    assert _workspace_bead_store_dirs(split) == [
        split / "sase" / "repos" / "beads",
    ]

    combined = tmp_path / "combined"
    plans_beads = combined / "sase" / "repos" / "plans" / "beads"
    plans_beads.mkdir(parents=True)
    (plans_beads / "config.json").write_text("{}\n", encoding="utf-8")
    assert _workspace_bead_store_dirs(combined) == [plans_beads]

    bare = tmp_path / "bare"
    (bare / "sase" / "repos" / "beads").mkdir(parents=True)
    assert _workspace_bead_store_dirs(bare) == []
