"""Fresh-interpreter import-order guards for the RUNNING-claim modules.

``sase.core.agent_launch_claims`` and the ``sase.running_field`` package import
each other. In-process tests cannot see a cycle like that, because pytest has
usually loaded both modules by the time a test runs. These probes import each
entry point first in a new interpreter, as a job subprocess does.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "sase.core.agent_launch_claims",
        "sase.workspace_provider.inventory",
        "sase.scripts.sase_chop_disk_pressure",
    ],
)
def test_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout
