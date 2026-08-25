"""Launch-admission stop behavior."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from sase.agent.launch_request import stop_launch_admission


def test_stop_escalates_term_then_exits(tmp_path: Path) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    root = tmp_path / "launch" / "launch_admission"
    root.mkdir(parents=True)
    (root / "sidecar.json").write_text(json.dumps({"pid": child.pid}), encoding="utf-8")
    try:
        stop_launch_admission(tmp_path / "launch")
        child.wait(timeout=8)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)
    assert child.returncode is not None


def test_stop_missing_coordinator_is_noop(tmp_path: Path) -> None:
    stop_launch_admission(tmp_path / "missing")
