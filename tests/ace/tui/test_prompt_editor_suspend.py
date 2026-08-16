"""Prompt editor suspend state used by prompt-input activity gates."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.actions._event_base import EventHandlersBase
from sase.ace.tui.actions.agent_workflow._editor import EditorMixin
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar


class _EditorActivityApp(EventHandlersBase, EditorMixin):
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self._prompt_editor_suspended = False
        self.active_during_editor: list[bool] = []

    @contextmanager
    def suspend(self) -> Iterator[None]:
        yield

    def query(self, selector: Any) -> list[object]:
        del selector
        return []


def test_prompt_editor_suspend_marks_prompt_input_active(tmp_path: Path) -> None:
    app = _EditorActivityApp(tmp_path)

    def run_editor(cmd: list[str], *, check: bool = False) -> object:
        del check
        app.active_during_editor.append(app._prompt_input_active())
        Path(cmd[-1]).write_text("edited prompt", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    with (
        patch("sase.core.paths.get_sase_managed_tmpdir", return_value=tmp_path),
        patch(
            "sase.ace.tui.actions.agent_workflow._editor.resolve_editor",
            return_value=SimpleNamespace(argv=["editor"], command_name="editor"),
        ),
        patch("subprocess.run", run_editor),
    ):
        result = app._open_editor_for_agent_prompt("initial")

    assert result == "edited prompt"
    assert app.active_during_editor == [True]
    assert app._prompt_editor_suspended is False
    assert app._prompt_input_active() is False


def test_prompt_editor_suspend_flag_clears_when_editor_raises(tmp_path: Path) -> None:
    app = _EditorActivityApp(tmp_path)

    def fail_editor(_cmd: list[str], *, check: bool = False) -> object:
        del check
        app.active_during_editor.append(app._prompt_input_active())
        raise RuntimeError("editor crashed")

    with (
        patch("sase.core.paths.get_sase_managed_tmpdir", return_value=tmp_path),
        patch(
            "sase.ace.tui.actions.agent_workflow._editor.resolve_editor",
            return_value=SimpleNamespace(argv=["editor"], command_name="editor"),
        ),
        patch("subprocess.run", fail_editor),
        pytest.raises(RuntimeError, match="editor crashed"),
    ):
        app._open_editor_for_agent_prompt("initial")

    assert app.active_during_editor == [True]
    assert app._prompt_editor_suspended is False
    assert app._prompt_input_active() is False
