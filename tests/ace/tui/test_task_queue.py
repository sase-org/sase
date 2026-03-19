"""Tests for sase.ace.tui.task_queue."""

from __future__ import annotations

import io
import sys
import threading

from sase.ace.tui.task_queue import _TaskInfo, TaskQueue, capture_output


# ---------------------------------------------------------------------------
# TaskQueue.submit
# ---------------------------------------------------------------------------


class TestTaskQueueSubmit:
    def test_submit_creates_running_task(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.gp")

        assert info.status == "running"
        assert info.task_type == "sync"
        assert info.cl_name == "CL-1"
        assert info.project_file == "/proj.gp"
        assert info.finished_at is None

    def test_submit_generates_unique_ids(self) -> None:
        q = TaskQueue()
        a = q.submit("sync", "CL-1", "/proj.gp")
        b = q.submit("mail", "CL-2", "/proj.gp")
        assert a.task_id != b.task_id


# ---------------------------------------------------------------------------
# TaskQueue.complete
# ---------------------------------------------------------------------------


class TestTaskQueueComplete:
    def test_complete_success(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.gp")
        q.complete(info.task_id, success=True, message="ok", output="log")

        assert info.status == "success"
        assert info.message == "ok"
        assert info.output == "log"
        assert info.error is None
        assert info.finished_at is not None

    def test_complete_error(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.gp")
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
        info = q.submit("sync", "CL-1", "/proj.gp")
        assert q.get_running_for_cl("CL-1") is info

    def test_returns_none_after_completion(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.gp")
        q.complete(info.task_id, success=True, message="ok", output="")
        assert q.get_running_for_cl("CL-1") is None

    def test_returns_none_for_different_cl(self) -> None:
        q = TaskQueue()
        q.submit("sync", "CL-1", "/proj.gp")
        assert q.get_running_for_cl("CL-2") is None


# ---------------------------------------------------------------------------
# TaskQueue.get_all / remove
# ---------------------------------------------------------------------------


class TestTaskQueueGetAllRemove:
    def test_get_all_returns_newest_first(self) -> None:
        q = TaskQueue()
        a = q.submit("sync", "CL-1", "/proj.gp")
        b = q.submit("mail", "CL-2", "/proj.gp")
        result = q.get_all()
        assert result[0].task_id == b.task_id
        assert result[1].task_id == a.task_id

    def test_remove(self) -> None:
        q = TaskQueue()
        info = q.submit("sync", "CL-1", "/proj.gp")
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
        results: list[_TaskInfo] = []
        lock = threading.Lock()

        def worker(i: int) -> None:
            info = q.submit("sync", f"CL-{i}", "/proj.gp")
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
