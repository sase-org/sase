"""Launch-flow publication coverage for plan-file ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN, write_plan_update
from tests.test_bead.cli_work_from_plan_publication_helpers import (
    linked_bead_id,
    stable_plan_formatting,
)
from tests.test_bead.sync_test_helpers import configure_git_identity


@pytest.fixture(autouse=True)
def _stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    stable_plan_formatting(monkeypatch)


def test_plan_file_publishes_graph_before_launch_and_reconciles_afterward(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    sidecar = tmp_path / "plans-sidecar"
    with BeadProject.init(sidecar, beads_dirname="beads"):
        pass
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=sidecar,
        check=True,
        capture_output=True,
    )
    configure_git_identity(sidecar)
    subprocess.run(["git", "add", "."], cwd=sidecar, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initialize plans sidecar"],
        cwd=sidecar,
        check=True,
        capture_output=True,
    )
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=sidecar,
        repo_root=sidecar,
        remote_url="git@example.test:plans.git",
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
    events: list[tuple[str, object]] = []

    def commit_store(
        _store: SddStore,
        message: str,
        *,
        paths: list[Path],
        push_after_commit: bool,
        already_locked: bool = False,
    ) -> bool:
        del paths
        assert already_locked is not message.startswith("Archive approved plan")
        events.append(("commit", (message, push_after_commit)))
        return True

    def launch(_project: BeadProject, _epic_id: str, **kwargs: object) -> bool:
        before_agent_launch = kwargs["before_agent_launch"]
        assert callable(before_agent_launch)
        _project.mark_ready_to_work(_epic_id)
        before_agent_launch(_project, _epic_id)
        events.append(("launch", (kwargs["no_push"], kwargs["defer_push"])))
        return True

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit_store)
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        launch,
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda _beads_dir, epic_id: events.append(("graph-commit", epic_id)) or True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.bead_state_is_clean",
        lambda _beads_dir: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._publish_epic_graph_before_launch",
        lambda _store, *, no_push: events.append(("graph-push", no_push)) or True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._push_store_after_launch",
        lambda _store, **kwargs: events.append(("reconcile", kwargs["no_push"])),
    )

    work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    commit_events = [value for kind, value in events if kind == "commit"]
    assert len(commit_events) == 2
    assert all(
        push_after_commit is False for _message, push_after_commit in commit_events
    )
    graph_commit = next(
        i for i, event in enumerate(events) if event[0] == "graph-commit"
    )
    graph_push = next(i for i, event in enumerate(events) if event[0] == "graph-push")
    launch_event = next(i for i, event in enumerate(events) if event[0] == "launch")
    reconcile = next(i for i, event in enumerate(events) if event[0] == "reconcile")
    assert graph_commit < graph_push < launch_event < reconcile
    assert events[launch_event] == ("launch", (False, True))


def test_detached_store_no_push_preserves_linked_graph_without_launch(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    sidecar = tmp_path / "plans-sidecar"
    with BeadProject.init(sidecar, beads_dirname="beads"):
        pass
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=sidecar,
        repo_root=sidecar,
        remote_url="git@example.test:plans.git",
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
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    launch_reached = False

    def launch(project: BeadProject, epic_id: str, **kwargs: object) -> bool:
        nonlocal launch_reached
        if not project.show(epic_id).is_ready_to_work:
            project.mark_ready_to_work(epic_id)
        before_agent_launch = kwargs["before_agent_launch"]
        assert callable(before_agent_launch)
        before_agent_launch(project, epic_id)
        launch_reached = True
        return True

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        launch,
    )

    with pytest.raises(PlanFileWorkError, match="--no-push cannot launch") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=True,
            render=False,
        )

    assert launch_reached is False
    assert "--no-push" not in (excinfo.value.resume_command or "")
    archived = next(sidecar.glob("*/rollout.md"))
    linked = linked_bead_id(archived)
    with BeadProject(sidecar, beads_dirname="beads") as project:
        assert project.show(linked).is_ready_to_work is True
        assert len(project.get_epic_children(linked)) == 3

    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._publish_epic_graph_before_launch",
        lambda _store, *, no_push: True,
    )
    retried = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert launch_reached is True
    assert retried.resumed is True
    assert retried.epic_id == linked
    with BeadProject(sidecar, beads_dirname="beads") as project:
        assert len(project.list_issues()) == 4


def test_synchronous_graph_push_failure_preserves_state_and_stops_launch(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    source = project_dir / "push_failure.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    sidecar = tmp_path / "plans-sidecar"
    with BeadProject.init(sidecar, beads_dirname="beads"):
        pass
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=sidecar,
        repo_root=sidecar,
        remote_url="git@example.test:plans.git",
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
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
    )
    monkeypatch.setattr(
        "sase.bead.sync.commit_epic_graph_checkpoint",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        lambda _beads_dir, **_kwargs: SimpleNamespace(
            pushed=False,
            skipped_no_remote=False,
            error="git push failed: rejected",
        ),
    )
    launcher_reached = False

    def launch(project: BeadProject, epic_id: str, **kwargs: object) -> bool:
        nonlocal launcher_reached
        project.mark_ready_to_work(epic_id)
        before_agent_launch = kwargs["before_agent_launch"]
        assert callable(before_agent_launch)
        before_agent_launch(project, epic_id)
        launcher_reached = True
        return True

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        launch,
    )

    with pytest.raises(PlanFileWorkError, match="git push failed: rejected"):
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    assert launcher_reached is False
    archived = next(sidecar.glob("*/push_failure.md"))
    linked = linked_bead_id(archived)
    with BeadProject(sidecar, beads_dirname="beads") as project:
        assert project.show(linked).is_ready_to_work is True
        assert len(project.get_epic_children(linked)) == 3
