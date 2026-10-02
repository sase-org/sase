"""Import-cost regression test for ``sase.ace.tui.util.pane_grid``.

The PaneGrid model is stdlib only: importing it must not pull in Textual,
Rich, the ACE widget/action stack, or the pager (epic ``sase-1eu`` landing
fix; the pager already imports ``sase.ace.tui.util`` on its cold path).
"""

from __future__ import annotations

import subprocess
import sys


def test_pane_grid_import_avoids_tui_stack() -> None:
    """Importing the PaneGrid model stays off the TUI stack."""
    probe = (
        "import sys;"
        "import sase.ace.tui.util.pane_grid;"
        "heavy = [name for name in sys.modules"
        " if name in ('textual', 'rich', 'sase.pager')"
        " or name.startswith(('textual.', 'rich.', 'sase.pager.',"
        " 'sase.ace.tui.widgets', 'sase.ace.tui.actions'))];"
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
        f"pane_grid import loaded TUI modules: {proc.stdout.strip()}"
    )
