"""Command grammar and write-hint policy-I/O tests."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from textual.widgets import Static


@asynccontextmanager
async def _grammar_panel(
    grammar: Any, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[tuple[Any, Any]]:
    """Open the panel with the real in-process grammar behind the resolver."""
    from unittest.mock import patch as mock_patch

    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line import screen as screen_module
    from sase.ace.tui.command_line.screen import CommandLineScreen

    monkeypatch.setattr(screen_module, "read_command_line_store_rows", lambda: [])
    with (
        mock_patch.object(AceApp, "_load_agents"),
        mock_patch.object(AceApp, "_load_axe_status"),
    ):
        async with AcePage(query="test_feature", patches=[make_patch()]) as page:
            page.app._command_line_grammar = grammar
            page.app.action_open_command_line()
            await page.expect_modal("CommandLineScreen")
            screen = page.app.screen
            assert isinstance(screen, CommandLineScreen)
            await page.pause()
            await page.pause()
            yield page, screen


@pytest.fixture(scope="module")
def grammar_handle() -> Any:
    """Return an in-process ``CommandLineGrammar`` (no spec subprocess)."""
    try:
        from sase.completion.build import build_spec
        from sase.completion.command_line_grammar import CommandLineGrammar

        return CommandLineGrammar.from_spec_json(json.dumps(build_spec().to_json()))
    except AttributeError:
        pytest.skip("installed sase_core_rs wheel predates CommandLineGrammar")


async def test_mounted_panel_shows_writes_chip(
    grammar_handle: Any,
    history_file: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mounted panel shows the ``writes`` chip for writers (not just the spec)."""
    from sase.ace.tui.command_line.input import CommandLineInput

    async with _grammar_panel(grammar_handle, monkeypatch) as (page, screen):
        for line in ("tool stop", "plan approve"):
            widget = screen.query_one(CommandLineInput)
            widget.set_line(line)
            await page.pause()
            hint = str(screen.query_one("#command-line-hint-row", Static).render())
            assert "⚠ writes" in hint, line
        screen.transcript.stop_tail_task()
