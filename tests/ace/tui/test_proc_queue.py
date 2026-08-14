"""Tests for sase.ace.tui.proc_queue."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.proc_actions import (
    ProcActionsMixin,
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.ace.tui.proc_queue import (
    ProcInfo,
    ProcQueue,
    _ProcLog,
    redirect_print_to,
)
from sase.ace.tui.proc_subprocess import ProcReporter, _stream_subprocess


# ---------------------------------------------------------------------------
# ProcQueue.submit
# ---------------------------------------------------------------------------


class TestProcQueueSubmit:
    def test_submit_creates_running_proc(self) -> None:
        q = ProcQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")

        assert info.status == "running"
        assert info.proc_type == "sync"
        assert info.cl_name == "CL-1"
        assert info.project_file == "/proj.sase"
        assert info.finished_at is None

    def test_submit_generates_unique_ids(self) -> None:
        q = ProcQueue()
        a = q.submit("sync", "CL-1", "/proj.sase")
        b = q.submit("mail", "CL-2", "/proj.sase")
        assert a.proc_id != b.proc_id

    def test_submit_accepts_display_name_and_dedup_key(self) -> None:
        q = ProcQueue()
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
# ProcQueue.complete
# ---------------------------------------------------------------------------


class TestProcQueueComplete:
    def test_complete_success(self) -> None:
        q = ProcQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")
        q.complete(info.proc_id, success=True, message="ok", output="log")

        assert info.status == "success"
        assert info.message == "ok"
        assert info.output == "log"
        assert info.error is None
        assert info.finished_at is not None

    def test_complete_error(self) -> None:
        q = ProcQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")
        q.complete(
            info.proc_id,
            success=False,
            message="boom",
            output="log",
            error="boom",
        )

        assert info.status == "error"
        assert info.error == "boom"
        assert info.finished_at is not None

    def test_complete_unknown_id_is_noop(self) -> None:
        q = ProcQueue()
        q.complete("nonexistent", success=True, message="x", output="")


# ---------------------------------------------------------------------------
# ProcQueue.get_running_for_cl  (deduplication)
# ---------------------------------------------------------------------------


class TestProcQueueDedup:
    def test_returns_running_proc(self) -> None:
        q = ProcQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")
        assert q.get_running_for_cl("CL-1") is info

    def test_returns_none_after_completion(self) -> None:
        q = ProcQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")
        q.complete(info.proc_id, success=True, message="ok", output="")
        assert q.get_running_for_cl("CL-1") is None

    def test_returns_none_for_different_cl(self) -> None:
        q = ProcQueue()
        q.submit("sync", "CL-1", "/proj.sase")
        assert q.get_running_for_cl("CL-2") is None

    def test_returns_running_proc_for_generic_key(self) -> None:
        q = ProcQueue()
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
        q = ProcQueue()
        info = q.submit("launch", "foo", "/proj.sase", dedup_key="launch:foo")
        q.complete(info.proc_id, success=True, message="ok", output="")

        assert q.get_running_for_key("launch:foo") is None

    def test_update_scopes_conflict_by_intersection(self) -> None:
        q = ProcQueue()
        comprehensive = q.submit(
            "comprehensive-update",
            "updates",
            "",
            dedup_key="comprehensive-update",
            exclusive_scopes=("sase-update", "agent-cli-update"),
        )

        assert q.get_running_for_scopes(("sase-update",)) is comprehensive
        assert q.get_running_for_scopes(("agent-cli-update",)) is comprehensive
        assert q.get_running_for_scopes(("plugin-install",)) is None


def test_tracked_update_scope_blocks_different_dedup_key() -> None:
    app = _ProcActionsHarness()
    first = app._submit_tracked_proc(
        "comprehensive-update",
        "updates",
        "",
        lambda: TrackedProcResult(True, "done"),
        dedup_key="comprehensive-update",
        exclusive_scopes=("sase-update", "agent-cli-update"),
    )

    blocked = app._submit_tracked_proc(
        "sase-update",
        "sase",
        "",
        lambda: TrackedProcResult(True, "done"),
        dedup_key="sase-update",
        exclusive_scopes=("sase-update",),
        duplicate_message="update conflict",
    )

    assert first is not None
    assert blocked is None
    assert app.notifications[-1] == ("update conflict", "warning")


# ---------------------------------------------------------------------------
# ProcQueue.get_all / remove
# ---------------------------------------------------------------------------


class TestProcQueueGetAllRemove:
    def test_get_all_returns_newest_first(self) -> None:
        q = ProcQueue()
        a = q.submit("sync", "CL-1", "/proj.sase")
        b = q.submit("mail", "CL-2", "/proj.sase")
        result = q.get_all()
        assert result[0].proc_id == b.proc_id
        assert result[1].proc_id == a.proc_id

    def test_remove(self) -> None:
        q = ProcQueue()
        info = q.submit("sync", "CL-1", "/proj.sase")
        q.remove(info.proc_id)
        assert q.get_all() == []

    def test_remove_unknown_id_is_noop(self) -> None:
        q = ProcQueue()
        q.remove("nonexistent")


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestProcQueueThreadSafety:
    def test_concurrent_submits(self) -> None:
        q = ProcQueue()
        results: list[ProcInfo] = []
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
        ids = {r.proc_id for r in results}
        assert len(ids) == 20  # all unique


# ---------------------------------------------------------------------------
# _ProcLog
# ---------------------------------------------------------------------------


class TestProcLog:
    def test_append_snapshot_and_text(self) -> None:
        log = _ProcLog()

        log.append("line 1\nline 2", stream="stdout")
        snapshot = log.snapshot()

        assert snapshot.version == 1
        assert [line.text for line in snapshot.lines] == ["line 1", "line 2"]
        assert log.text() == "line 1\nline 2\n"

    def test_bounds_by_lines_and_reports_trimmed_count(self) -> None:
        log = _ProcLog(max_lines=2, max_chars=1_000)

        log.append("one")
        log.append("two")
        log.append("three")

        snapshot = log.snapshot()
        assert snapshot.trimmed_count == 1
        assert [line.text for line in snapshot.lines] == ["two", "three"]
        assert log.text().startswith("... 1 earlier lines trimmed\n")

    def test_redirect_print_to_captures_stdout_and_stderr(self) -> None:
        log = _ProcLog()

        with redirect_print_to(log):
            print("hello")
            print("err", file=sys.stderr)

        assert log.text() == "hello\nerr\n"


class _ProcActionsHarness(ProcActionsMixin):
    def __init__(self) -> None:
        self._init_proc_queue()
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


class _IndicatorHarness(_ProcActionsHarness):
    """Harness whose top-bar indicator records every painted count."""

    def __init__(self) -> None:
        super().__init__()
        self.indicator_counts: list[int] = []

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        harness = self

        class _Indicator:
            def set_count(self, count: int) -> None:
                harness.indicator_counts.append(count)

        return _Indicator()


def test_proc_indicator_counts_detached_procs_for_this_session() -> None:
    app = _IndicatorHarness()

    app._submit_tracked_proc(
        "launch",
        "foo",
        "/proj.sase",
        lambda: TrackedProcResult(True, "done"),
        dedup_key="launch:foo",
        reload_on_complete=False,
        notify_on_complete=False,
    )

    assert app.indicator_counts[-1] == 1

    # A detached store proc attributed to this session joins the count.
    app._apply_detached_proc_count(2)
    assert app.indicator_counts[-1] == 3

    app._on_proc_worker_completed(app.workers[0])
    assert app.indicator_counts[-1] == 2


def test_submit_tracked_proc_completes_queue_and_typed_callback() -> None:
    app = _ProcActionsHarness()
    completions: list[TrackedProcCompletion[str]] = []

    info = app._submit_tracked_proc(
        "launch",
        "foo",
        "/proj.sase",
        lambda: TrackedProcResult(True, "done", payload="payload"),
        display_name="launch foo",
        dedup_key="launch:foo",
        on_complete=completions.append,
        reload_on_complete=False,
        notify_on_complete=False,
    )

    assert info is not None
    assert info.status == "running"
    assert app._proc_queue.running_count == 1

    app._on_proc_worker_completed(app.workers[0])

    assert info.status == "success"
    assert info.message == "done"
    assert app._proc_queue.running_count == 0
    assert [completion.payload for completion in completions] == ["payload"]
    assert app.notifications == []
    assert app.reloads == 0


def test_submit_tracked_proc_passes_reporter_when_callable_accepts_it() -> None:
    app = _ProcActionsHarness()

    def proc_callable(reporter: ProcReporter) -> TrackedProcResult[str]:
        reporter.phase("Doing work")
        reporter.log("live line")
        return TrackedProcResult(True, "done", payload="payload")

    info = app._submit_tracked_proc(
        "launch",
        "foo",
        "/proj.sase",
        proc_callable,
        display_name="launch foo",
        dedup_key="launch:foo",
        reload_on_complete=False,
        notify_on_complete=False,
    )

    assert info is not None
    assert "Doing work" in info.get_live_output()
    assert "live line" in info.get_live_output()


def test_stream_subprocess_streams_lines_and_returns_completed_process() -> None:
    seen: list[str] = []

    result = _stream_subprocess(
        [
            sys.executable,
            "-c",
            "import sys; print('out', flush=True); print('err', file=sys.stderr, flush=True)",
        ],
        on_line=seen.append,
        cancel_event=threading.Event(),
    )

    assert result.returncode == 0
    assert seen == ["out", "err"]
    assert "out" in result.stdout
    assert "err" in result.stdout


def test_stream_subprocess_timeout_raises_with_captured_output() -> None:
    with pytest.raises(subprocess.TimeoutExpired) as exc_info:
        _stream_subprocess(
            [
                sys.executable,
                "-c",
                "import os, time; os.write(1, b'started\\n'); time.sleep(5)",
            ],
            on_line=lambda _line: None,
            cancel_event=threading.Event(),
            timeout=1.0,
        )

    output = exc_info.value.output
    assert isinstance(output, str)
    assert "started" in output


def test_stream_subprocess_cancel_escalates_sigterm_resistant_process() -> None:
    cancel_event = threading.Event()
    seen: list[str] = []

    def on_line(line: str) -> None:
        seen.append(line)
        cancel_event.set()

    started = time.monotonic()
    result = _stream_subprocess(
        [
            sys.executable,
            "-c",
            (
                "import signal, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('started', flush=True); "
                "time.sleep(5)"
            ),
        ],
        on_line=on_line,
        cancel_event=cancel_event,
    )
    elapsed = time.monotonic() - started

    assert seen == ["started"]
    assert result.returncode != 0
    assert elapsed < 3.0


# ---------------------------------------------------------------------------
# Custom dedup keys opt out of per-CL dedup
# ---------------------------------------------------------------------------


class TestProcQueueCustomKeyScoping:
    def test_custom_dedup_key_task_invisible_to_per_cl_dedup(self) -> None:
        # Launch and cleanup tasks carry a real Patch name for display but a
        # custom dedup key; they must never block Patch actions that
        # dedup via get_running_for_cl on the same Patch.
        q = ProcQueue()
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
        q = ProcQueue()
        q.submit("dismiss", "CL-1", "/proj.sase", dedup_key="dismiss:0123abcd")
        sync_info = q.submit("sync", "CL-1", "/proj.sase")

        assert q.get_running_for_cl("CL-1") is sync_info
