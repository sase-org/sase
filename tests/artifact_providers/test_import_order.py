"""Regression tests for artifact-provider import order.

These must run in a fresh interpreter: once ``sase.config`` is already in
``sys.modules``, an in-process ``import`` can no longer reproduce the cycle.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "sase.artifact_providers",
        "sase.artifact_providers.registry",
        "sase.config.file_hooks",
    ],
)
def test_module_imports_first_from_cold_interpreter(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
