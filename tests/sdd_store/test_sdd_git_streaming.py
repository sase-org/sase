from __future__ import annotations

from pathlib import Path
import sys

import pytest

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
    monkeypatch.setattr("sase.sdd._git.sdd_git_command", command)

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
        "sase.sdd._git.sdd_git_command",
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
        "sase.sdd._git.sdd_git_command",
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
