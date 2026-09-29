"""Shared helpers for completion-source tests.

Public helpers used by more than one ``test_completion_sources_*`` module
live here under public names so no new module imports a ``_``-prefixed
name from another new module.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch as mock_patch

import pytest

from sase.history import command_line as history_store


@pytest.fixture
def history_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate the history store to a temp file."""
    path = tmp_path / "command_line_history.json"
    monkeypatch.setattr(history_store, "_history_file_override", path)
    return path


@pytest.fixture(scope="module")
def grammar_handle() -> Any:
    """Return an in-process ``CommandLineGrammar`` (no spec subprocess)."""
    try:
        from sase.completion.build import build_spec
        from sase.completion.command_line_grammar import CommandLineGrammar

        return CommandLineGrammar.from_spec_json(json.dumps(build_spec().to_json()))
    except AttributeError:
        pytest.skip("installed sase_core_rs wheel predates CommandLineGrammar")


@asynccontextmanager
async def panel(grammar: Any) -> AsyncGenerator[tuple[Any, Any]]:
    from sase.ace.testing import AcePage, make_patch
    from sase.ace.tui import AceApp
    from sase.ace.tui.command_line.screen import CommandLineScreen

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
            screen.transcript.stop_tail_task()
            await page.pause()
            yield page, screen


async def type_line(page: Any, screen: Any, line: str) -> Any:
    from sase.ace.tui.command_line.input import CommandLineInput

    widget = screen.query_one(CommandLineInput)
    widget.set_line(line)
    await page.pause()
    return widget


async def await_provider_task(screen: Any) -> None:
    task = screen._provider_task
    assert task is not None
    await asyncio.wait_for(task, timeout=5)


def shown(screen: Any) -> list[str]:
    """The popup rows' display text, in order."""
    return [
        str(item.get("display") or item.get("insert_text") or "").strip()
        for item in screen._popup_state.items
    ]


def stub_provider(monkeypatch: pytest.MonkeyPatch, fetch: Any) -> list[bool]:
    """Route ``candidates_for`` to *fetch*, recording each ``use_disk_cache``."""
    import sase.completion.candidates.providers as providers

    uses_disk_cache: list[bool] = []

    def _candidates_for(
        kind: str,
        prefix: str,
        *,
        project: str | None,
        limit: int,
        use_disk_cache: bool = True,
    ) -> Any:
        uses_disk_cache.append(use_disk_cache)
        return fetch(kind)

    monkeypatch.setattr(providers, "candidates_for", _candidates_for)
    return uses_disk_cache


def pin_cwd(page: Any, screen: Any, cwd: Path) -> None:
    from sase.ace.tui.command_line.context import CommandLineContext
    from sase.ace.tui.command_line.session import command_line_session_for

    command_line_session_for(page.app).cwd_pin = str(cwd)
    screen._working_context = CommandLineContext(
        cwd=str(cwd), project=None, pinned=True
    )
