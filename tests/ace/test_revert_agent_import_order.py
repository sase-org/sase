"""The revert modules import cleanly whichever one a process imports first.

``sase.ace.revert_agent_resolution`` reaches the TUI model package, whose
completed-agent loaders once imported ``agent_is_reverted`` through the
``sase.ace.revert_agent`` facade, and the facade imports the resolution module
back. A process that happened to import the facade first never noticed; one
that imported the resolution module first failed with a partially initialized
module. A sharded contention soak, which imports each worker's test files in a
different order than a whole-suite run, collected two test files that way.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "module",
    [
        "sase.ace.revert_agent_resolution",
        "sase.ace.revert_agent",
        "sase.ace.tui.models",
    ],
)
def test_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stderr
