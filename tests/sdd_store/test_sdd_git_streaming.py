from __future__ import annotations

import os
from pathlib import Path
import signal
import sys
import time

import pytest

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.commit_publication import _bounded_publication_drain
from sase.sdd._git import SddGitCommandTimeout, run_sdd_git


def test_streaming_transfer_succeeds_while_progress_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen_args: list[list[str]] = []
    script = (
        "import sys, time\n"
        "for index in range(6):\n"
        "    sys.stderr.write(f'Counting objects: {index}\\r')\n"
        "    sys.stderr.flush()\n"
        "    time.sleep(0.05)\n"
        "sys.stdout.write('done')\n"
    )

    def command(args: list[str]) -> list[str]:
        seen_args.append(args)
        return [sys.executable, "-c", script]

    monkeypatch.setenv("SASE_SDD_GIT_NETWORK_TRANSFER_CEILING", "2")
    monkeypatch.setattr("sase.sdd._git_runner.sdd_git_command", command)

    result = run_sdd_git(
        ["clone", "source", "target"],
        cwd=tmp_path,
        op="test.clone",
        timeout=0.15,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == "done"
    assert "Counting objects: 5" in result.stderr
    assert seen_args == [["clone", "--progress", "source", "target"]]


def test_streaming_transfer_aborts_after_progress_stalls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = (
        "import sys, time\n"
        "sys.stderr.write('Receiving objects: 1\\r')\n"
        "sys.stderr.flush()\n"
        "time.sleep(0.2)\n"
    )
    monkeypatch.setenv("SASE_SDD_GIT_NETWORK_TRANSFER_CEILING", "1")
    monkeypatch.setattr(
        "sase.sdd._git_runner.sdd_git_command",
        lambda _args: [sys.executable, "-c", script],
    )

    with pytest.raises(
        SddGitCommandTimeout,
        match="stalled after 0.03s without progress",
    ):
        run_sdd_git(
            ["fetch", "origin"],
            cwd=tmp_path,
            op="test.fetch",
            timeout=0.03,
            check=True,
            capture_output=True,
            text=True,
        )


def test_streaming_transfer_aborts_at_absolute_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = (
        "import sys, time\n"
        "for index in range(10):\n"
        "    sys.stderr.write(f'Writing objects: {index}\\r')\n"
        "    sys.stderr.flush()\n"
        "    time.sleep(0.02)\n"
    )
    monkeypatch.setenv("SASE_SDD_GIT_NETWORK_TRANSFER_CEILING", "0.05")
    monkeypatch.setattr(
        "sase.sdd._git_runner.sdd_git_command",
        lambda _args: [sys.executable, "-c", script],
    )

    with pytest.raises(
        SddGitCommandTimeout,
        match="exceeded streaming ceiling 0.05s",
    ):
        run_sdd_git(
            ["push", "origin", "HEAD"],
            cwd=tmp_path,
            op="test.push",
            timeout=0.2,
            check=True,
            capture_output=True,
            text=True,
        )


def _descendant_pipe_command(tmp_path: Path) -> tuple[list[str], Path]:
    child = tmp_path / "pipe-holder.py"
    child.write_text(
        "import os, signal, sys, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "open(sys.argv[1], 'w').write(str(os.getpid()))\n"
        "time.sleep(3)\n",
    )
    parent = tmp_path / "git-wrapper.py"
    parent.write_text(
        "import subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
        "print(child.pid, flush=True)\n"
        "sys.stderr.write('Receiving objects: 1\\r')\n"
        "sys.stderr.flush()\n"
        "time.sleep(30)\n",
    )
    pid_file = tmp_path / "descendant.pid"
    return [sys.executable, str(parent), str(child), str(pid_file)], pid_file


def _process_is_running(pid: int) -> bool:
    proc_stat = Path(f"/proc/{pid}/stat")
    if proc_stat.exists():
        try:
            state = proc_stat.read_text().split(") ", 1)[1][0]
        except (OSError, IndexError):
            return False
        return state != "Z"
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _assert_process_stopped(pid: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and _process_is_running(pid):
        time.sleep(0.02)  # sase-test-wait: poll for descendant exit after group kill
    assert not _process_is_running(pid), f"descendant process {pid} is still running"


@pytest.mark.skipif(os.name != "posix", reason="process group cleanup requires POSIX")
@pytest.mark.parametrize("external_drain_alarm", [False, True])
def test_interruption_kills_process_group_with_pipe_holding_descendant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    external_drain_alarm: bool,
) -> None:
    command, pid_file = _descendant_pipe_command(tmp_path)
    monkeypatch.setenv("SASE_SDD_GIT_NETWORK_TRANSFER_CEILING", "5")
    monkeypatch.setattr("sase.sdd._git_runner.sdd_git_command", lambda _args: command)

    def run_transfer() -> None:
        run_sdd_git(
            ["fetch", "origin"],
            cwd=tmp_path,
            op="test.fetch_with_descendant",
            timeout=0.05 if not external_drain_alarm else 5.0,
            check=True,
            capture_output=True,
            text=True,
        )

    try:
        started = time.monotonic()
        if external_drain_alarm:
            with pytest.raises(PublicationDrainTimedOut):
                with _bounded_publication_drain(0.5):
                    run_transfer()
        else:
            with pytest.raises(SddGitCommandTimeout):
                run_transfer()
        descendant_pid = int(pid_file.read_text())
        _assert_process_stopped(descendant_pid)
        assert time.monotonic() - started < 2.5
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
