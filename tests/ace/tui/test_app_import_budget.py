"""Import-budget guard for the TUI startup-critical app module."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import Any

_MAX_ELAPSED_SECONDS = 5.0
_MAX_MODULE_COUNT = 3290


def _measure_tui_app_import() -> dict[str, Any]:
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
    assert payload["module_count"] < _MAX_MODULE_COUNT
    return payload


def test_tui_app_import_stays_under_startup_budget() -> None:
    """Importing the app should not pull known heavy deferred profile edges."""

    last_elapsed = 0.0
    last_count = 0
    for _ in range(3):
        payload = _measure_tui_app_import()
        last_elapsed = float(payload["elapsed_seconds"])
        last_count = int(payload["module_count"])
        if last_elapsed < _MAX_ELAPSED_SECONDS:
            return

    raise AssertionError(
        f"TUI app import stayed over the {_MAX_ELAPSED_SECONDS}s startup budget "
        f"after 3 attempts (elapsed={last_elapsed!r}, module_count={last_count!r})"
    )
