"""Launch-flow publication coverage for plan-file ``sase bead work``."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.sdd.store import SddStore
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN, write_plan_update
from tests.test_bead.cli_work_from_plan_publication_helpers import (
    linked_bead_id,
    stable_plan_formatting,
)
from tests.test_bead.cli_work_helpers import FakeLaunchResult
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


def test_graph_publication_maps_conflict_status_to_typed_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An aborted publication raises typed; other failures stay RuntimeError."""
    from sase.bead.cli_work_from_plan_store import (
        publish_epic_graph_before_launch_result,
    )
    from sase.bead.cli_work_handler_errors import EpicGraphPublicationConflictError
    from sase.sdd._repository_types import SddIntegrationStatus

    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=tmp_path,
        repo_root=tmp_path,
        remote_url="git@example.test:beads.git",
    )
    log_path = tmp_path / "sync.log"
    cause = (
        "bead-ID collision with concurrently published history "
        "could not be merged: duplicate issue_created event for sase-1"
    )

    def conflict_outcome(_beads_dir: Path, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            pushed=False,
            skipped_no_remote=False,
            error=cause,
            log_path=log_path,
            bead_relocations=(),
            push_attempts=1,
            integration_status=SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS.value,
        )

    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        conflict_outcome,
    )
    with pytest.raises(EpicGraphPublicationConflictError) as excinfo:
        publish_epic_graph_before_launch_result(store, no_push=False)
    assert excinfo.value.publication_conflict is True
    assert excinfo.value.semantic_cause == cause
    assert excinfo.value.log_path == log_path
    assert "could not be merged" in str(excinfo.value)
    assert f"managed sync log: {log_path}" in str(excinfo.value)

    def transient_outcome(_beads_dir: Path, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            pushed=False,
            skipped_no_remote=False,
            error="git push rejected",
            log_path=log_path,
            bead_relocations=(),
            push_attempts=1,
            integration_status=None,
        )

    monkeypatch.setattr(
        "sase.bead.sync.push_bead_work_launch",
        transient_outcome,
    )
    with pytest.raises(RuntimeError, match="git push rejected") as plain:
        publish_epic_graph_before_launch_result(store, no_push=False)
    assert not isinstance(plain.value, EpicGraphPublicationConflictError)


def test_publication_conflict_message_is_cause_first_without_git_noise() -> None:
    """The unmergeable-conflict summary leads with the cause, not git noise."""
    from sase.sdd._repository_integration_repair import _cause_first_integration_error

    error = _cause_first_integration_error(
        "git rebase failed: Rebasing (1/1)\n"
        "error: could not apply 35f5186 chore(beads): checkpoint approved epic graph\n"
        "hint: Resolve all conflicts manually, mark them as resolved with\n"
        'hint: "git add/rm <conflicted_files>"\n'
        "Could not apply 35f5186 chore(beads): checkpoint approved epic graph",
        "semantic conflict resolution failed: validation: "
        "duplicate issue_created event for bob-cli-ra",
    )
    assert error.startswith(
        "bead-ID collision with concurrently published history could not be merged:"
    )
    assert "duplicate issue_created event for bob-cli-ra" in error
    assert "hint:" not in error
    assert "Rebasing (1/1)" not in error


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_replay_remote(tmp_path: Path, name: str) -> Path:
    remote = tmp_path / f"{name}.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    return remote


def _seed_split_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_dir: Path,
) -> tuple[SddStore, object, Path, Path]:
    """Build split plans/beads sidecars with real remotes for one plan launch."""
    from sase.bead.cli_common import _BeadsLocation

    plans_remote = _init_replay_remote(tmp_path, "plans")
    beads_remote = _init_replay_remote(tmp_path, "beads")
    plans = tmp_path / "plans-sidecar"
    beads = tmp_path / "beads-sidecar"
    for clone, remote in ((plans, plans_remote), (beads, beads_remote)):
        _git(tmp_path, "clone", str(remote), str(clone))
        configure_git_identity(clone)
    (plans / "README.md").write_text("plans\n", encoding="utf-8")
    _git(plans, "add", "README.md")
    _git(plans, "commit", "-m", "Initialize plans sidecar")
    _git(plans, "push", "-u", "origin", "main")
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
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_from_plan._write_and_commit_plan_file",
        write_plan_update,
    )
    monkeypatch.setattr(
        "sase.bead.sync.refresh_bead_store",
        lambda _beads_dir, *, lock_timeout=None: None,
    )
    source = project_dir / "rollout.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    source.with_name(f"{source.stem}.plan-decisions.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "definitions": [{"id": "grouping", "prompt": "Choose grouping"}],
            }
        ),
        encoding="utf-8",
    )
    return store, location, plans, beads


@pytest.mark.usefixtures("fake_cli_work_macros")
def test_publication_conflict_replay_discards_graph_and_remints(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unmergeable zero-spawn publication is discarded and re-minted.

    A concurrent clone publishes the ID this launch minted from its stale
    counter; the first publication aborts, the replay preserves the graph
    under a recovery ref, resets to upstream, and the retry mints fresh.
    """
    import sase.bead._cli_work_from_plan_transaction as launch_module
    import sase.sdd._semantic_conflict_resolver as resolver_module

    _store, _location, plans, beads = _seed_split_sidecars(
        tmp_path, monkeypatch, project_dir
    )

    concurrent = tmp_path / "concurrent"
    _git(tmp_path, "clone", str(tmp_path / "beads.git"), str(concurrent))
    configure_git_identity(concurrent)
    from sase.bead.model import IssueType

    with BeadProject(concurrent, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        concurrent_epic = project.create(
            title="Concurrent epic", issue_type=IssueType.PLAN
        )
    discarded_id = concurrent_epic.id
    _git(concurrent, "add", "-A")
    _git(concurrent, "commit", "-m", "Concurrent epic publication")
    _git(concurrent, "push", "-u", "origin", "main")

    real_resolve = resolver_module.resolve_semantic_conflicts
    resolve_calls = 0

    def fail_first_resolve(cwd: str | Path = ".", **kwargs: Any) -> Any:
        nonlocal resolve_calls
        resolve_calls += 1
        if resolve_calls == 1:
            return resolver_module._SemanticConflictResolution(
                False,
                f"duplicate issue_created event for {discarded_id}",
            )
        return real_resolve(cwd, **kwargs)

    monkeypatch.setattr(
        resolver_module,
        "resolve_semantic_conflicts",
        fail_first_resolve,
    )

    launches: list[object] = []

    def fake_launch(*_args: object, **_kwargs: object) -> list[FakeLaunchResult]:
        launches.append(True)
        return [FakeLaunchResult()]

    monkeypatch.setattr(
        "sase.bead.cli_work_handler_publish.launch_bead_work_agents",
        fake_launch,
    )

    replayed: list[tuple[str, str]] = []
    real_replay = launch_module.replay_publication_conflict

    def spy_replay(**kwargs: Any) -> str:
        ref = real_replay(**kwargs)
        head = _git(beads, "rev-parse", "HEAD").stdout.strip()
        upstream = _git(beads, "rev-parse", "@{upstream}").stdout.strip()
        replayed.append((head, upstream))
        return ref

    monkeypatch.setattr(
        launch_module,
        "replay_publication_conflict",
        spy_replay,
    )

    result = work_from_plan_file(
        str(project_dir / "rollout.md"),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    # The retry minted a fresh ID; the plan link names the launched epic.
    assert result.epic_id != discarded_id
    archived = next(plans.glob("202607/rollout.md"))
    assert linked_bead_id(archived) == result.epic_id
    # Only the successful retry spawned agents.
    assert len(launches) == 1
    # The replay ran once and left the store exactly at upstream.
    assert len(replayed) == 1
    assert replayed[0][0] == replayed[0][1]
    assert resolve_calls >= 1
    # The discarded graph survives under a recovery ref naming the old ID.
    ref_lines = _git(beads, "for-each-ref", "refs/sase/recovery/").stdout.splitlines()
    assert len(ref_lines) == 1
    recovery_ref = ref_lines[0].split()[-1]
    assert discarded_id in recovery_ref
    tracked = _git(
        beads, "ls-tree", "-r", "--name-only", recovery_ref
    ).stdout.splitlines()
    assert any(name.endswith(f"/{discarded_id}.jsonl") for name in tracked)
    # The live history holds the fresh checkpoint, not the discarded one.
    subjects = _git(beads, "log", "--format=%s").stdout.splitlines()
    assert f"chore(beads): checkpoint approved epic graph {result.epic_id}" in subjects
    assert discarded_id not in " ".join(subjects)


def test_publication_conflict_replay_refuses_foreign_unpublished_commit(
    tmp_path: Path,
) -> None:
    """A foreign commit in the unpublished range refuses the reset entirely."""
    from sase.bead._cli_work_from_plan_replay import replay_publication_conflict
    from sase.bead.epic_from_plan import EpicFromPlanError

    remote = _init_replay_remote(tmp_path, "replay-beads")
    clone = tmp_path / "replay-clone"
    _git(tmp_path, "clone", str(remote), str(clone))
    configure_git_identity(clone)
    (clone / "base.txt").write_text("base\n", encoding="utf-8")
    _git(clone, "add", "base.txt")
    _git(clone, "commit", "-m", "base")
    _git(clone, "push", "-u", "origin", "main")
    launch_base = _git(clone, "rev-parse", "HEAD").stdout.strip()
    (clone / "foreign.txt").write_text("another writer\n", encoding="utf-8")
    _git(clone, "add", "foreign.txt")
    _git(clone, "commit", "-m", "foreign unpublished commit")

    with pytest.raises(EpicFromPlanError, match="NOT discarded") as excinfo:
        replay_publication_conflict(
            beads_dir=clone,
            launch_base=launch_base,
            epic_id="beads-9",
            checkpoint_sha="0" * 40,
            attempt_tip_sha=None,
            cause="epic graph publication conflicted and could not be merged",
            archived_path=tmp_path / "rollout.md",
        )

    message = str(excinfo.value)
    assert "foreign unpublished commit" not in message
    assert "is not part of this attempt's unpublished graph" in message
    assert "For broader diagnostics, run `sase doctor -v`." in message
    # Nothing was reset: the foreign commit is still HEAD, no recovery ref.
    assert _git(clone, "rev-parse", "HEAD").stdout.strip() != launch_base
    assert _git(clone, "for-each-ref", "refs/sase/recovery/").stdout.strip() == ""
