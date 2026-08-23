"""End-to-end writer-lock coverage for approved-epic launch."""

from __future__ import annotations

import json
import os
import select
import shlex
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.bead.epic_launch import build_epic_launch_argv, start_epic_launch_monitor
from sase.dev_update.code_swap_lock import code_swap_writer_lock, guarded_exec_argv

from .epic_launch_test_helpers import fake_lease


def test_host_epic_launch_waits_out_writer_then_runs_bead_work_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tmp_path / "approved.md"
    plan.write_text("# epic\n", encoding="utf-8")
    marker = tmp_path / "created.json"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_sase = fake_bin / "sase"
    fake_sase.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "import json, pathlib, sys",
                f"path = pathlib.Path({str(marker)!r})",
                "path.write_text(json.dumps(sys.argv))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_sase.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")

    logical = build_epic_launch_argv(plan, artifacts_dir=tmp_path / "artifacts")
    execution = guarded_exec_argv(logical)
    monitor = SimpleNamespace(
        monitor_id="m7k2xyz",
        monitor_state="running",
        command=shlex.join(logical),
    )
    lease = fake_lease(tmp_path)
    captured: dict[str, object] = {}

    def fake_start_monitor(request: object) -> object:
        captured["request"] = request
        proc = subprocess.Popen(
            list(request.execution_argv),  # type: ignore[attr-defined]
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        captured["proc"] = proc
        return monitor

    with (
        patch("sase.procs.procs_dir", return_value=tmp_path / "tasks"),
        patch("sase.procs.read_procs", return_value=[]),
        patch(
            "sase.workspace_provider.lease.acquire_operational_lease",
            return_value=lease,
        ),
        patch("sase.workspace_provider.lease.release_operational_lease"),
        patch("sase.monitor.start.start_monitor", side_effect=fake_start_monitor),
        code_swap_writer_lock() as writer,
    ):
        assert writer.acquired is True
        submitted = start_epic_launch_monitor(
            plan,
            project="sase",
            host_action_data={"agent_name": "planner"},
            artifacts_dir=tmp_path / "artifacts",
        )
        assert submitted is monitor
        proc = captured["proc"]
        assert isinstance(proc, subprocess.Popen)
        try:
            line = _readline_until(
                proc, "waiting for the source-tree swap to finish", timeout=5.0
            )
            assert line is not None
            assert proc.poll() is None
            assert not marker.exists()
            assert plan.read_text(encoding="utf-8") == "# epic\n"
        except BaseException:
            proc.kill()
            proc.wait(timeout=5)
            raise

    assert proc.wait(timeout=10) == 0
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload[0].endswith("sase")
    assert payload[1:4] == ["bead", "work", str(plan)]
    request = captured["request"]
    assert request.command == shlex.join(logical)  # type: ignore[attr-defined]
    assert list(request.execution_argv) == execution  # type: ignore[attr-defined]


def _readline_until(
    proc: subprocess.Popen[str], needle: str, *, timeout: float
) -> str | None:
    stream = proc.stdout
    if stream is None:
        return None
    deadline = time.monotonic() + timeout
    buf = ""
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        ready, _, _ = select.select([stream], [], [], max(0.0, remaining))
        if not ready:
            continue
        chunk = stream.readline()
        if chunk == "":
            return None
        buf += chunk
        if needle in buf:
            return buf
    return None
