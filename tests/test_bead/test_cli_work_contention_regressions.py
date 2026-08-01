"""Regression coverage for contended ``sase bead work`` launch paths."""

from __future__ import annotations

import fcntl
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time
from typing import Any

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.work import VCSLaunchContext

from .cli_work_helpers import FakeLaunchResult, make_args, seed_diamond, seed_task

pytestmark = pytest.mark.usefixtures("fake_cli_work_xprompts")

_CONCURRENT_MUTATION_WORKERS = 3
_CONCURRENT_MUTATION_ITERATIONS = 4
_MUTATION_LOCK_HOLD_SECONDS = 2.6
_PROCESS_TIMEOUT_SECONDS = 12.0


def _append_notes_worker(
    project_dir: str,
    bead_ids: list[str],
    worker_index: int,
    iterations: int,
    ready_queue: Any,
    result_queue: Any,
) -> None:
    """Append notes in a child process once the parent-held lock is released."""
    try:
        with BeadProject(Path(project_dir)) as project:
            ready_queue.put(worker_index)
            for iteration in range(iterations):
                bead_id = bead_ids[(worker_index + iteration) % len(bead_ids)]
                project.append_note(
                    bead_id,
                    f"contention worker {worker_index} iteration {iteration}",
                )
    except BaseException as exc:
        result_queue.put(
            {
                "ok": False,
                "worker": worker_index,
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    else:
        result_queue.put({"ok": True, "worker": worker_index, "error": ""})


def test_concurrent_bead_mutations_wait_past_the_old_lock_timeout(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several writers should wait for the env-configured mutation deadline."""
    monkeypatch.setenv("SASE_BEAD_MUTATION_LOCK_TIMEOUT", "5")
    with BeadProject(project_dir) as project:
        bead_ids = [
            project.create(f"Seeded task {index}", IssueType.TASK).id
            for index in range(36)
        ]

    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    result_queue = context.Queue()
    lock_file = (project_dir / "sdd/beads/beads.db").open("a+", encoding="utf-8")
    processes: list[multiprocessing.Process] = []
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    try:
        for worker_index in range(_CONCURRENT_MUTATION_WORKERS):
            process = context.Process(
                target=_append_notes_worker,
                args=(
                    str(project_dir),
                    bead_ids,
                    worker_index,
                    _CONCURRENT_MUTATION_ITERATIONS,
                    ready_queue,
                    result_queue,
                ),
            )
            process.start()
            processes.append(process)

        ready_workers = {
            ready_queue.get(timeout=_PROCESS_TIMEOUT_SECONDS)
            for _ in range(_CONCURRENT_MUTATION_WORKERS)
        }
        assert ready_workers == set(range(_CONCURRENT_MUTATION_WORKERS))

        # The old hardcoded Rust timeout was 2s. Holding the lock longer keeps
        # this test tied to the new env-configured wait instead of incidental
        # fast local mutations.
        time.sleep(_MUTATION_LOCK_HOLD_SECONDS)
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

    try:
        results = [
            result_queue.get(timeout=_PROCESS_TIMEOUT_SECONDS)
            for _ in range(_CONCURRENT_MUTATION_WORKERS)
        ]
        for process in processes:
            process.join(timeout=_PROCESS_TIMEOUT_SECONDS)
            if process.is_alive():
                process.terminate()
                pytest.fail(f"mutation worker {process.pid} did not finish")
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()

    failures = [result for result in results if not result["ok"]]
    assert failures == []

    with BeadProject(project_dir) as project:
        notes = "\n".join(project.show(bead_id).notes for bead_id in bead_ids)
    assert "contention worker 0 iteration 0" in notes
    assert "lock_timeout" not in notes.lower()


@pytest.fixture
def task_vcs_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_work_task.resolve_task_vcs_launch_context",
        lambda: VCSLaunchContext(vcs_workflow="git", project_name="sase"),
    )


def test_task_launch_waits_for_overlapping_epic_launch_and_claims_task(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    task_vcs_context: None,
) -> None:
    epic_id, phase_ids = seed_diamond(project_dir)
    task_id = seed_task(project_dir)
    epic_launch_entered = threading.Event()
    release_epic_launch = threading.Event()
    task_launch_entered = threading.Event()
    events: list[str] = []
    events_lock = threading.Lock()

    def record(event: str) -> None:
        with events_lock:
            events.append(event)

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.resolve_vcs_launch_context",
        lambda: VCSLaunchContext(vcs_workflow="git", project_name="sase"),
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_handler.checkpoint_epic_work_launch",
        lambda *_args, **_kwargs: record("epic-checkpoint") or True,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.checkpoint_task_work_launch",
        lambda *_args, **_kwargs: record("task-checkpoint") or True,
    )

    def launch_epic_agents(*_args: object, **_kwargs: object) -> list[FakeLaunchResult]:
        record("epic-launch-enter")
        epic_launch_entered.set()
        assert release_epic_launch.wait(timeout=_PROCESS_TIMEOUT_SECONDS)
        record("epic-launch-exit")
        return [FakeLaunchResult()]

    def launch_task_agent(*_args: object, **_kwargs: object) -> list[FakeLaunchResult]:
        record("task-launch-enter")
        task_launch_entered.set()
        return [FakeLaunchResult()]

    monkeypatch.setattr(
        "sase.bead.cli_work_handler.launch_bead_work_agents",
        launch_epic_agents,
    )
    monkeypatch.setattr(
        "sase.bead.cli_work_task.launch_bead_work_agents",
        launch_task_agent,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        epic_result = executor.submit(
            bead_cli.handle_bead_work, make_args(epic_id, yes=True)
        )
        assert epic_launch_entered.wait(timeout=_PROCESS_TIMEOUT_SECONDS)

        task_result = executor.submit(
            bead_cli.handle_bead_work, make_args(task_id, yes=True)
        )
        assert task_launch_entered.wait(timeout=0.2) is False
        with events_lock:
            assert "task-checkpoint" not in events

        release_epic_launch.set()
        epic_result.result(timeout=_PROCESS_TIMEOUT_SECONDS)
        task_result.result(timeout=_PROCESS_TIMEOUT_SECONDS)

    with events_lock:
        assert events.index("epic-launch-exit") < events.index("task-checkpoint")
        assert events.index("task-checkpoint") < events.index("task-launch-enter")

    with BeadProject(project_dir) as project:
        task = project.show(task_id)
        epic = project.show(epic_id)
        phases = [project.show(phase_id) for phase_id in phase_ids]

    assert (task.status, task.assignee) == (Status.IN_PROGRESS, task_id)
    assert (epic.status, epic.assignee) == (Status.IN_PROGRESS, f"{epic_id}.land")
    assert all(
        (phase.status, phase.assignee) == (Status.IN_PROGRESS, phase.id)
        for phase in phases
    )
    assert Status.CLAIMED not in {task.status, epic.status, *(p.status for p in phases)}
