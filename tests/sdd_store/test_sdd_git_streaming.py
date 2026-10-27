from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import time

import pytest

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync import _commit_publication_drain as publication_drain
from sase.sdd._git import SddGitCommandTimeout, run_sdd_git

GH013_SECRET = "SYNTHETIC-REMOTE-SECRET-7f3a9c2e"


def _git_ops_records(path: Path) -> list[dict[str, object]]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _redirect_git_ops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log_path = tmp_path / "tui_git_ops.jsonl"
    monkeypatch.setenv("SASE_TUI_GIT_OPS_PATH", str(log_path))
    monkeypatch.setattr("sase.logs.tui_telemetry.TUI_GIT_OPS_JSONL", str(log_path))
    return log_path


def _fake_git_with_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, exit_code: int
) -> None:
    script = tmp_path / "fake_git.py"
    script.write_text(
        "import sys\n"
        f"sys.stdout.write('shown {GH013_SECRET}\\n')\n"
        "sys.stderr.write("
        f"'remote: error: GH013: Repository rule violations found\\n{GH013_SECRET}\\n'"
        ")\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.sdd._git_runner.sdd_git_command",
        lambda _args: [sys.executable, str(script)],
    )
    monkeypatch.setattr(
        "sase.sdd._git_network._sleep_for_network_retry",
        lambda **_kwargs: False,
    )


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
                with publication_drain._bounded_publication_drain(0.5):
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


def test_agents_push_omits_output_previews_from_git_ops_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git

    log_path = _redirect_git_ops(tmp_path, monkeypatch)
    _fake_git_with_secret(tmp_path, monkeypatch, exit_code=1)
    result = run_git(tmp_path, ["push", "origin", "HEAD"], network=True)

    assert result.returncode == 1
    records = _git_ops_records(log_path)
    assert records
    blob = json.dumps(records)
    assert GH013_SECRET not in blob
    for record in records:
        assert "stdout_preview" not in record
        assert "stderr_preview" not in record
        assert "cmd" in record
        assert "cwd" in record
        assert "status" in record


def test_slow_agents_git_bytes_omits_output_previews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.agents_sync.git import run_git_bytes

    log_path = _redirect_git_ops(tmp_path, monkeypatch)
    monkeypatch.setenv("SASE_SDD_GIT_SLOW_MS", "0.001")
    _fake_git_with_secret(tmp_path, monkeypatch, exit_code=0)
    result = run_git_bytes(tmp_path, ["show", "HEAD:secret.txt"])

    assert result.returncode == 0
    records = _git_ops_records(log_path)
    assert records
    blob = json.dumps(records)
    assert GH013_SECRET not in blob
    for record in records:
        assert "stdout_preview" not in record
        assert "stderr_preview" not in record


def test_non_agents_sdd_git_still_records_output_previews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_path = _redirect_git_ops(tmp_path, monkeypatch)
    monkeypatch.setenv("SASE_SDD_GIT_SLOW_MS", "0.001")
    _fake_git_with_secret(tmp_path, monkeypatch, exit_code=1)
    result = run_sdd_git(
        ["status"],
        cwd=tmp_path,
        op="test.git",
        timeout=5,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    records = _git_ops_records(log_path)
    assert records
    blob = json.dumps(records)
    assert GH013_SECRET in blob
    assert any("stderr_preview" in record for record in records)
