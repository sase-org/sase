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
_OLD_HARDCODED_LOCK_TIMEOUT_SECONDS = 2.0
_MUTATION_LOCK_HOLD_SECONDS = 2.6
# Deliberately far above any wall clock this test can plausibly need. The
# behavior under test is "a blocked writer keeps waiting and then succeeds",
# so the configured deadline must never double as the test's time budget --
# that is what made this test fail only under saturated full-suite runs.
_MUTATION_LOCK_TIMEOUT_SECONDS = 600
# A deadline short enough that a writer blocked by the parent-held lock must
# give up, which is how we prove the env var is read at all: the built-in
# default waits indefinitely.
_SHORT_MUTATION_LOCK_TIMEOUT_SECONDS = 1
# Backstop for hung children only; never part of the asserted behavior.
_PROCESS_TIMEOUT_SECONDS = 120.0


def _append_note_worker(
    project_dir: str,
    bead_id: str,
    worker_index: int,
    ready_queue: Any,
    result_queue: Any,
) -> None:
    """Append one note in a child process, timing the contended mutation.

    ``started`` is stamped before the readiness handshake so the parent's hold
    is guaranteed to be fully contained in the reported ``elapsed``; that keeps
    the wait assertion exact instead of racing the child's scheduling.
    """
    result: dict[str, Any] = {"ok": True, "worker": worker_index, "error": ""}
    started = time.monotonic()
    try:
        with BeadProject(Path(project_dir)) as project:
            ready_queue.put(worker_index)
            project.append_note(bead_id, f"contention worker {worker_index}")
    except BaseException as exc:
        result.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    result["elapsed"] = time.monotonic() - started
    result_queue.put(result)


def _seed_contention_beads(project_dir: Path, count: int) -> list[str]:
    with BeadProject(project_dir) as project:
        return [
            project.create(
                f"Seeded task {index}", IssueType.TASK, task_type="bug", size="small"
            ).id
            for index in range(count)
        ]


def _start_blocked_writers(
    context: Any,
    project_dir: Path,
    bead_ids: list[str],
    ready_queue: Any,
    result_queue: Any,
    processes: list[multiprocessing.Process],
) -> None:
    """Spawn one writer per seeded bead and wait for every readiness signal.

    Started processes are appended to ``processes`` as they launch so the
    caller's cleanup still reaches them if the handshake below fails.
    """
    for worker_index, bead_id in enumerate(bead_ids):
        process = context.Process(
            target=_append_note_worker,
            args=(str(project_dir), bead_id, worker_index, ready_queue, result_queue),
        )
        process.start()
        processes.append(process)

    ready_workers = {
        ready_queue.get(timeout=_PROCESS_TIMEOUT_SECONDS) for _ in processes
    }
    assert ready_workers == set(range(len(processes)))


def _join_writers(processes: list[multiprocessing.Process]) -> None:
    try:
        for process in processes:
            process.join(timeout=_PROCESS_TIMEOUT_SECONDS)
            if process.is_alive():
                pytest.fail(f"mutation worker {process.pid} did not finish")
            assert process.exitcode == 0
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()


def test_concurrent_bead_mutations_wait_past_the_old_lock_timeout(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Several writers should block past the old 2s deadline, then succeed."""
    monkeypatch.setenv(
        "SASE_BEAD_MUTATION_LOCK_TIMEOUT", str(_MUTATION_LOCK_TIMEOUT_SECONDS)
    )
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repo_root))
    bead_ids = _seed_contention_beads(project_dir, _CONCURRENT_MUTATION_WORKERS)

    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    result_queue = context.Queue()
    lock_file = (project_dir / "sdd/beads/beads.db").open("a+", encoding="utf-8")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    processes: list[multiprocessing.Process] = []
    try:
        _start_blocked_writers(
            context, project_dir, bead_ids, ready_queue, result_queue, processes
        )
        # The old hardcoded Rust timeout was 2s. Holding the lock longer keeps
        # this test tied to the configured wait instead of incidental fast
        # local mutations.
        time.sleep(_MUTATION_LOCK_HOLD_SECONDS)
        # No writer can have finished while we still hold the exclusive lock;
        # asserting it here is what proves the waiting actually happened.
        assert result_queue.empty(), "a writer settled while the lock was held"
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

    results = [result_queue.get(timeout=_PROCESS_TIMEOUT_SECONDS) for _ in processes]
    _join_writers(processes)

    assert [result for result in results if not result["ok"]] == []
    assert all(
        result["elapsed"] > _OLD_HARDCODED_LOCK_TIMEOUT_SECONDS for result in results
    ), results

    with BeadProject(project_dir) as project:
        notes = "\n".join(project.show(bead_id).notes_text for bead_id in bead_ids)
    for worker_index in range(_CONCURRENT_MUTATION_WORKERS):
        assert f"contention worker {worker_index}" in notes
    assert "lock_timeout" not in notes.lower()


def test_bead_mutation_lock_wait_honors_a_short_configured_deadline(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured deadline bounds the wait; the default would never expire."""
    monkeypatch.setenv(
        "SASE_BEAD_MUTATION_LOCK_TIMEOUT",
        str(_SHORT_MUTATION_LOCK_TIMEOUT_SECONDS),
    )
    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(repo_root))
    bead_ids = _seed_contention_beads(project_dir, 1)

    context = multiprocessing.get_context("spawn")
    ready_queue = context.Queue()
    result_queue = context.Queue()
    lock_file = (project_dir / "sdd/beads/beads.db").open("a+", encoding="utf-8")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    processes: list[multiprocessing.Process] = []
    try:
        _start_blocked_writers(
            context, project_dir, bead_ids, ready_queue, result_queue, processes
        )
        # Hold the lock for the whole wait: the writer must give up on its own.
        result = result_queue.get(timeout=_PROCESS_TIMEOUT_SECONDS)
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

    _join_writers(processes)

    assert result["ok"] is False
    assert "lock_timeout" in result["error"]
    assert result["elapsed"] >= _SHORT_MUTATION_LOCK_TIMEOUT_SECONDS


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
