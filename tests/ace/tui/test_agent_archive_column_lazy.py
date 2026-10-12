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
    "sase.ace.tui.actions.agents._archive_view",
    "sase.ace.tui.models.agent_archive_controller",
    "sase.ace.tui.models.agent_archive_list",
    "sase.ace.tui.models.agent_archive_view",
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


def test_inbox_jk_probe_does_not_load_archive_view() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import importlib, json, sys
                from types import SimpleNamespace

                importlib.import_module("sase.ace.tui.app")
                from sase.ace.tui.actions.agents._display_helpers import (
                    route_archive_key_if_active,
                )

                owner = SimpleNamespace(
                    current_tab="agents",
                    _agents_archive_view=SimpleNamespace(active_view="inbox"),
                )
                assert route_archive_key_if_active(owner, "down") is False
                print(json.dumps([
                    name for name in (
                        "sase.ace.tui.actions.agents._archive_view",
                        "sase.ace.tui.models.agent_archive_view",
                    ) if name in sys.modules
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


def test_archive_column_mixin_module_is_gone() -> None:
    import importlib.util

    assert (
        importlib.util.find_spec("sase.ace.tui.actions.agents._archive_column_mixin")
        is None
    )
