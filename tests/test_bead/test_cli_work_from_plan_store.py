"""Store, archive, and push coverage for plan-file ``sase bead work``."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.bead.cli_work_from_plan import PlanFileWorkError, work_from_plan_file
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore
from tests.test_bead.cli_work_helpers import FakeLaunchResult
from tests.test_bead.cli_work_from_plan_helpers import EPIC_PLAN, write_plan_update
from tests.test_bead.sync_test_helpers import configure_git_identity


@pytest.fixture(autouse=True)
def _stable_plan_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )


def test_plan_file_mode_uses_sidecar_store(
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
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **_kwargs: True,
    )

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert result.archived_plan_path.is_relative_to(sidecar)
    with BeadProject(sidecar, beads_dirname="beads") as project:
        assert project.show(result.epic_id or "").design == (
            f"plans:{result.archived_plan_path.relative_to(sidecar).as_posix()}"
        )


def test_plan_file_publication_uses_split_beads_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_from_plan_store import publish_epic_graph_before_launch

    plans = tmp_path / "sase" / "repos" / "plans"
    beads = tmp_path / "sase" / "repos" / "beads"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.test:project--plans.git",
        beads_dir=beads,
    )
    pushed: list[Path] = []

    def fake_push(path: Path) -> SimpleNamespace:
        pushed.append(path)
        return SimpleNamespace(pushed=True, error=None)

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_push)

    assert publish_epic_graph_before_launch(store, no_push=False)
    assert pushed == [beads]


def test_plan_update_lock_failure_leaves_original_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_work_from_plan_store import write_and_commit_plan_file
    from sase.sdd._repository_transaction import SddRepositoryHealthError

    repo = tmp_path / "plans"
    repo.mkdir()
    plan = repo / "approved.md"
    original = EPIC_PLAN.encode()
    plan.write_bytes(original)
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=repo,
        repo_root=repo,
    )

    @contextmanager
    def unavailable_lock(*_args: object, **_kwargs: object) -> Iterator[bool]:
        yield False

    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        unavailable_lock,
    )
    monkeypatch.setattr(
        "sase.sdd.files.commit_sdd_store_files",
        lambda *_args, **_kwargs: pytest.fail("commit ran without the store lock"),
    )

    with pytest.raises(SddRepositoryHealthError, match="plan was not changed"):
        write_and_commit_plan_file(
            store,
            workspace_dir=repo,
            plan_path=plan,
            content=EPIC_PLAN.replace("tier: epic", "tier: epic\nbead_id: sase-1"),
            message="Link approved plan",
        )

    assert plan.read_bytes() == original


def test_plan_file_refuses_poisoned_sidecar_before_archive_or_bead_open(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation

    source = project_dir / "approved.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    sidecar = tmp_path / "plans-sidecar"
    sidecar.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=sidecar, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=sidecar,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=sidecar, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "seed"],
        cwd=sidecar,
        check=True,
        capture_output=True,
    )
    (sidecar / "beads").mkdir()
    (sidecar / ".git/rebase-merge").mkdir()
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=sidecar,
        repo_root=sidecar,
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
        "sase.sdd.plan_archive.archive_plan_file",
        lambda *_args, **_kwargs: pytest.fail("poisoned store was archived into"),
    )

    with pytest.raises(PlanFileWorkError, match="not safe to write") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    assert excinfo.value.resume_command == f"sase bead work {source} --yes"
    assert not (sidecar / "plans").exists()


def test_neutral_gate_plan_archives_under_original_stem(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = project_dir / "interaction_requests" / "epic_plan" / "request"
    bundle.mkdir(parents=True)
    source = bundle / "plan.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    original = project_dir / "proposals" / "canonical_rollout.md"
    (bundle / "request.json").write_text(
        json.dumps(
            {
                "kind": "epic_plan",
                "payload": {
                    "original_plan_file": str(original),
                    "plan_resource": "plan.md",
                },
            }
        ),
        encoding="utf-8",
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
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, _epic_id, **_kwargs: True,
    )

    result = work_from_plan_file(
        str(source),
        dry_run=False,
        yes=True,
        no_push=False,
        render=False,
    )

    assert result.archived_plan_path.name == "canonical_rollout.md"


def test_plan_file_rejects_preserved_archive_identity_mismatch(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = project_dir / "incoming" / "rollout.md"
    source.parent.mkdir()
    source.write_text(EPIC_PLAN, encoding="utf-8")
    archived = project_dir / "sdd" / "plans" / "202607" / "rollout.md"
    archived.parent.mkdir(parents=True)
    archived.write_text(
        "---\ntier: tale\ntitle: Different plan\n---\n# Plan\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("sase.sdd.files.get_yyyymm", lambda: "202607")

    with pytest.raises(PlanFileWorkError, match="archive collision") as excinfo:
        work_from_plan_file(
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )

    message = str(excinfo.value)
    assert str(source) in message
    assert str(archived) in message
    assert excinfo.value.resume_command == f"sase bead work {archived} --yes"


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
        lambda _store, *, no_push: events.append(("reconcile", no_push)),
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
    linked = _linked_bead_id(archived)
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


def _linked_bead_id(plan_path: Path) -> str:
    from sase.sdd.frontmatter import parse_frontmatter

    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        plan_path.read_text(encoding="utf-8")
    )
    return str(frontmatter["bead_id"])


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
        lambda _beads_dir: SimpleNamespace(
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
    linked = _linked_bead_id(archived)
    with BeadProject(sidecar, beads_dirname="beads") as project:
        assert project.show(linked).is_ready_to_work is True
        assert len(project.get_epic_children(linked)) == 3


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
        epic_id = _linked_bead_id(archived)
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
            assert epic.design.startswith("plans:")
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
    assert all("mark bead work launched" not in line for line in commit_subjects)
