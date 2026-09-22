"""Launch-time eviction must never destroy unpublished sidecar bead commits."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.axe import runner_workspace_sidecar as workspace_module
from sase.axe.runner_workspace import prepare_launch_workspace_repos
from sase.axe.runner_workspace_beads import _workspace_bead_store_dirs
from sase.axe.runner_workspace_prepare import _protect_unpushed_sidecar_commits
from sase.axe.runner_workspace_sidecar import _workspace_sidecar_repo_roots
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead.sync import commit_bead_claim, unpushed_bead_commit_count

from .sync_conflict_regression_helpers import _clone, _commit, _git
from .sync_test_helpers import init_git_repo

_WORKSPACE_NUM = 7


@pytest.fixture(autouse=True)
def _clear_publication_memo():
    workspace_module._FAILED_PUBLICATIONS.clear()
    yield
    workspace_module._FAILED_PUBLICATIONS.clear()


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


def test_eviction_quarantines_unborn_head_sidecar_and_reclones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, _remote = _seed_workspace_sidecar_repo(tmp_path)
    _damage_sidecar_unborn_head(plans)
    home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []

    def recreate_plans_sidecar(
        workspace_dir: str, workspace_num: int, *, strict: bool = False
    ) -> None:
        clones.append((workspace_dir, workspace_num, strict))
        fresh = Path(workspace_dir) / "sase" / "repos" / "plans"
        fresh.mkdir(parents=True)
        init_git_repo(fresh)

    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        recreate_plans_sidecar,
    )

    cloned_sidecars = prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert cloned_sidecars == {str(plans.resolve())}
    assert (plans / ".git").is_dir()
    # The damaged clone was quarantined into the durable rescue store outside
    # the workspace — never into the workspace itself — and eviction proceeded.
    assert not (workspace / ".sase" / "sidecar-quarantine").exists()
    entries = _rescue_entries(home)
    assert len(entries) == 1
    quarantined = entries[0] / "quarantined-clone"
    assert (quarantined / ".git").is_dir()
    assert len(notified) == 1
    sender, _cl_name, _success, notes, kwargs = notified[0]
    assert sender == "workspace-rescue"
    assert any("quarantin" in note for note in notes)
    assert any(str(entries[0]) in note for note in notes)
    assert kwargs["extra_files"] == [str(entries[0])]


def test_eviction_proceeds_when_damaged_sidecar_quarantine_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, plans, _remote = _seed_workspace_sidecar_repo(tmp_path)
    _damage_sidecar_unborn_head(plans)
    _home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.workspace_provider.rescue.quarantine_directory",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    stderr = capsys.readouterr().err
    assert "may lose local commits" in stderr
    assert "proceeding with eviction" in stderr
    assert len(notified) == 1
    sender, _cl_name, success, _notes, _kwargs = notified[0]
    assert sender == "workspace-rescue"
    assert success is False


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


def test_eviction_rescues_when_remote_keeps_advancing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    _commit_unpushed_sidecar_file(plans)
    home, notified = _redirect_state(tmp_path, monkeypatch)
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

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    # The push policy still stops within its bound, but the launch no longer
    # fails: the local work is rescued and eviction proceeds. (Integration
    # rebased the commit, so the bundle holds the rebased HEAD carrying the
    # local file, not the original SHA.)
    assert push_calls == 3
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    bundles = _rescue_bundles(home)
    assert len(bundles) == 1
    probe = tmp_path / "probe-rescued"
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(probe)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "fetch", str(bundles[0]), "refs/*:refs/sase/rescued/x/*"],
        cwd=probe,
        check=True,
        capture_output=True,
        text=True,
    )
    rescued = subprocess.run(
        ["git", "show", "refs/sase/rescued/x/heads/main:202609/rollout.md"],
        cwd=probe,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert rescued == "# Plan\n"
    stderr = capsys.readouterr().err
    assert "retry limit is exhausted" in stderr
    assert str(bundles[0].parent) in stderr
    assert len(notified) == 1
    assert notified[0][0] == "workspace-rescue"


def test_eviction_rescues_sidecar_when_rebase_conflicts(
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
    home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    # The conflicting commit was never published, but it survives in the
    # rescue bundle instead of failing the launch.
    assert _git(remote, "rev-parse", "refs/heads/main").stdout.strip() != local_commit
    bundles = _rescue_bundles(home)
    assert len(bundles) == 1
    assert _bundle_holds_sha(bundles[0], local_commit, tmp_path, remote)
    assert "git rebase failed" in capsys.readouterr().err
    assert len(notified) == 1
    assert notified[0][0] == "workspace-rescue"


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


def test_eviction_rescues_unpublished_plans_sidecar_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, plans, remote = _seed_workspace_sidecar_repo(tmp_path)
    local_commit = _commit_unpushed_sidecar_file(plans)
    home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []

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

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    # Eviction proceeds: the unpublished commit survives in a restorable
    # rescue bundle instead of failing the launch.
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert _git(remote, "rev-parse", "refs/heads/main").stdout.strip() != local_commit
    bundles = _rescue_bundles(home)
    assert len(bundles) == 1
    assert _bundle_holds_sha(bundles[0], local_commit, tmp_path, remote)
    stderr = capsys.readouterr().err
    assert str(bundles[0].parent) in stderr
    assert "injected sidecar push failure" in stderr
    assert len(notified) == 1
    sender, _cl_name, _success, notes, kwargs = notified[0]
    assert sender == "workspace-rescue"
    assert any(str(bundles[0].parent) in note for note in notes)
    assert kwargs["extra_files"] == [str(bundles[0].parent)]


def test_eviction_rescues_unpublished_sidecar_bead_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace, sidecar, phase_id = _seed_workspace_sidecar_beads(tmp_path)
    local_commit = _commit_unpushed_claim(sidecar, phase_id)
    home, notified = _redirect_state(tmp_path, monkeypatch)
    beads_remote = tmp_path / "beads-remote.git"

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

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    # Exactly one publication attempt, then rescue and eviction proceed.
    assert sync_attempts == [sidecar]
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert not (workspace / "sase" / "repos").exists()
    bundles = _rescue_bundles(home)
    assert len(bundles) == 1
    assert _bundle_holds_sha(bundles[0], local_commit, tmp_path, beads_remote)
    assert str(bundles[0].parent) in capsys.readouterr().err
    assert len(notified) == 1
    assert notified[0][0] == "workspace-rescue"


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


def test_launch_publishes_once_and_rescues_once_for_wedged_bead_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Incident regression: tolerant prep plus eviction publish exactly once."""
    workspace, sidecar, phase_id = _seed_workspace_sidecar_beads(tmp_path)
    local_commit = _commit_unpushed_claim(sidecar, phase_id)
    home, notified = _redirect_state(tmp_path, monkeypatch)

    sync_attempts: list[Path] = []
    clones: list[tuple[str, int, bool]] = []

    def fail_publish_once(beads_dir: Path, **kwargs: object) -> object:
        sync_attempts.append(beads_dir)
        from types import SimpleNamespace

        return SimpleNamespace(
            pushed=False,
            error=(
                "semantic conflict resolution failed: validation: cannot merge "
                "non-append-only bead event stream"
            ),
            log_path=tmp_path / "failed-sync.log",
        )

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fail_publish_once)
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    # The ordinary preparation pass attempts publication and warns; the
    # launch eviction pass must not re-publish at the same HEAD.
    assert _protect_unpushed_sidecar_commits(str(workspace))
    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert sync_attempts == [sidecar]
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert len(_rescue_entries(home)) == 1
    bundles = _rescue_bundles(home)
    assert len(bundles) == 1
    assert _bundle_holds_sha(
        bundles[0], local_commit, tmp_path, tmp_path / "beads-remote.git"
    )
    assert len(notified) == 1
    assert notified[0][0] == "workspace-rescue"


def test_generic_pass_skips_bead_roots_handled_by_bead_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, sidecar, phase_id = _seed_workspace_sidecar_beads(tmp_path)
    _commit_unpushed_claim(sidecar, phase_id)
    _git(sidecar, "push")
    assert unpushed_bead_commit_count(sidecar, sidecar) == 0
    _redirect_state(tmp_path, monkeypatch)

    sync_attempts: list[Path] = []
    generic_pushes: list[Path] = []
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        _fail_publish(tmp_path / "unused-sync.log", sync_attempts),
    )
    monkeypatch.setattr(
        "sase.axe.runner_workspace_sidecar._run_sidecar_push",
        lambda repo: (
            generic_pushes.append(repo)
            or subprocess.CompletedProcess(["git", "push"], 0, stdout="", stderr="")
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    # Nothing was unpublished, so neither pass touches the bead store — and
    # the plain-git generic path never republishes a bead root it was told
    # the bead pass already handled.
    assert sync_attempts == []
    assert generic_pushes == []
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]


def test_eviction_rescues_when_bead_count_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, sidecar, phase_id = _seed_workspace_sidecar_beads(tmp_path)
    _commit_unpushed_claim(sidecar, phase_id)
    _git(sidecar, "push")
    home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.bead.sync.unpushed_bead_commit_count_result",
        lambda _repo, _beads: (0, "injected git failure"),
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    # Unknown is not zero: the store is rescued, never silently evicted.
    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert len(_rescue_entries(home)) == 1
    assert len(notified) == 1
    assert notified[0][0] == "workspace-rescue"


def test_eviction_rescues_when_sidecar_count_is_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, plans, _remote = _seed_workspace_sidecar_repo(tmp_path)
    home, notified = _redirect_state(tmp_path, monkeypatch)
    clones: list[tuple[str, int, bool]] = []
    monkeypatch.setattr(
        "sase.axe.runner_workspace_sidecar._unpushed_sidecar_commit_count",
        lambda _repo: workspace_module._SidecarCommitCountResult(
            count=0, error="injected git failure", damaged=False
        ),
    )
    monkeypatch.setattr(
        "sase.sdd.store.ensure_workspace_sdd_clone",
        _record_clone(clones),
    )

    prepare_launch_workspace_repos(str(workspace), _WORKSPACE_NUM)

    assert clones == [(str(workspace), _WORKSPACE_NUM, True)]
    assert len(_rescue_entries(home)) == 1
    assert len(notified) == 1
    assert notified[0][0] == "workspace-rescue"
