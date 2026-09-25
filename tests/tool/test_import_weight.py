"""A foreground `sase tool run` must not pay for the provider/xprompt stack."""

from __future__ import annotations

import subprocess
import sys


HEAVY_PREFIXES = ("sase.llm_provider", "sase.xprompt")


def test_tool_modules_do_not_import_the_provider_stack() -> None:
    # `sase tool run -- true` measured ~0.35 s slower than `sase proc list` while
    # observe.py imported git helpers through the `sase.llm_provider` package.
    code = (
        "import sys\n"
        "import sase.tool.executor, sase.tool.query, sase.tool.observe\n"
        f"heavy = sorted(m for m in sys.modules if m.startswith({HEAVY_PREFIXES!r}))\n"
        "print(heavy)\n"
        "sys.exit(1 if heavy else 0)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
