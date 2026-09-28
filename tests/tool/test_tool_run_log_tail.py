"""Tests for the shared ToolRun log-tail helper (epic sase-1bt).

Covers the availability cases (available, truncated, pruned, owner log
missing, not recorded) and pins the ``sase tool show --log`` replay bytes
the helper shares its selection logic with.
"""

from __future__ import annotations

from pathlib import Path

from sase.tool.logs import _ToolRunLogTail, record_truncation, tool_run_log_tail
from sase.tool.query import _replay_logs


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_available_run_tail(tmp_path: Path) -> None:
    stdout = _write(tmp_path / "stdout.log", "out1\nout2\nout3\n")
    stderr = _write(tmp_path / "stderr.log", "err1\n")
    tail = tool_run_log_tail(
        "run-1",
        {"stdout_path": str(stdout), "stderr_path": str(stderr)},
        None,
        None,
        12,
        65536,
    )
    assert tail.availability == "available"
    assert tail.source == "run"
    assert tail.lines == ("out1", "out2", "out3", "err1")
    assert tail.total_bytes == stdout.stat().st_size + stderr.stat().st_size
    assert tail.truncated is False


def test_global_line_cap_across_streams_marks_truncated(tmp_path: Path) -> None:
    stdout = _write(tmp_path / "stdout.log", "out1\nout2\nout3\n")
    stderr = _write(tmp_path / "stderr.log", "err1\n")
    tail = tool_run_log_tail(
        "run-1",
        {"stdout_path": str(stdout), "stderr_path": str(stderr)},
        None,
        None,
        2,
        65536,
    )
    assert tail.availability == "truncated"
    assert tail.lines == ("out3", "err1")
    assert tail.truncated is True


def test_full_tail_is_not_truncated(tmp_path: Path) -> None:
    stdout = _write(tmp_path / "stdout.log", "out1\nout2\n")
    tail = tool_run_log_tail(
        "run-1", {"stdout_path": str(stdout)}, None, None, 12, 65536
    )
    assert tail.availability == "available"
    assert tail.lines == ("out1", "out2")
    assert tail.truncated is False


def test_truncated_on_rotation_marker(tmp_path: Path) -> None:
    stdout = _write(tmp_path / "stdout.log", "new\n")
    _write(tmp_path / "stdout.log.1", "old1\nold2\nold3\n")
    tail = tool_run_log_tail(
        "run-1", {"stdout_path": str(stdout)}, None, None, 12, 65536
    )
    assert tail.availability == "truncated"
    assert tail.truncated is True
    assert tail.lines == ("old1", "old2", "old3", "new")


def test_truncated_on_recorded_dropped_bytes(tmp_path: Path) -> None:
    stdout = _write(tmp_path / "stdout.log", "out1\n")
    events = tmp_path / "events.jsonl"
    events.touch()
    assert record_truncation(events, "run-1", ["stdout dropped 10 bytes"]) is True
    tail = tool_run_log_tail(
        "run-1",
        {"stdout_path": str(stdout), "events_path": str(events)},
        None,
        None,
        12,
        65536,
    )
    assert tail.availability == "truncated"
    assert tail.truncated is True


def test_truncated_on_byte_cap(tmp_path: Path) -> None:
    stdout = _write(tmp_path / "stdout.log", "".join(f"line{i}\n" for i in range(50)))
    tail = tool_run_log_tail("run-1", {"stdout_path": str(stdout)}, None, None, 50, 64)
    assert tail.availability == "truncated"
    assert tail.truncated is True
    assert len(tail.lines) < 50


def test_pruned_when_retention_took_the_logs(tmp_path: Path) -> None:
    tail = tool_run_log_tail(
        "run-1",
        {
            "stdout_path": str(tmp_path / "gone-stdout.log"),
            "detail_pruned": True,
        },
        None,
        None,
        12,
        65536,
    )
    assert tail == _ToolRunLogTail(availability="pruned", source="none")


def test_not_recorded_without_paths_or_owner() -> None:
    tail = tool_run_log_tail("run-1", {}, None, None, 12, 65536)
    assert tail == _ToolRunLogTail(availability="not-recorded", source="none")


def test_missing_files_without_pruning_signal_are_not_recorded(
    tmp_path: Path,
) -> None:
    tail = tool_run_log_tail(
        "run-1",
        {"stdout_path": str(tmp_path / "gone.log")},
        None,
        None,
        12,
        65536,
    )
    assert tail.availability == "not-recorded"


def test_owner_log_path_is_used_when_recorded(tmp_path: Path) -> None:
    owner_log = _write(tmp_path / "owner.log", "o1\no2\n")
    tail = tool_run_log_tail(
        "run-1",
        {"owner_log_path": str(owner_log)},
        "proc",
        "proc-1",
        12,
        65536,
    )
    assert tail.availability == "available"
    assert tail.source == "owner"
    assert tail.lines == ("o1", "o2")


def test_owner_log_missing_is_reported(tmp_path: Path) -> None:
    tail = tool_run_log_tail(
        "run-1",
        {"owner_log_path": str(tmp_path / "gone-owner.log")},
        "proc",
        "proc-1",
        12,
        65536,
    )
    assert tail.availability == "owner-missing"
    assert tail.source == "none"


def test_unknown_proc_owner_is_missing_not_crash() -> None:
    tail = tool_run_log_tail("run-1", {}, "proc", "no-such-proc", 12, 65536)
    assert tail.availability == "owner-missing"


def test_show_log_replay_stays_byte_identical(tmp_path, capsys) -> None:
    """Pin the show --log bytes the shared helper mirrors."""

    stdout = _write(tmp_path / "stdout.log", "out1\nout2\n")
    stderr = _write(tmp_path / "stderr.log", "err1\n")
    run = {
        "run_id": "run-1",
        "logs": {"stdout_path": str(stdout), "stderr_path": str(stderr)},
    }
    assert _replay_logs(run) == 0
    captured = capsys.readouterr()
    assert captured.out == "out1\nout2\n"
    assert captured.err == (
        "err1\n"
        "sase: no total order between the retained stdout and stderr "
        "streams; order across them is not the child's write order\n"
    )


def test_show_log_replay_rotation_notice_is_byte_identical(tmp_path, capsys) -> None:
    stdout = _write(tmp_path / "stdout.log", "new\n")
    _write(tmp_path / "stdout.log.1", "old\n")
    run = {"run_id": "run-1", "logs": {"stdout_path": str(stdout)}}
    assert _replay_logs(run) == 0
    captured = capsys.readouterr()
    assert captured.out == "new\n"
    assert captured.err == "sase: stdout retained log was rotated/truncated\n"
