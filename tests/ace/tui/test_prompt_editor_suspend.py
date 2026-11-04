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
        self.notifications: list[tuple[str, str]] = []
        self._prompt_context = SimpleNamespace(project_name="demo")

    @contextmanager
    def suspend(self) -> Iterator[None]:
        yield

    def query(self, selector: Any) -> list[object]:
        del selector
        return []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))


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
    ):
        assert app._open_editor_for_agent_prompt("initial") is None

    assert app.active_during_editor == [True]
    assert app._prompt_editor_suspended is False
    assert app._prompt_input_active() is False


def test_prompt_editor_stashes_changed_draft_on_nonzero_exit(
    tmp_path: Path,
) -> None:
    app = _EditorActivityApp(tmp_path)
    stored: list[Any] = []

    def fail_after_edit(cmd: list[str], *, check: bool = False) -> object:
        del check
        Path(cmd[-1]).write_text("recovered prompt", encoding="utf-8")
        return SimpleNamespace(returncode=1)

    with (
        patch("sase.core.paths.get_sase_managed_tmpdir", return_value=tmp_path),
        patch(
            "sase.ace.tui.actions.agent_workflow._editor.resolve_editor",
            return_value=SimpleNamespace(argv=["editor"], command_name="editor"),
        ),
        patch("subprocess.run", fail_after_edit),
        patch(
            "sase.core.paths.prompt_stash_path", return_value=tmp_path / "stash.jsonl"
        ),
        patch(
            "sase.core.prompt_stash_facade.append_prompt_stash",
            side_effect=lambda _path, entry: stored.append(entry),
        ),
    ):
        assert app._open_editor_for_agent_prompt("initial") is None

    assert len(stored) == 1
    assert stored[0].text == "recovered prompt"
    assert stored[0].project == "demo"
    assert stored[0].source == "editor_recovered"
    kept = list(tmp_path.glob("sase_ace_prompt_*.md"))
    assert len(kept) == 1
    assert str(kept[0]) in app.notifications[0][0]
    assert stored[0].id in app.notifications[0][0]


def test_prompt_editor_removes_unchanged_draft_on_nonzero_exit(tmp_path: Path) -> None:
    app = _EditorActivityApp(tmp_path)

    def fail_unchanged(cmd: list[str], *, check: bool = False) -> object:
        del cmd, check
        return SimpleNamespace(returncode=1)

    with (
        patch("sase.core.paths.get_sase_managed_tmpdir", return_value=tmp_path),
        patch(
            "sase.ace.tui.actions.agent_workflow._editor.resolve_editor",
            return_value=SimpleNamespace(argv=["editor"], command_name="editor"),
        ),
        patch("subprocess.run", fail_unchanged),
        patch("sase.core.prompt_stash_facade.append_prompt_stash") as append,
    ):
        assert app._open_editor_for_agent_prompt("initial") is None

    append.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_prompt_editor_keeps_file_when_read_fails(tmp_path: Path) -> None:
    app = _EditorActivityApp(tmp_path)

    def fail_after_edit(cmd: list[str], *, check: bool = False) -> object:
        del check
        Path(cmd[-1]).write_text("changed", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    with (
        patch("sase.core.paths.get_sase_managed_tmpdir", return_value=tmp_path),
        patch(
            "sase.ace.tui.actions.agent_workflow._editor.resolve_editor",
            return_value=SimpleNamespace(argv=["editor"], command_name="editor"),
        ),
        patch("subprocess.run", fail_after_edit),
        patch(
            "sase.ace.tui.actions.agent_workflow._editor._read_editor_file",
            return_value=None,
        ),
    ):
        assert app._open_editor_for_agent_prompt("initial") is None

    kept = list(tmp_path.glob("sase_ace_prompt_*.md"))
    assert len(kept) == 1
    assert str(kept[0]) in app.notifications[0][0]


def test_workflow_editor_keeps_changed_draft_on_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _EditorActivityApp(tmp_path)

    def fail_after_edit(cmd: list[str], *, check: bool = False) -> object:
        del check
        Path(cmd[-1]).write_text("steps: []\n", encoding="utf-8")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda _name: tmp_path
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._editor.resolve_editor",
        lambda: SimpleNamespace(argv=["editor"], command_name="editor"),
    )
    monkeypatch.setattr("subprocess.run", fail_after_edit)
    monkeypatch.setattr("sase.core.time.generate_timestamp", lambda: "20261104_000000")
    monkeypatch.setattr(
        "sase.macro.loader.get_sase_package_macros_dir", lambda: tmp_path
    )

    assert app._open_workflow_yaml_editor() is None
    kept = list(tmp_path.glob("sase_ace_workflow_*.yml"))
    assert len(kept) == 1
    assert kept[0].read_text(encoding="utf-8") == "steps: []\n"
    assert str(kept[0]) in app.notifications[0][0]


def test_workflow_editor_removes_unchanged_draft_on_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _EditorActivityApp(tmp_path)

    def fail_unchanged(cmd: list[str], *, check: bool = False) -> object:
        del cmd, check
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda _name: tmp_path
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._editor.resolve_editor",
        lambda: SimpleNamespace(argv=["editor"], command_name="editor"),
    )
    monkeypatch.setattr("subprocess.run", fail_unchanged)
    monkeypatch.setattr("sase.core.time.generate_timestamp", lambda: "20261104_000000")
    monkeypatch.setattr(
        "sase.macro.loader.get_sase_package_macros_dir", lambda: tmp_path
    )

    assert app._open_workflow_yaml_editor() is None
    assert list(tmp_path.glob("sase_ace_workflow_*.yml")) == []
    assert app.notifications == []


def test_workflow_editor_keeps_file_when_read_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _EditorActivityApp(tmp_path)

    def successful_editor(cmd: list[str], *, check: bool = False) -> object:
        del check
        Path(cmd[-1]).write_text("changed", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda _name: tmp_path
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._editor.resolve_editor",
        lambda: SimpleNamespace(argv=["editor"], command_name="editor"),
    )
    monkeypatch.setattr("subprocess.run", successful_editor)
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._editor._read_editor_file",
        lambda _path: None,
    )
    monkeypatch.setattr("sase.core.time.generate_timestamp", lambda: "20261104_000000")
    monkeypatch.setattr(
        "sase.macro.loader.get_sase_package_macros_dir", lambda: tmp_path
    )

    assert app._open_workflow_yaml_editor() is None
    kept = list(tmp_path.glob("sase_ace_workflow_*.yml"))
    assert len(kept) == 1
    assert str(kept[0]) in app.notifications[0][0]


def test_workflow_editor_saves_successful_edit_and_removes_scratch_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _EditorActivityApp(tmp_path)
    macros_dir = tmp_path / "saved"
    macros_dir.mkdir()

    def successful_editor(cmd: list[str], *, check: bool = False) -> object:
        del check
        Path(cmd[-1]).write_text("steps: []\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(
        "sase.core.paths.get_sase_managed_tmpdir", lambda _name: tmp_path
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._editor.resolve_editor",
        lambda: SimpleNamespace(argv=["editor"], command_name="editor"),
    )
    monkeypatch.setattr("subprocess.run", successful_editor)
    monkeypatch.setattr("sase.core.time.generate_timestamp", lambda: "20261104_000000")
    monkeypatch.setattr(
        "sase.macro.loader.get_sase_package_macros_dir", lambda: tmp_path
    )
    monkeypatch.setattr(
        "sase.content_layout.resolve_home_layout",
        lambda: SimpleNamespace(macros=SimpleNamespace(write_path=macros_dir)),
    )

    result = app._open_workflow_yaml_editor()
    assert result == (
        "adhoc_20261104_000000",
        str(macros_dir / "adhoc_20261104_000000.yml"),
    )
    assert Path(result[1]).read_text(encoding="utf-8") == "steps: []\n"
    assert list(tmp_path.glob("sase_ace_workflow_*.yml")) == []
