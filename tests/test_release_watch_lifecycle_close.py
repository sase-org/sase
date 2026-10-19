"""Bead close, retry, and idempotency tests for the release watcher."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from tests._release_watch_helpers import Reader, options, pr, signal_values, watch


def closed_read_output(bead_id: str) -> str:
    return f"↳   ✓  M {bead_id} · Fake bead ← sase-9zz  ⧖ 18h\n"


def open_read_output(bead_id: str) -> str:
    return f"▸   ◐ {bead_id} · Fake bead ← sase-9zz  ⧖ 1m\n"


def bead_aware_process(
    reads: dict[str, str],
    *,
    returncodes: list[int] | None = None,
):
    """Fake process routing `sase bead read` to canned output by bead id."""
    calls: list[tuple[list[str], dict[str, Any]]] = []
    codes = list(returncodes or [0])

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        if len(argv) >= 4 and argv[:3] == ["sase", "bead", "read"]:
            return subprocess.CompletedProcess(argv, 0, reads.get(argv[3], ""), "")
        code = codes.pop(0) if codes else 0
        return subprocess.CompletedProcess(argv, code, "", "failed" if code else "")

    return process, calls


def test_close_retries_three_times_and_waits_between_attempts(tmp_path: Path) -> None:
    process, calls = bead_aware_process({}, returncodes=[1, 1, 0])
    sleeps: list[float] = []
    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1kx.3"),
        Reader(),
        process=process,
        sleep=sleeps.append,
        output=lambda _line: None,
    )
    watcher.set_verdict("DEADLINE", "time elapsed")

    code = watcher.finalize()

    closes = [call for call in calls if call[0][:3] == ["sase", "bead", "close"]]
    assert code == watch.EXIT_CODES["DEADLINE"]
    assert len(closes) == 3
    assert sleeps == [30, 30]
    assert watcher.close_outcome == "closed on attempt 3"


def test_already_closed_bead_exits_without_watching(tmp_path: Path) -> None:
    process, calls = bead_aware_process(
        {"sase-1lh.5": closed_read_output("sase-1lh.5")}
    )
    output: list[str] = []
    reader = Reader(signal_values(release=pr()))
    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1lh.5"),
        reader,
        process=process,
        output=output.append,
    )

    assert watcher.run() == 0
    assert reader.reads == 0
    assert any(line.startswith("ALREADY_CLOSED") for line in output)
    assert all(
        call[0][2] == "read" for call in calls if call[0][:2] == ["sase", "bead"]
    )


def test_close_skipped_when_bead_already_closed(tmp_path: Path) -> None:
    process, calls = bead_aware_process(
        {"sase-1lh.5": closed_read_output("sase-1lh.5")}
    )
    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1lh.5"),
        Reader(),
        process=process,
        output=lambda _line: None,
    )
    watcher.set_verdict("FULL_CI_RED", "two red runs")

    assert watcher.finalize() == watch.EXIT_CODES["FULL_CI_RED"]
    assert watcher.close_outcome == "already closed (verified before attempt 1)"
    assert all(
        call[0][2] == "read" for call in calls if call[0][:2] == ["sase", "bead"]
    )


def test_close_retry_stops_when_bead_closes_elsewhere(tmp_path: Path) -> None:
    reads = iter(
        ["", closed_read_output("sase-1lh.5"), closed_read_output("sase-1lh.5")]
    )
    calls: list[tuple[list[str], dict[str, Any]]] = []
    codes = [1]

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        if len(argv) >= 4 and argv[:3] == ["sase", "bead", "read"]:
            return subprocess.CompletedProcess(argv, 0, next(reads), "")
        code = codes.pop(0) if codes else 0
        return subprocess.CompletedProcess(argv, code, "", "failed" if code else "")

    sleeps: list[float] = []
    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1lh.5"),
        Reader(),
        process=process,
        sleep=sleeps.append,
        output=lambda _line: None,
    )
    watcher.set_verdict("DEADLINE", "time elapsed")

    assert watcher.finalize() == watch.EXIT_CODES["DEADLINE"]
    closes = [call for call in calls if call[0][:3] == ["sase", "bead", "close"]]
    assert len(closes) == 1
    assert sleeps == [30]
    assert watcher.close_outcome == "already closed (verified before attempt 2)"


def test_idempotent_close_check_fails_open_on_error(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def process(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if len(argv) >= 4 and argv[:3] == ["sase", "bead", "read"]:
            raise RuntimeError("bead store unreachable")
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    watcher = watch.ReleaseWatcher(
        options(tmp_path, close_bead="sase-1lh.5"),
        Reader(),
        process=process,
        output=lambda _line: None,
    )
    watcher.set_verdict("DEADLINE", "time elapsed")

    assert watcher.finalize() == watch.EXIT_CODES["DEADLINE"]
    assert watcher.close_outcome == "closed on attempt 1"
    assert calls[0][:4] == ["sase", "bead", "close", "sase-1lh.5"]
