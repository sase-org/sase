"""CLI-import guarantee for Textual-free artifact target/index modules."""

from __future__ import annotations

import subprocess
import sys


def test_core_relation_modules_import_without_textual() -> None:
    script = (
        "import sys\n"
        "assert 'textual' not in sys.modules\n"
        "import sase.core.artifact_entry_target\n"
        "import sase.core.artifact_relations\n"
        "assert 'textual' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
