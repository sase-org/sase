"""Launch-time eviction must never destroy unpublished sidecar bead commits."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.axe import runner_workspace_sidecar as workspace_module
from sase.axe.runner_workspace import prepare_launch_workspace_repos
from sase.axe.runner_workspace_beads import _workspace_bead_store_dirs
from sase.axe.runner_workspace_prepare import _WorkspaceBeadEvictionRefused
from sase.axe.runner_workspace_sidecar import _workspace_sidecar_repo_roots
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


def test_eviction_publishes_unpushed_plans_sidecar_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    local_commit = _commit_unpushed_sidecar_file(plans)
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert _git(remote, "rev-parse", "refs/heads/main").stdout.strip() == local_commit
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert not (workspace / "sase" / "repos").exists()


def test_eviction_integrates_disjoint_remote_plan_commit_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    _commit_unpushed_sidecar_file(plans)
    _commit_remote_sidecar_file(
        tmp_path,
        remote,
        "202609/remote.md",
        "# Remote\n",
        "archive remote plan",
    )
    clones: list[tuple[str, int, bool]] = []
    notified: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )
    monkeypatch.setattr(
        "sase.notifications.notify_workflow_complete",
        lambda *args, **kwargs: notified.append((*args, kwargs)),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert _remote_file(remote, "202609/rollout.md") == "# Plan\n"
    assert _remote_file(remote, "202609/remote.md") == "# Remote\n"
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert notified == []
    assert not (workspace / "sase" / "repos").exists()


def test_eviction_converges_when_equivalent_plan_change_is_already_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    _commit_unpushed_sidecar_file(plans)
    _commit_remote_sidecar_file(
        tmp_path,
        remote,
        "202609/rollout.md",
        "# Plan\n",
        "archive equivalent rollout plan",
    )
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert _remote_file(remote, "202609/rollout.md") == "# Plan\n"
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert not (workspace / "sase" / "repos").exists()


def test_eviction_retries_when_remote_writer_wins_after_first_integration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    _commit_unpushed_sidecar_file(plans)
    _commit_remote_sidecar_file(
        tmp_path,
        remote,
        "202609/first-remote.md",
        "# First\n",
        "archive first remote plan",
    )
    clones: list[tuple[str, int, bool]] = []
    push_calls = 0
    actual_push = workspace_module._run_sidecar_push

    def push_with_race(repo: Path) -> subprocess.CompletedProcess[str]:
        nonlocal push_calls
        push_calls += 1
        if push_calls == 2:
            _commit_remote_sidecar_file(
                tmp_path,
                remote,
                "202609/race.md",
                "# Race\n",
                "archive racing remote plan",
                writer_name="remote-race-writer",
            )
        return actual_push(repo)

    monkeypatch.setattr(
        "sase.axe.runner_workspace_sidecar._run_sidecar_push",
        push_with_race,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert push_calls == 3
    assert _remote_file(remote, "202609/rollout.md") == "# Plan\n"
    assert _remote_file(remote, "202609/first-remote.md") == "# First\n"
    assert _remote_file(remote, "202609/race.md") == "# Race\n"
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]


def test_eviction_stops_within_bound_when_remote_keeps_advancing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    _commit_unpushed_sidecar_file(plans)
    local_path = plans / "202609" / "rollout.md"
    clones: list[tuple[str, int, bool]] = []
    push_calls = 0
    actual_push = workspace_module._run_sidecar_push

    def push_after_remote_advances(repo: Path) -> subprocess.CompletedProcess[str]:
        nonlocal push_calls
        push_calls += 1
        _commit_remote_sidecar_file(
            tmp_path,
            remote,
            f"202609/remote-{push_calls}.md",
            f"# Remote {push_calls}\n",
            f"archive remote plan {push_calls}",
            writer_name=f"advancing-writer-{push_calls}",
        )
        return actual_push(repo)

    monkeypatch.setattr(
        "sase.axe.runner_workspace_sidecar._run_sidecar_push",
        push_after_remote_advances,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    with pytest.raises(_WorkspaceBeadEvictionRefused):
        prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert push_calls == 3
    assert clones == []
    assert (plans / ".git").is_dir()
    assert local_path.read_text(encoding="utf-8") == "# Plan\n"
    refs = _recovery_refs(plans)
    assert len(refs) == 1
    stderr = capsys.readouterr().err
    assert "retry limit is exhausted" in stderr
    assert refs[0][0] in stderr


def test_eviction_preserves_sidecar_when_rebase_conflicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    local_commit = _commit_sidecar_file(
        plans,
        "README.md",
        "# local\n",
        "edit local readme",
    )
    _commit_remote_sidecar_file(
        tmp_path,
        remote,
        "README.md",
        "# remote\n",
        "edit remote readme",
    )
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    with pytest.raises(_WorkspaceBeadEvictionRefused):
        prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert clones == []
    assert (plans / ".git").is_dir()
    assert _git(plans, "rev-parse", "HEAD").stdout.strip() == local_commit
    assert not (plans / ".git" / "rebase-merge").exists()
    assert not (plans / ".git" / "rebase-apply").exists()
    assert _recovery_refs(plans)
    assert "git rebase failed" in capsys.readouterr().err


def test_eviction_uses_configured_non_origin_upstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(
        tmp_path,
        branch="stable",
        remote_name="mirror",
    )
    _commit_unpushed_sidecar_file(plans)
    _commit_remote_sidecar_file(
        tmp_path,
        remote,
        "202609/mirror.md",
        "# Mirror\n",
        "archive mirror plan",
    )
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert _remote_file(remote, "202609/rollout.md", ref="stable") == "# Plan\n"
    assert _remote_file(remote, "202609/mirror.md", ref="stable") == "# Mirror\n"
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]


def test_eviction_refuses_to_trash_unpublished_plans_sidecar_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    local_commit = _commit_unpushed_sidecar_file(plans)
    clones: list[tuple[str, int, bool]] = []
    notified: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        "sase.axe.runner_workspace_sidecar._run_sidecar_push",
        lambda _repo: subprocess.CompletedProcess(
            ["git", "push"],
            1,
            stdout="",
            stderr="injected sidecar push failure",
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )
    monkeypatch.setattr(
        "sase.notifications.notify_workflow_complete",
        lambda *args, **kwargs: notified.append((*args, kwargs)),
    )

    with pytest.raises(_WorkspaceBeadEvictionRefused):
        prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert clones == []
    assert not (workspace / ".sase" / "trash").exists()
    assert (plans / ".git").is_dir()
    assert _git(plans, "rev-parse", "HEAD").stdout.strip() == local_commit
    assert _git(remote, "rev-parse", "refs/heads/main").stdout.strip() != local_commit
    refs = _recovery_refs(plans)
    assert len(refs) == 1
    assert refs[0][1] == local_commit
    stderr = capsys.readouterr().err
    assert refs[0][0] in stderr
    assert "injected sidecar push failure" in stderr
    assert len(notified) == 1
    sender, cl_name, success, notes, kwargs = notified[0]
    assert sender == "sidecar-protection"
    assert cl_name == ""
    assert success is False
    assert any("Failed to publish sidecar" in note for note in notes)
    assert any(refs[0][0] in note for note in notes)
    assert kwargs["extra_files"] == [str(plans.resolve())]


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

    with pytest.raises(_WorkspaceBeadEvictionRefused):
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


def test_workspace_sidecar_repo_roots_finds_direct_git_roles(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    plans = workspace / "sase" / "repos" / "plans"
    research = workspace / "sase" / "repos" / "research"
    linked = workspace / "sase" / "repos" / "linked" / "tooling"
    for repo in (plans, research, linked):
        repo.mkdir(parents=True)
        init_git_repo(repo)
    (workspace / "sase" / "repos" / "scratch").mkdir()

    assert _workspace_sidecar_repo_roots(workspace) == [
        plans.resolve(),
        research.resolve(),
    ]
