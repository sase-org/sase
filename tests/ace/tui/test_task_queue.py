"""Tests for sase.ace.tui.task_queue."""

from __future__ import annotations

import io
import sys
import threading
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.task_actions import (
    TaskActionsMixin,
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.ace.tui.task_queue import TaskInfo, TaskQueue, capture_output


# ---------------------------------------------------------------------------
# TaskQueue.submit
# ---------------------------------------------------------------------------


class TestTaskQueueSubmit:
    def test_submit_creates_running_task(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")

        assert info.status == "running"
        assert info.task_type == "sync"
        assert info.cl_name == "CL-1"
        assert info.project_file == "/proj.sase"
        assert info.finished_at is None

    def test_submit_generates_unique_ids(self) -> None:
        q = TaskQueue()
        a = q.submit("sync", "CL-1", "/proj.sase")
        b = q.submit("mail", "CL-2", "/proj.sase")
        assert a.task_id != b.task_id

    def test_submit_accepts_display_name_and_dedup_key(self) -> None:
        q = TaskQueue()
        info = q.submit(
            "launch",
            "foo",
            "/proj.sase",
            display_name="launch fanout foo",
            dedup_key="launch:foo:1",
        )

        assert info.display_name == "launch fanout foo"
        assert info.label == "launch fanout foo"
        assert info.dedup_key == "launch:foo:1"


# ---------------------------------------------------------------------------
# TaskQueue.complete
# ---------------------------------------------------------------------------


class TestTaskQueueComplete:
    def test_complete_success(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")
        q.complete(info.task_id, success=True, message="ok", output="log")

        assert info.status == "success"
        assert info.message == "ok"
        assert info.output == "log"
        assert info.error is None
        assert info.finished_at is not None

    def test_complete_error(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")
        q.complete(
            info.task_id,
            success=False,
            message="boom",
            output="log",
            error="boom",
        )

        assert info.status == "error"
        assert info.error == "boom"
        assert info.finished_at is not None

    def test_complete_unknown_id_is_noop(self) -> None:
        q = TaskQueue()
        q.complete("nonexistent", success=True, message="x", output="")


# ---------------------------------------------------------------------------
# TaskQueue.get_running_for_cl  (deduplication)
# ---------------------------------------------------------------------------


class TestTaskQueueDedup:
    def test_returns_running_task(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")
        assert q.get_running_for_cl("CL-1") is info

    def test_returns_none_after_completion(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")
        q.complete(info.task_id, success=True, message="ok", output="")
        assert q.get_running_for_cl("CL-1") is None

    def test_returns_none_for_different_cl(self) -> None:
        q = TaskQueue()
        q.submit("sync", "CL-1", "/proj.sase")
        assert q.get_running_for_cl("CL-2") is None

    def test_returns_running_task_for_generic_key(self) -> None:
        q = TaskQueue()
        info = q.submit(
            "launch",
            "foo",
            "/proj.sase",
            display_name="launch foo",
            dedup_key="launch:foo",
        )

        assert q.get_running_for_key("launch:foo") is info
        assert q.get_running_for_key("launch:bar") is None

    def test_generic_key_returns_none_after_completion(self) -> None:
        q = TaskQueue()
        info = q.submit("launch", "foo", "/proj.sase", dedup_key="launch:foo")
        q.complete(info.task_id, success=True, message="ok", output="")

        assert q.get_running_for_key("launch:foo") is None


# ---------------------------------------------------------------------------
# TaskQueue.get_all / remove
# ---------------------------------------------------------------------------


class TestTaskQueueGetAllRemove:
    def test_get_all_returns_newest_first(self) -> None:
        q = TaskQueue()
        a = q.submit("sync", "CL-1", "/proj.sase")
        b = q.submit("mail", "CL-2", "/proj.sase")
        result = q.get_all()
        assert result[0].task_id == b.task_id
        assert result[1].task_id == a.task_id

    def test_remove(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")
        q.remove(info.task_id)
        assert q.get_all() == []

    def test_remove_unknown_id_is_noop(self) -> None:
        q = TaskQueue()
        q.remove("nonexistent")


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestTaskQueueThreadSafety:
    def test_concurrent_submits(self) -> None:
        q = TaskQueue()
        results: list[TaskInfo] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            info = q.submit("sync", f"CL-{i}", "/proj.sase")
            with lock:
                results.append(info)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 20
        ids = {r.task_id for r in results}
        assert len(ids) == 20  # all unique


# ---------------------------------------------------------------------------
# capture_output
# ---------------------------------------------------------------------------


class TestCaptureOutput:
    def test_captures_stdout(self) -> None:
        with capture_output() as buf:
            print("hello")
        assert buf.getvalue() == "hello\n"

    def test_captures_stderr(self) -> None:
        with capture_output() as buf:
            print("err", file=sys.stderr)
        assert buf.getvalue() == "err\n"

    def test_restores_streams_on_success(self) -> None:
        orig_out, orig_err = sys.stdout, sys.stderr
        with capture_output():
            pass
        assert sys.stdout is orig_out
        assert sys.stderr is orig_err

    def test_restores_streams_on_exception(self) -> None:
        orig_out, orig_err = sys.stdout, sys.stderr
        try:
            with capture_output():
                raise ValueError("boom")
        except ValueError:
            pass
        assert sys.stdout is orig_out
        assert sys.stderr is orig_err

    def test_buffer_is_stringio(self) -> None:
        with capture_output() as buf:
            assert isinstance(buf, io.StringIO)


class _TaskActionsHarness(TaskActionsMixin):
    def __init__(self) -> None:
        self._init_task_queue()
        self.notifications: list[tuple[str, str | None]] = []
        self.reloads = 0
        self.workers: list[Any] = []

    def run_worker(self, fn: Any, *, thread: bool = False) -> Any:
        assert thread is True
        worker = SimpleNamespace(result=fn(), error=None, cancelled=False)

        def _cancel() -> None:
            worker.cancelled = True

        worker.cancel = _cancel
        self.workers.append(worker)
        return worker

    def notify(self, msg: str, *, severity: str | None = None) -> None:
        self.notifications.append((msg, severity))

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("no DOM")

    def _reload_and_reposition(self) -> None:
        self.reloads += 1


def test_submit_tracked_task_completes_queue_and_typed_callback() -> None:
    app = _TaskActionsHarness()
    completions: list[TrackedTaskCompletion[str]] = []

    info = app._submit_tracked_task(
        "launch",
        "foo",
        "/proj.sase",
        lambda: TrackedTaskResult(True, "done", payload="payload"),
        display_name="launch foo",
        dedup_key="launch:foo",
        on_complete=completions.append,
        reload_on_complete=False,
        notify_on_complete=False,
    )

    assert info is not None
    assert info.status == "running"
    assert app._task_queue.running_count == 1

    app._on_task_worker_completed(app.workers[0])

    assert info.status == "success"
    assert info.message == "done"
    assert app._task_queue.running_count == 0
    assert [completion.payload for completion in completions] == ["payload"]
    assert app.notifications == []
    assert app.reloads == 0


# ---------------------------------------------------------------------------
# Custom dedup keys opt out of per-CL dedup
# ---------------------------------------------------------------------------


class TestTaskQueueCustomKeyScoping:
    def test_custom_dedup_key_task_invisible_to_per_cl_dedup(self) -> None:
        # Launch and cleanup tasks carry a real CL name for display but a
        # custom dedup key; they must never block ChangeSpec actions that
        # dedup via get_running_for_cl on the same CL.
        q = TaskQueue()
        info = q.submit(
            "dismiss",
            "CL-1",
            "/proj.sase",
            display_name="dismiss agent for CL-1",
            dedup_key="dismiss:0123abcd",
        )

        assert q.get_running_for_cl("CL-1") is None
        assert q.get_running_for_key("dismiss:0123abcd") is info

    def test_per_cl_task_still_visible_alongside_custom_key_task(self) -> None:
        q = TaskQueue()
        q.submit("dismiss", "CL-1", "/proj.sase", dedup_key="dismiss:0123abcd")
        sync_info = q.submit("sync", "CL-1", "/proj.sase")

        assert q.get_running_for_cl("CL-1") is sync_info
