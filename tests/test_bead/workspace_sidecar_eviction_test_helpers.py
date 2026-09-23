"""Shared seeds and assertions for workspace sidecar eviction tests."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead.sync import commit_bead_claim, unpushed_bead_commit_count

from .sync_conflict_regression_helpers import _clone, _commit, _git
from .sync_test_helpers import init_git_repo

_WORKSPACE_NUM = 7


def _redirect_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[tuple[object, ...]]]:
    """Point SASE_HOME and notifications at tmp; return home and sent notes."""
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    notified: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "sase.notifications.notify_workflow_complete",
        lambda *args, **kwargs: notified.append((*args, kwargs)),
    )
    return home, notified


def _rescue_bundles(home: Path) -> list[Path]:
    root = home / "rescue"
    if not root.is_dir():
        return []
    return sorted(root.glob("*/*/local-commits.bundle"))


def _rescue_entries(home: Path) -> list[Path]:
    root = home / "rescue"
    if not root.is_dir():
        return []
    return sorted(
        entry
        for month in root.iterdir()
        if month.is_dir()
        for entry in month.iterdir()
        if entry.is_dir()
    )


def _bundle_holds_sha(bundle: Path, sha: str, tmp_path: Path, base: Path) -> bool:
    """Fetch the bundle into a clone of *base* and prove *sha* is restorable."""
    heads = subprocess.run(
        ["git", "bundle", "list-heads", str(bundle)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if sha not in heads:
        return False
    probe = tmp_path / f"probe-{bundle.parent.name}"
    subprocess.run(
        ["git", "clone", "-q", str(base), str(probe)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "fetch", str(bundle), "refs/*:refs/sase/rescued/x/*"],
        cwd=probe,
        check=True,
        capture_output=True,
        text=True,
    )
    return (
        subprocess.run(
            ["git", "cat-file", "-e", sha], cwd=probe, capture_output=True
        ).returncode
        == 0
    )


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


def _seed_workspace_sidecar_repo(
    tmp_path: Path,
    *,
    branch: str = "main",
    remote_name: str = "origin",
    role: str = "plans",
) -> tuple[Path, Path, Path]:
    """Build a numbered workspace with one direct sidecar repo clone."""
    remote = tmp_path / f"{role}-remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", branch, str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / f"{role}-seed"
    seed.mkdir()
    init_git_repo(seed)
    _git(seed, "branch", "-M", branch)
    (seed / "README.md").write_text(f"# {role}\n", encoding="utf-8")
    _commit(seed, f"seed {role} sidecar")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", branch)

    workspace = tmp_path / f"project_{_WORKSPACE_NUM}"
    workspace.mkdir()
    init_git_repo(workspace)
    sidecar = workspace / "sase" / "repos" / role
    sidecar.parent.mkdir(parents=True)
    _clone(remote, sidecar)
    if remote_name != "origin":
        _git(sidecar, "remote", "rename", "origin", remote_name)
        _git(sidecar, "branch", "--set-upstream-to", f"{remote_name}/{branch}", branch)
    return workspace, sidecar, remote


def _commit_unpushed_claim(sidecar: Path, phase_id: str) -> str:
    """Write and commit a canonical bead mutation that never reaches origin."""
    with BeadProject(sidecar, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        _issue, changed = project.claim_for_agent_wait(phase_id, "local-agent")
    assert changed
    assert commit_bead_claim(sidecar, phase_id, "local-agent")
    assert unpushed_bead_commit_count(sidecar, sidecar) == 1
    return _git(sidecar, "rev-parse", "HEAD").stdout.strip()


def _commit_sidecar_file(
    repo: Path,
    relpath: str,
    text: str,
    message: str,
) -> str:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _commit(repo, message, relpath.split("/", 1)[0])
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _commit_unpushed_sidecar_file(sidecar: Path) -> str:
    return _commit_sidecar_file(
        sidecar,
        "202609/rollout.md",
        "# Plan\n",
        "archive rollout plan",
    )


def _damage_sidecar_unborn_head(sidecar: Path) -> None:
    _git(sidecar, "symbolic-ref", "HEAD", "refs/heads/master")


def _commit_remote_sidecar_file(
    tmp_path: Path,
    remote: Path,
    relpath: str,
    text: str,
    message: str,
    *,
    writer_name: str = "remote-writer",
) -> str:
    writer = tmp_path / writer_name
    _clone(remote, writer)
    commit = _commit_sidecar_file(writer, relpath, text, message)
    _git(writer, "push")
    return commit


def _remote_file(remote: Path, relpath: str, *, ref: str = "main") -> str:
    return _git(remote, "show", f"{ref}:{relpath}").stdout


def _record_clone(clones: list[tuple[str, int, bool]]):
    def ensure_workspace_sdd_clone(
        workspace_dir: str, workspace_num: int, *, strict: bool = False
    ) -> None:
        clones.append((workspace_dir, workspace_num, strict))

    return ensure_workspace_sdd_clone


def _fail_publish(sync_log: Path, attempts: list[Path]):
    def publish(beads_dir: Path, **kwargs: object) -> SimpleNamespace:
        attempts.append(beads_dir)
        return SimpleNamespace(
            pushed=False,
            error="injected managed sync failure",
            log_path=sync_log,
        )

    return publish
