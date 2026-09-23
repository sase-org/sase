"""Launch-time eviction of bead sidecar stores must preserve local commits."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.axe import runner_workspace_sidecar as workspace_module
from sase.axe.runner_workspace import prepare_launch_workspace_repos
from sase.axe.runner_workspace_beads import _workspace_bead_store_dirs
from sase.axe.runner_workspace_prepare import protect_unpushed_sidecar_commits
from sase.axe.runner_workspace_sidecar import _workspace_sidecar_repo_roots
from sase.bead.sync import unpushed_bead_commit_count

from .sync_conflict_regression_helpers import _git
from .sync_test_helpers import init_git_repo
from .workspace_sidecar_eviction_test_helpers import (
    _WORKSPACE_NUM,
    _bundle_holds_sha,
    _commit_unpushed_claim,
    _fail_publish,
    _record_clone,
    _redirect_state,
    _rescue_bundles,
    _rescue_entries,
    _seed_workspace_sidecar_beads,
    _seed_workspace_sidecar_repo,
)


@pytest.fixture(autouse=True)
def _clear_publication_memo():
    workspace_module._FAILED_PUBLICATIONS.clear()
    yield
    workspace_module._FAILED_PUBLICATIONS.clear()


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
    assert protect_unpushed_sidecar_commits(str(workspace))
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
