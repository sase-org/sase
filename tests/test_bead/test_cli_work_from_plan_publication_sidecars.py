"""Git sidecar publication coverage for plan-file ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.bead.cli_work_from_plan import work_from_plan_file
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.sdd.store import SddStore
from tests.test_bead.cli_work_helpers import FakeLaunchResult
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN
from tests.test_bead.cli_work_from_plan_publication_helpers import (
    linked_bead_id,
    stable_plan_formatting,
)
from tests.test_bead.sync_test_helpers import configure_git_identity


@pytest.fixture(autouse=True)
def _stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    stable_plan_formatting(monkeypatch)


def test_plan_file_launch_pushes_split_plans_archive_and_bead_link(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation
    from sase.sdd.frontmatter import parse_frontmatter

    plans_remote = tmp_path / "plans.git"
    beads_remote = tmp_path / "beads.git"
    plans = tmp_path / "plans-sidecar"
    beads = tmp_path / "beads-sidecar"
    _init_remote_clone(plans_remote, plans, readme="plans\n")
    _init_remote_clone(beads_remote, beads, readme=None)
    with BeadProject.init(beads, beads_dirname=BEADS_DIRNAME_ROOT):
        pass
    _git(beads, "add", "-A")
    _git(beads, "commit", "-m", "Initialize beads sidecar")
    _git(beads, "push", "-u", "origin", "main")

    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url=str(plans_remote),
        beads_dir=beads,
        beads_remote_url=str(beads_remote),
    )
    location = _BeadsLocation(
        root=beads,
        beads_dirname=BEADS_DIRNAME_ROOT,
        storage=store.storage,
        store=store,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._resolve_context",
        lambda *, dry_run: (location, store, project_dir),
    )
    monkeypatch.setattr("sase.sdd.files.get_yyyymm", lambda: "202607")

    def launch(project: BeadProject, epic_id: str, **kwargs: object) -> bool:
        before_agent_launch = kwargs["before_agent_launch"]
        assert callable(before_agent_launch)
        project.mark_ready_to_work(epic_id)
        before_agent_launch(project, epic_id)
        return True

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        launch,
    )
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    observer = tmp_path / "plans-observer"
    _git(tmp_path, "clone", str(plans_remote), str(observer))
    archived = observer / "202607" / "rollout.md"
    assert archived.is_file()
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        archived.read_text(encoding="utf-8")
    )
    assert frontmatter["bead_id"] == result.epic_id
    subjects = _git_output(observer, "log", "--format=%s").splitlines()
    assert "Archive approved plan rollout" in subjects
    assert "Link approved epic plan to its bead: rollout" in subjects


@pytest.mark.usefixtures("fake_cli_work_xprompts")
def test_git_sidecar_fresh_clone_sees_complete_graph_before_launch(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    remote = tmp_path / "plans.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    sidecar = tmp_path / "plans-sidecar"
    sidecar.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=sidecar,
        check=True,
        capture_output=True,
    )
    configure_git_identity(sidecar)
    with BeadProject.init(sidecar, beads_dirname="beads"):
        pass
    subprocess.run(["git", "add", "."], cwd=sidecar, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initialize plans sidecar"],
        cwd=sidecar,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        cwd=sidecar,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=sidecar,
        check=True,
        capture_output=True,
    )

    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=sidecar,
        repo_root=sidecar,
        remote_url=str(remote),
    )
    location = _BeadsLocation(
        root=sidecar,
        beads_dirname="beads",
        storage=store.storage,
        store=store,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._resolve_context",
        lambda *, dry_run: (location, store, project_dir),
    )

    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    observed: dict[str, object] = {}

    def inspect_fresh_worker_clone(
        _query: str,
        extra_env: object = None,
        segment_extra_env: object = None,
    ) -> FakeLaunchResult:
        del extra_env, segment_extra_env
        observer = tmp_path / "fresh-worker"
        subprocess.run(
            ["git", "clone", str(remote), str(observer)],
            check=True,
            capture_output=True,
        )
        archived = next(observer.glob("*/rollout.md"))
        epic_id = linked_bead_id(archived)
        with BeadProject(observer, beads_dirname="beads") as project:
            epic = project.show(epic_id)
            phases = project.get_epic_children(epic_id)
            observed["epic_id"] = epic_id
            observed["phase_ids"] = tuple(phase.id for phase in phases)
            assert epic.is_ready_to_work is True
            assert (epic.status.value, epic.assignee) == (
                "in_progress",
                f"{epic_id}.land",
            )
            assert [(phase.status.value, phase.assignee) for phase in phases] == [
                ("in_progress", phase.id) for phase in phases
            ]
            assert epic.design.startswith("plan:")
            assert epic.design.endswith("/rollout.md")
            assert [len(phase.dependencies) for phase in phases] == [0, 1, 2]
        return FakeLaunchResult()

    monkeypatch.setattr(
        "sase.agent.launcher.launch_agent_from_cwd",
        inspect_fresh_worker_clone,
    )

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert observed["epic_id"] == result.epic_id
    assert observed["phase_ids"] == result.phase_bead_ids
    commit_subjects = subprocess.run(
        ["git", "log", "--format=%s"],
        cwd=sidecar,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert (
        sum("checkpoint approved epic graph" in line for line in commit_subjects) == 1
    )
    # The checkpoint is the launch's only bead commit, so nothing may follow it.
    assert "checkpoint approved epic graph" in commit_subjects[0]


def _init_remote_clone(remote: Path, clone: Path, *, readme: str | None) -> None:
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(remote.parent, "clone", str(remote), str(clone))
    configure_git_identity(clone)
    if readme is None:
        return
    (clone / "README.md").write_text(readme, encoding="utf-8")
    _git(clone, "add", "README.md")
    _git(clone, "commit", "-m", "Initialize plans sidecar")
    _git(clone, "push", "-u", "origin", "main")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _git_output(cwd: Path, *args: str) -> str:
    return _git(cwd, *args).stdout.strip()
