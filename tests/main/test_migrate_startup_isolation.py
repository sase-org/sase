"""Startup isolation tests for the temporary migration kit."""

from __future__ import annotations

import subprocess
import sys


def test_import_sase_does_not_import_migration_kit() -> None:
    script = (
        "import sys\n"
        "import sase\n"
        "print('MODULE_PRESENT=' + str('sase.migration_kit' in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "MODULE_PRESENT=False" in result.stdout


def test_sase_help_does_not_import_migration_kit() -> None:
    script = (
        "import runpy, sys\n"
        "sys.argv = ['sase', '--help']\n"
        "try:\n"
        "    runpy.run_module('sase', run_name='__main__')\n"
        "except SystemExit:\n"
        "    pass\n"
        "print('MODULE_PRESENT=' + str('sase.migration_kit' in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "MODULE_PRESENT=False" in result.stdout
