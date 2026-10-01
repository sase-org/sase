"""Import-cost regression test for ``sase.memory.history``.

The package ``__init__`` must stay slim: importing any history CLI submodule
must not pull in the pager/TUI stack (epic ``sase-1dr`` landing fix).
"""

from __future__ import annotations

import subprocess
import sys


def test_cli_history_import_avoids_pager_stack() -> None:
    """Importing the history CLI stays off the pager/TUI stack."""
    probe = (
        "import sys;"
        "import sase.memory.history.cli_history;"
        "heavy = [name for name in sys.modules"
        " if name in ('sase.pager', 'sase.pager.app', 'textual.app')"
        " or name.startswith(('sase.pager.', 'textual.'))];"
        "print(','.join(sorted(heavy)));"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip() == "", (
        f"history CLI import loaded pager/TUI modules: {proc.stdout.strip()}"
    )
