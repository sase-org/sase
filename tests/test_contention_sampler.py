"""The contention soak's diagnostic sampler.

The sampler is evidence for a run that may die without uploading anything, so
these tests pin what it must survive and record: hosts without PSI, cgroups, or
smaps, senders that exit before they can be read, and a soak parent that dies
without stopping it. Real processes are used only where the kernel is the thing
under test (signal sender capture and sampler lifetime), and every signal here
is aimed at one process the test itself started.
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests._contention import (
    CONTROLLER_PROGRESS_FILENAME,
    KILLS_FILENAME,
    progress_directory,
    write_json_atomic,
)
from tests._contention_procfs import ProcFS, parse_stat, scan_usage, soak_tree
from tests._contention_sampler import (
    POST_ROOT_OBSERVATION_LIMIT,
    SAMPLER_REAP_TIMEOUT_SECONDS,
    SAMPLER_STOP_TIMEOUT_SECONDS,
    SAMPLES_FILENAME,
    SIGNALS_FILENAME,
    Sampler,
    SamplerHandle,
    read_progress,
)


ROOT = Path(__file__).resolve().parents[1]
GIB = 2**30


def _stat_line(
    pid: int,
    ppid: int,
    comm: str = "python3",
    *,
    threads: int = 1,
    rss_pages: int = 0,
    major_faults: int = 0,
    start_time_ticks: int | None = None,
    pgrp: int | None = None,
) -> str:
    start = pid * 10 if start_time_ticks is None else start_time_ticks
    group = ppid if pgrp is None else pgrp
    return (
        f"{pid} ({comm}) S {ppid} {group} 0 0 -1 0 0 0 {major_faults} 0 0 0 0 0 "
        f"20 0 {threads} 0 {start} 0 {rss_pages}\n"
    )


def _fake_host(tmp_path: Path, *, with_optional_fields: bool = True) -> ProcFS:
    """A small /proc and cgroup tree: parent 100 > controller 101 > worker 102
    > test child 103, plus an unrelated process 200."""
    proc = tmp_path / "proc"
    cgroups = tmp_path / "cgroup"
    tree = {
        100: (1, "python3", 1, 1000),
        101: (100, "python3", 2, 2000),
        102: (101, "python3", 4, 250_000),
        103: (102, "sase", 1, 25_000),
        200: (1, "sshd", 1, 500),
    }
    for pid, (ppid, comm, threads, rss_pages) in tree.items():
        directory = proc / str(pid)
        directory.mkdir(parents=True)
        (directory / "stat").write_text(
            _stat_line(pid, ppid, comm, threads=threads, rss_pages=rss_pages)
        )
        (directory / "cmdline").write_bytes(f"{comm}\0--pid\0{pid}\0".encode())
        if with_optional_fields:
            (directory / "smaps_rollup").write_text(
                f"Rss: {rss_pages * 4} kB\nPss: {rss_pages * 2} kB\nSwap: 8 kB\n"
            )
    (proc / "self").mkdir()
    (proc / "meminfo").write_text(
        "MemTotal: 16777216 kB\nMemAvailable: 4194304 kB\n"
        "SwapTotal: 4194304 kB\nSwapFree: 2097152 kB\n"
    )
    (proc / "vmstat").write_text("pswpin 10\npswpout 20\noom_kill 0\nnr_free 1\n")
    (proc / "loadavg").write_text("27.50 20.10 9.00 30/400 12345\n")
    if with_optional_fields:
        (proc / "self" / "cgroup").write_text("0::/runner.slice\n")
        (proc / "pressure").mkdir()
        (proc / "pressure" / "memory").write_text(
            "some avg10=42.50 avg60=10.00 avg300=1.00 total=1\n"
            "full avg10=30.25 avg60=5.00 avg300=0.50 total=1\n"
        )
        slice_dir = cgroups / "runner.slice"
        slice_dir.mkdir(parents=True)
        (slice_dir / "memory.current").write_text(f"{3 * GIB}\n")
        (slice_dir / "memory.max").write_text("max\n")
        (slice_dir / "memory.events").write_text(
            "low 0\nhigh 0\nmax 2\noom 1\noom_kill 1\n"
        )
    return ProcFS(proc, cgroups)


def _sampler(tmp_path: Path, procfs: ProcFS) -> tuple[Sampler, io.StringIO]:
    stream = io.StringIO()
    out = tmp_path / "diagnostics"
    out.mkdir()
    sampler = Sampler(
        root_pid=100,
        out=out,
        paths={"scratch": tmp_path, "tmp": tmp_path / "absent"},
        procfs=procfs,
        stream=stream,
    )
    return sampler, stream


def test_stat_parsing_survives_spaces_and_parentheses_in_comm() -> None:
    stat = parse_stat(7, _stat_line(7, 3, "py (x) y", threads=9, rss_pages=2))

    assert (
        stat.ppid,
        stat.pgrp,
        stat.comm,
        stat.start_time_ticks,
        stat.threads,
    ) == (3, 3, "py (x) y", 70, 9)
    assert stat.rss_bytes == 2 * os.sysconf("SC_PAGE_SIZE")


def test_soak_tree_counts_each_process_once_and_skips_the_sampler(
    tmp_path: Path,
) -> None:
    stats = _fake_host(tmp_path).all_stats()

    assert soak_tree(stats, 100, exclude=0) == {100: 0, 101: 1, 102: 2, 103: 3}
    assert soak_tree(stats, 100, exclude=102) == {100: 0, 101: 1}
    assert soak_tree(stats, 999, exclude=0) == {}


def test_sample_reports_role_memory_host_cgroup_and_progress(tmp_path: Path) -> None:
    sampler, stream = _sampler(tmp_path, _fake_host(tmp_path))
    repeat = progress_directory(sampler.out, 1)
    repeat.mkdir(parents=True)
    write_json_atomic(
        repeat / CONTROLLER_PROGRESS_FILENAME,
        {
            "workers_configured": 26,
            "collection": {"workers_finished": 12, "items": 60493},
            "finished": 0,
            "failed_reports": 0,
        },
    )

    record = sampler.sample()

    soak = record["soak"]
    assert soak["procs"] == 4
    assert soak["threads"] == 8
    assert soak["by_role"]["worker"]["count"] == 1
    # PSS comes from smaps_rollup, and is kept apart from summed RSS.
    assert soak["pss"] == soak["rss"] // 2 or soak["pss"] < soak["rss"]
    assert record["cgroup"]["max"] == "max"
    assert record["cgroup"]["events"]["oom_kill"] == 1
    assert record["pressure"]["memory"] == {"some": 42.5, "full": 30.25}
    assert record["filesystems"]["tmp"] is None
    assert record["filesystems"]["scratch"]["free_bytes"] > 0
    assert "scratch_usage" in record
    line = stream.getvalue()
    assert line.startswith("[contention-diag] +")
    assert "collected 12/26 workers (60493 items)" in line
    assert "psi10 mem 42.5/30.25" in line
    stored = (sampler.out / SAMPLES_FILENAME).read_text().splitlines()
    assert json.loads(stored[-1])["kind"] == "sample"


def test_final_root_death_sample_counts_only_identity_checked_survivors(
    tmp_path: Path,
) -> None:
    procfs = _fake_host(tmp_path)
    sampler, _ = _sampler(tmp_path, procfs)
    sampler.sample()

    # The parent and controller exited; their already observed worker and test
    # child survive and have been reparented. An unrelated member of the same
    # process group is not run membership evidence.
    for pid in (100, 101):
        directory = procfs.root / str(pid)
        for name in ("stat", "cmdline", "smaps_rollup"):
            path = directory / name
            if path.exists():
                path.unlink()
        directory.rmdir()
    (procfs.root / "102" / "stat").write_text(
        _stat_line(102, 1, "python3", start_time_ticks=1020, pgrp=100)
    )
    (procfs.root / "103" / "stat").write_text(
        _stat_line(103, 102, "sase", start_time_ticks=1030, pgrp=100)
    )
    (procfs.root / "200" / "stat").write_text(
        _stat_line(200, 1, "sshd", start_time_ticks=2000, pgrp=100)
    )

    record = sampler.sample(reason="final: soak parent exited")

    assert record["root_alive"] is False
    assert record["membership"] == "observed-survivors"
    assert record["post_root_observations"] == 1
    assert record["soak"]["procs"] == 2
    assert {record["top_rss"][i]["pid"] for i in range(2)} == {102, 103}


def test_reused_pid_is_not_counted_as_an_observed_survivor(tmp_path: Path) -> None:
    procfs = _fake_host(tmp_path)
    sampler, _ = _sampler(tmp_path, procfs)
    sampler.sample()

    for pid in (100, 101):
        directory = procfs.root / str(pid)
        for name in ("stat", "cmdline", "smaps_rollup"):
            path = directory / name
            if path.exists():
                path.unlink()
        directory.rmdir()
    # PID 102 now names a different process, despite sharing the old parent
    # and process group IDs. The old test child 103 remains the same process.
    (procfs.root / "102" / "stat").write_text(
        _stat_line(102, 1, "replacement", start_time_ticks=999_999, pgrp=100)
    )
    (procfs.root / "103" / "stat").write_text(
        _stat_line(103, 102, "sase", start_time_ticks=1030, pgrp=100)
    )

    record = sampler.sample(reason="final: soak parent exited")

    assert record["soak"]["procs"] == 1
    assert record["top_rss"][0]["pid"] == 103


def test_root_death_observation_is_bounded(tmp_path: Path) -> None:
    procfs = _fake_host(tmp_path)
    sampler, _ = _sampler(tmp_path, procfs)
    sampler.sample()
    root = procfs.root / "100"
    for name in ("stat", "cmdline", "smaps_rollup"):
        (root / name).unlink()
    root.rmdir()

    records = [
        sampler.sample(reason="root exited")
        for _ in range(POST_ROOT_OBSERVATION_LIMIT + 1)
    ]

    assert records[0]["soak"]["procs"] == 3
    assert records[POST_ROOT_OBSERVATION_LIMIT - 1]["soak"]["procs"] == 3
    assert records[-1]["soak"]["procs"] == 0
    assert records[-1]["post_root_observations"] == POST_ROOT_OBSERVATION_LIMIT


def test_missing_process_start_time_is_not_used_as_membership(
    tmp_path: Path,
) -> None:
    procfs = _fake_host(tmp_path)
    raw = _stat_line(103, 102, "sase")
    close = raw.rindex(")")
    fields = raw[close + 2 :].split()
    fields.pop(19)
    missing_start = f"103 (sase) {' '.join(fields)}\n"
    (procfs.root / "103" / "stat").write_text(missing_start)
    sampler, _ = _sampler(tmp_path, procfs)

    record = sampler.sample()

    assert procfs.stat(103) is None
    assert record["soak"]["procs"] == 3


def test_sampler_reaping_uses_explicit_wait_limits() -> None:
    class _Process:
        def __init__(self) -> None:
            self.stdin = io.BytesIO()
            self.wait_timeouts: list[float] = []
            self.killed = False

        def wait(self, *, timeout: float) -> int:
            self.wait_timeouts.append(timeout)
            if len(self.wait_timeouts) == 1:
                raise subprocess.TimeoutExpired("sampler", timeout)
            return 0

        def kill(self) -> None:
            self.killed = True

    process = _Process()
    result = SamplerHandle(process).stop()

    assert result == 0
    assert process.killed is True
    assert process.wait_timeouts == [
        SAMPLER_STOP_TIMEOUT_SECONDS,
        SAMPLER_REAP_TIMEOUT_SECONDS,
    ]


def test_missing_proc_and_cgroup_fields_degrade_to_unknown(tmp_path: Path) -> None:
    sampler, stream = _sampler(
        tmp_path, _fake_host(tmp_path, with_optional_fields=False)
    )

    record = sampler.sample()
    sampler.finish("stopped by the harness")

    assert record["cgroup"] is None
    assert record["soak"]["pss"] == 0
    assert record["pressure"]["memory"] == {}
    output = stream.getvalue()
    assert "cgroup ?/?" in output
    assert "progress none yet" in output
    assert "stopped (stopped by the harness)" in output


def test_signal_names_a_sender_that_exited_and_the_test_its_worker_ran(
    tmp_path: Path,
) -> None:
    procfs = _fake_host(tmp_path)
    sampler, stream = _sampler(tmp_path, procfs)
    repeat = progress_directory(sampler.out, 1)
    repeat.mkdir(parents=True)
    write_json_atomic(
        repeat / "worker-gw3.json",
        {
            "worker": "gw3",
            "pid": 102,
            "start_time_ticks": 1020,
            "nodeid": "tests/t.py::test_kills_its_group",
            "started_at": time.time() - 30,
            "finished_at": None,
        },
    )
    (repeat / KILLS_FILENAME).write_text(
        json.dumps(
            {
                "worker": "gw3",
                "call": "os.killpg(0, SIGTERM)",
                "reason": "caller's own process group",
                "nodeid": "tests/t.py::test_kills_its_group",
            }
        )
        + "\n"
    )
    sampler.sample()
    # The sender exits between the last sample and the signal.
    for name in ("stat", "cmdline", "smaps_rollup"):
        (procfs.root / "103" / name).unlink()
    (procfs.root / "103").rmdir()
    info = SimpleNamespace(
        si_signo=int(signal.SIGTERM), si_code=0, si_pid=103, si_uid=1001
    )

    record = sampler.on_signal(info)

    chain = record["sender_chain"]
    assert [item["pid"] for item in chain] == [103, 102, 101, 100, 1]
    assert chain[0]["gone"] is True and chain[0]["role"] == "descendant"
    assert chain[1]["worker"] == "gw3"
    assert record["sender_worker"]["nodeid"] == "tests/t.py::test_kills_its_group"
    assert record["code"] == "SI_USER"
    output = stream.getvalue()
    assert "SIGTERM (SI_USER) from pid 103 uid 1001" in output
    assert "sender's worker gw3 was running tests/t.py::test_kills_its_group" in output
    assert "hazardous kill: gw3 os.killpg(0, SIGTERM)" in output
    stored = json.loads((sampler.out / SIGNALS_FILENAME).read_text())
    assert stored["sender_pid"] == 103


def test_progress_reader_uses_the_latest_repeat_and_skips_bad_records(
    tmp_path: Path,
) -> None:
    for index in (1, 2):
        progress_directory(tmp_path, index).mkdir(parents=True)
    latest = progress_directory(tmp_path, 2)
    (latest / "worker-gw0.json").write_text("{not json")
    write_json_atomic(latest / "worker-gw1.json", {"pid": 7, "worker": "gw1"})
    (latest / KILLS_FILENAME).write_text('{"call": "a"}\nbroken\n')

    progress = read_progress(tmp_path / "progress")

    assert progress is not None
    assert progress["repeat"] == "repeat-02"
    assert list(progress["workers"]) == [7]
    assert progress["kill_count"] == 1
    assert read_progress(tmp_path / "absent") is None


def test_usage_scan_is_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for index in range(5):
        (tmp_path / f"f{index}").write_bytes(b"x" * 10)
    monkeypatch.setattr("tests._contention_procfs.USAGE_SCAN_MAX_ENTRIES", 3)

    usage = scan_usage(tmp_path)

    assert usage["entries"] == 3
    assert usage["truncated"] is True


# --- real processes: the harness, the sampler, and one targeted signal -------

HARNESS = textwrap.dedent(
    """
    import os, subprocess, sys
    from pathlib import Path
    from tests._contention_sampler import start_sampler

    out, mode = Path(sys.argv[1]), sys.argv[2]
    handle = start_sampler(
        out, root_pid=os.getpid(), paths={"scratch": out.parent},
        interval=0.2, cwd=Path.cwd(),
    )
    if mode == "exit":
        code = subprocess.run([sys.executable, "-c", "raise SystemExit(3)"]).returncode
        handle.stop()
        raise SystemExit(code)
    sys.stdin.read()  # "orphan": exit without stopping the sampler
    """
)


def _start_harness(tmp_path: Path, mode: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", HARNESS, str(tmp_path / "diagnostics"), mode],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )


def _poll(predicate: Any, what: str, timeout: float = 30.0) -> Any:
    deadline = time.monotonic() + timeout
    while not (value := predicate()):
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.05)  # sase-test-wait: polls a real child process's files
    return value


def _sampler_pid(out: Path) -> int:
    def header() -> dict[str, Any] | None:
        try:
            return json.loads((out / SAMPLES_FILENAME).read_text().splitlines()[0])
        except (OSError, IndexError, ValueError):
            return None

    return int(_poll(header, "the sampler header")["sampler_pid"])


def _gone(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return True
    return state == "Z"


def test_harness_exit_status_survives_and_the_sampler_stops(tmp_path: Path) -> None:
    harness = _start_harness(tmp_path, "exit")
    stdout, _ = harness.communicate(timeout=60)

    assert harness.returncode == 3
    out = tmp_path / "diagnostics"
    records = [
        json.loads(line) for line in (out / SAMPLES_FILENAME).read_text().splitlines()
    ]
    assert records[0]["kind"] == "header"
    assert records[-1]["reason"] == "final: stopped by the harness"
    assert "stopped (stopped by the harness)" in stdout
    assert _gone(records[0]["sampler_pid"])


def test_signal_sender_is_recorded_and_an_orphaned_sampler_exits(
    tmp_path: Path,
) -> None:
    harness = _start_harness(tmp_path, "orphan")
    out = tmp_path / "diagnostics"
    try:
        sampler_pid = _sampler_pid(out)
        # Aimed at the one sampler this test started, never a group.
        os.kill(sampler_pid, signal.SIGTERM)
        signals = out / SIGNALS_FILENAME
        _poll(signals.exists, "the signal record")
        record = json.loads(signals.read_text().splitlines()[0])
        assert record["signal"] == "SIGTERM"
        assert record["sender_pid"] == os.getpid()
        assert record["code"] == "SI_USER"
        assert not _gone(sampler_pid), "the sampler must outlive a SIGTERM"
    finally:
        stdout, _ = harness.communicate(input="", timeout=60)

    _poll(lambda: _gone(sampler_pid), "the orphaned sampler to exit")
    assert "stopped (soak parent exited)" in stdout
