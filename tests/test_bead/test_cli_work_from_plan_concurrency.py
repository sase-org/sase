"""Concurrency coverage for plan-file ``sase bead work`` launches."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import threading

import pytest

from sase.bead.cli_work_from_plan import work_from_plan_file
from sase.bead.project import BeadProject
from sase.sdd.frontmatter import parse_frontmatter
from sase.sdd.store import SddStore
from tests.test_bead.cli_work_from_plan_helpers import write_plan_update
from tests.test_bead.sync_test_helpers import configure_git_identity


EPIC_PLAN = """---
tier: epic
title: Plan-file rollout
goal: Exercise serialized plan-file launch.
phases:
  - id: core
    title: Build the core
    depends_on: []
    size: small
  - id: cli
    title: Add the CLI
    depends_on: [core]
    size: medium
  - id: verify
    title: Verify the result
    depends_on: [core, cli]
    size: large
---
# Plan

Execute the rollout.
"""

_CONCURRENCY_TIMEOUT_SECONDS = 10.0


def test_concurrent_plan_file_launches_serialize_through_terminal_push(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.bead.cli_work_from_plan as plan_module

    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )
    first_source = project_dir / "first.md"
    second_source = project_dir / "second.md"
    first_source.write_text(
        EPIC_PLAN.replace("Plan-file rollout", "First rollout"),
        encoding="utf-8",
    )
    second_source.write_text(
        EPIC_PLAN.replace("Plan-file rollout", "Second rollout"),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        plan_module,
        "_commit_plan_file",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        plan_module,
        "_write_and_commit_plan_file",
        write_plan_update,
    )

    events: list[tuple[str, str]] = []
    events_lock = threading.Lock()
    first_push_started = threading.Event()
    release_first_push = threading.Event()
    push_count = 0

    def launch(_project: BeadProject, epic_id: str, **_kwargs: object) -> bool:
        with events_lock:
            events.append(("launch", epic_id))
        return True

    def terminal_push(_store: SddStore, *, no_push: bool) -> None:
        nonlocal push_count
        assert no_push is False
        with events_lock:
            push_count += 1
            current_push = push_count
            events.append(("push-start", str(current_push)))
        if current_push == 1:
            first_push_started.set()
            assert release_first_push.wait(timeout=_CONCURRENCY_TIMEOUT_SECONDS)
        with events_lock:
            events.append(("push-end", str(current_push)))

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        launch,
    )
    monkeypatch.setattr(plan_module, "_push_store_after_launch", terminal_push)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                work_from_plan_file,
                str(source),
                dry_run=False,
                yes=True,
                no_push=False,
                render=False,
            )
            for source in (first_source, second_source)
        ]
        assert first_push_started.wait(timeout=_CONCURRENCY_TIMEOUT_SECONDS)
        with events_lock:
            assert sum(kind == "launch" for kind, _value in events) == 1
        release_first_push.set()
        results = [
            future.result(timeout=_CONCURRENCY_TIMEOUT_SECONDS) for future in futures
        ]

    epic_ids = {result.epic_id for result in results}
    assert None not in epic_ids
    assert len(epic_ids) == 2
    with events_lock:
        first_push_end = events.index(("push-end", "1"))
        second_launch = [
            index for index, (kind, _value) in enumerate(events) if kind == "launch"
        ][1]
    assert first_push_end < second_launch

    with BeadProject(project_dir) as project:
        for result in results:
            assert result.epic_id is not None
            phases = project.get_epic_children(result.epic_id)
            assert tuple(phase.id for phase in phases) == result.phase_bead_ids
            assert [len(phase.dependencies) for phase in phases] == [0, 1, 2]
            frontmatter, _body, _had_frontmatter = parse_frontmatter(
                result.archived_plan_path.read_text(encoding="utf-8")
            )
            assert frontmatter["bead_id"] == result.epic_id


def test_plan_link_write_and_commit_exclude_recovery_writer(
    project_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.cli_common import _BeadsLocation
    from sase.sdd._git_contention import store_git_write_lock
    from sase.sdd.files import commit_sdd_store_files as real_commit_sdd_store_files

    monkeypatch.setattr(
        "sase.file_references.format_with_prettier",
        lambda content: content,
    )
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

    source = project_dir / "race.md"
    source.write_text(EPIC_PLAN, encoding="utf-8")
    link_ready_to_commit = threading.Event()
    finish_link_commit = threading.Event()
    competitor_entered = threading.Event()
    commit_messages: list[str] = []
    launched: list[str] = []

    def pause_link_commit(
        commit_store: SddStore,
        message: str,
        *,
        paths: list[Path],
        push_after_commit: bool,
        already_locked: bool = False,
    ) -> bool:
        commit_messages.append(message)
        if message.startswith("Link approved epic plan"):
            assert already_locked is True
            frontmatter, _body, _had_frontmatter = parse_frontmatter(
                paths[0].read_text(encoding="utf-8")
            )
            assert frontmatter["bead_id"]
            link_ready_to_commit.set()
            assert finish_link_commit.wait(timeout=_CONCURRENCY_TIMEOUT_SECONDS)
        assert already_locked is not message.startswith("Archive approved plan")
        return real_commit_sdd_store_files(
            commit_store,
            message,
            paths=paths,
            push_after_commit=push_after_commit,
            already_locked=already_locked,
        )

    monkeypatch.setattr(
        "sase.sdd.files.commit_sdd_store_files",
        pause_link_commit,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_epic_bead_work",
        lambda _project, epic_id, **_kwargs: not launched.append(epic_id),
    )

    def compete_for_store() -> bool:
        with store_git_write_lock(
            sidecar,
            timeout=2.0,
            op="test.recovery_writer",
            mutates_worktree=True,
        ) as acquired:
            if acquired:
                competitor_entered.set()
            return acquired

    with ThreadPoolExecutor(max_workers=2) as executor:
        launch_future = executor.submit(
            work_from_plan_file,
            str(source),
            dry_run=False,
            yes=True,
            no_push=False,
            render=False,
        )
        if not link_ready_to_commit.wait(timeout=_CONCURRENCY_TIMEOUT_SECONDS):
            finish_link_commit.set()
            exception = launch_future.exception(timeout=_CONCURRENCY_TIMEOUT_SECONDS)
            pytest.fail(f"plan launch did not reach its link commit: {exception}")
        competitor_future = executor.submit(compete_for_store)
        assert competitor_entered.wait(timeout=0.2) is False
        finish_link_commit.set()
        result = launch_future.result(timeout=_CONCURRENCY_TIMEOUT_SECONDS)
        assert competitor_future.result(timeout=_CONCURRENCY_TIMEOUT_SECONDS) is True

    assert competitor_entered.is_set()
    assert launched == [result.epic_id]
    assert not any(
        message.startswith("Restore approved epic plan") for message in commit_messages
    )
    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        result.archived_plan_path.read_text(encoding="utf-8")
    )
    assert frontmatter["bead_id"] == result.epic_id
