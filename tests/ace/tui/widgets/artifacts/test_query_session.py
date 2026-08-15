"""Unit coverage for asynchronous Artifacts query sessions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from textual.worker import Worker
from textual.worker import WorkerState

from sase.ace.query_profile import compile_query_profile
from sase.ace.query_profile.profiles import beads_query_schema
from sase.ace.tui.widgets.artifacts.query_session import ArtifactQuerySession
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    compile_artifact_query_index,
)


class _FakeWorker:
    def __init__(self, task: Any) -> None:
        self.task = task
        self.result: Any = None
        self.is_finished = False
        self.cancelled = False

    @property
    def is_running(self) -> bool:
        return not self.is_finished

    def cancel(self) -> None:
        self.cancelled = True
        self.is_finished = True

    def finish(self) -> None:
        self.result = self.task()
        self.is_finished = True


class _FakeOwner:
    def __init__(self) -> None:
        self.workers: list[_FakeWorker] = []

    def run_worker(self, task: Any, **_kwargs: Any) -> _FakeWorker:
        worker = _FakeWorker(task)
        self.workers.append(worker)
        return worker


def _index(generation: int = 1) -> ArtifactQueryIndex:
    profile = compile_query_profile(beads_query_schema())
    return compile_artifact_query_index(
        pane_id="beads",
        generation=generation,
        profile=profile,
        entries=(
            {"stable_id": "a", "fields": {"status": "open", "title": "alpha"}},
            {"stable_id": "b", "fields": {"status": "closed", "title": "beta"}},
        ),
    )


def test_query_session_coalesces_caches_and_rejects_stale_results() -> None:
    owner = _FakeOwner()
    applied: list[tuple[str, ...]] = []
    session = ArtifactQuerySession(
        owner,
        group="test",
        on_current_result=lambda result: applied.append(result.matched_row_ids),
    )
    index = _index()

    assert session.result("status:open", index) is None
    assert session.result("status:open", index) is None
    assert len(owner.workers) == 1

    stale_worker = owner.workers[0]
    assert session.result("status:closed", index) is None
    assert len(owner.workers) == 1

    stale_worker.finish()
    assert session.handle_worker_state_changed(
        cast(
            Worker.StateChanged,
            SimpleNamespace(worker=stale_worker, state=WorkerState.SUCCESS),
        )
    )
    assert applied == []
    assert len(owner.workers) == 2

    current_worker = owner.workers[1]
    current_worker.finish()
    assert session.handle_worker_state_changed(
        cast(
            Worker.StateChanged,
            SimpleNamespace(worker=current_worker, state=WorkerState.SUCCESS),
        )
    )
    assert applied == [("b",)]

    cached = session.result("status:closed", index)
    assert cached is not None
    assert cached.matched_row_ids == ("b",)
    assert len(owner.workers) == 2
