"""The Archive column code never loads on the Inbox-only startup path."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

_ARCHIVE_ONLY_MODULES = (
    "sase.ace.tui.actions.agents._archive_column",
    "sase.ace.tui.actions.agents._archive_column_nav",
    "sase.ace.tui.actions.agents._archive_controller",
    "sase.ace.tui.actions.agents._archive_controller_build",
    "sase.ace.tui.models.agent_archive_controller",
    "sase.ace.tui.models.agent_archive_list",
    "sase.ace.tui.widgets.agents_archive",
)


def test_importing_the_app_loads_no_archive_column_modules() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import importlib, json, sys
                importlib.import_module("sase.ace.tui.app")
                print(json.dumps([
                    name for name in {_ARCHIVE_ONLY_MODULES!r} if name in sys.modules
                ]))
                """
            ),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == []
