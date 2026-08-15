"""Generation-keyed worker behavior for flat Artifacts query sessions."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast
from collections.abc import Callable

import pytest
from textual.worker import Worker, WorkerState

from sase.ace.query_profile import compiled_profile_for_builtin_pane
from sase.ace.tui.widgets.artifacts import query_session as query_session_module
from sase.ace.tui.widgets.artifacts.query_session import ArtifactQuerySession
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    ArtifactQueryResult,
)


@dataclass(eq=False)
class _FakeWorker:
    task: Callable[[], ArtifactQueryResult]
    is_running: bool = True
    is_finished: bool = False
    result: ArtifactQueryResult | None = None
    cancelled: bool = False

    def run(self) -> None:
        self.result = self.task()
        self.is_running = False
        self.is_finished = True

    def cancel(self) -> None:
        self.cancelled = True
        self.is_running = False
        self.is_finished = True


class _FakeOwner:
    def __init__(self) -> None:
        self.workers: list[_FakeWorker] = []
        self.calls: list[dict[str, Any]] = []

    def run_worker(self, task: Callable[[], ArtifactQueryResult], **kwargs: Any) -> Any:
        worker = _FakeWorker(task)
        self.workers.append(worker)
        self.calls.append(kwargs)
        return worker


def _index(generation: int) -> ArtifactQueryIndex:
    profile = compiled_profile_for_builtin_pane("beads")
    assert profile is not None
    return ArtifactQueryIndex(
        pane_id="beads",
        generation=generation,
        profile=profile,
        row_ids=("row",),
        facets={},
        rust_handle=object(),
    )


def _finish(session: ArtifactQuerySession, worker: _FakeWorker) -> None:
    worker.run()
    assert session.handle_worker_state_changed(
        cast(
            Worker.StateChanged,
            SimpleNamespace(worker=worker, state=WorkerState.SUCCESS),
        )
    )


@pytest.fixture
def fake_evaluator(monkeypatch: pytest.MonkeyPatch) -> None:
    def evaluate(
        query: str,
        index: ArtifactQueryIndex,
        *,
        canonical_query: str,
    ) -> ArtifactQueryResult:
        return ArtifactQueryResult(
            cache_key=index.cache_key(canonical_query),
            matched_row_ids=(query,),
        )

    monkeypatch.setattr(
        query_session_module,
        "evaluate_artifact_query_many",
        evaluate,
    )


def test_cache_miss_runs_in_thread_then_hits_exact_cache(fake_evaluator: None) -> None:
    owner = _FakeOwner()
    received: list[ArtifactQueryResult] = []
    session = ArtifactQuerySession(
        owner,
        group="query-test",
        on_current_result=received.append,
    )
    index = _index(4)

    assert session.result("status:open", index) is None
    assert owner.calls == [
        {
            "thread": True,
            "group": "query-test",
            "exclusive": False,
            "exit_on_error": False,
        }
    ]
    _finish(session, owner.workers[0])

    cached = session.result("status:open", index)
    assert cached is received[0]
    assert cached.cache_key == index.cache_key("status:open")
    assert len(owner.workers) == 1


def test_only_latest_pending_query_launches_after_live_worker(
    fake_evaluator: None,
) -> None:
    owner = _FakeOwner()
    received: list[ArtifactQueryResult] = []
    session = ArtifactQuerySession(
        owner,
        group="query-test",
        on_current_result=received.append,
    )
    index = _index(7)

    session.result("status:open", index)
    session.result("status:closed", index)
    session.result("status:blocked", index)
    assert len(owner.workers) == 1

    _finish(session, owner.workers[0])
    assert received == []
    assert len(owner.workers) == 2

    _finish(session, owner.workers[1])
    assert received[0].matched_row_ids == ("status:blocked",)
    assert len(owner.workers) == 2


def test_stale_generation_cannot_publish_over_current_result(
    fake_evaluator: None,
) -> None:
    owner = _FakeOwner()
    received: list[ArtifactQueryResult] = []
    session = ArtifactQuerySession(
        owner,
        group="query-test",
        on_current_result=received.append,
    )

    session.result("status:open", _index(1))
    session.result("status:open", _index(2))
    _finish(session, owner.workers[0])
    assert received == []
    _finish(session, owner.workers[1])

    assert [result.cache_key.generation for result in received] == [2]


def test_returning_to_live_key_drops_obsolete_pending_query(
    fake_evaluator: None,
) -> None:
    owner = _FakeOwner()
    session = ArtifactQuerySession(
        owner,
        group="query-test",
        on_current_result=lambda _result: None,
    )
    index = _index(3)

    session.result("status:open", index)
    session.result("status:closed", index)
    session.result("status:open", index)
    _finish(session, owner.workers[0])

    assert len(owner.workers) == 1


def test_clear_cancels_workers_and_forgets_pending(fake_evaluator: None) -> None:
    owner = _FakeOwner()
    session = ArtifactQuerySession(
        owner,
        group="query-test",
        on_current_result=lambda _result: None,
    )
    index = _index(8)
    session.result("status:open", index)
    session.result("status:closed", index)

    session.clear()

    assert owner.workers[0].cancelled
    assert not session.handle_worker_state_changed(
        cast(
            Worker.StateChanged,
            SimpleNamespace(
                worker=owner.workers[0],
                state=WorkerState.CANCELLED,
            ),
        )
    )
    assert len(owner.workers) == 1
