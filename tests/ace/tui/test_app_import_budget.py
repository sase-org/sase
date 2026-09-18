"""Import-budget guard for the TUI startup-critical app module."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap


def test_tui_app_import_stays_under_startup_budget() -> None:
    """Importing the app should not pull known heavy deferred profile edges."""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import importlib
                import json
                import sys
                import time

                started = time.perf_counter()
                importlib.import_module("sase.ace.tui.app")
                elapsed = time.perf_counter() - started

                print(json.dumps({
                    "elapsed_seconds": elapsed,
                    "module_count": len(sys.modules),
                    "deferred_modules": [
                        name for name in (
                            "sase.agent.multi_prompt",
                            "sase.agent.multi_prompt_launcher",
                        )
                        if name in sys.modules
                    ],
                }))
                """
            ),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr + result.stdout

    payload = json.loads(result.stdout)
    assert payload["deferred_modules"] == []
    assert payload["module_count"] < 3290
    assert payload["elapsed_seconds"] < 5.0
