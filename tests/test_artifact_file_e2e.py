from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.agents._panels import AgentPanelsMixin
from sase.ace.tui.graphics import ArtifactFileViewerResult
from sase.core.artifact_file_facade import ArtifactFile, list_artifact_files
from sase.main.artifact_file_handler import handle_artifact_file_command


def _agent_dir(home: Path, timestamp: str) -> Path:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / timestamp
    )
    artifacts_dir.mkdir(parents=True)
    return artifacts_dir


def _write_json(path: Path, data: dict[str, object]) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_done_agent(
    home: Path,
    timestamp: str,
    *,
    chat_name: str,
    plan: Path | None = None,
    image: Path | None = None,
) -> Path:
    artifacts_dir = _agent_dir(home, timestamp)
    chat = _write_text(home / ".sase" / "chats" / chat_name, "# Chat\n")
    done: dict[str, object] = {
        "outcome": "completed",
        "name": chat_name.removesuffix(".md"),
        "response_path": str(chat),
    }
    if plan is not None:
        done["plan_path"] = str(plan)
    if image is not None:
        done["image_paths"] = [str(image)]
    _write_json(artifacts_dir / "done.json", done)
    return artifacts_dir


def _artifact_create_args(
    path: Path, *, label: str | None = None
) -> argparse.Namespace:
    return argparse.Namespace(
        artifact_file_subcommand="create",
        path=str(path),
        label=label,
        kind=None,
    )


def test_done_artifact_file_fixture_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: home)

    chat_only_dir = _write_done_agent(home, "20260508010101", chat_name="chat-only.md")
    chat_plan_dir = _write_done_agent(
        home,
        "20260508010102",
        chat_name="chat-plan.md",
        plan=_write_text(tmp_path / "plan.md", "# Plan\n"),
    )
    chat_image_dir = _write_done_agent(
        home,
        "20260508010103",
        chat_name="chat-image.md",
        image=_write_text(tmp_path / "image.png", "png"),
    )
    explicit_dir = _write_done_agent(home, "20260508010104", chat_name="explicit.md")
    explicit_source = _write_text(tmp_path / "report.md", "# Report\n")

    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(explicit_dir))
    with pytest.raises(SystemExit) as explicit_exit:
        handle_artifact_file_command(
            _artifact_create_args(explicit_source, label="Report")
        )
    assert explicit_exit.value.code == 0
    assert "id: explicit:" in capsys.readouterr().out

    revived_dir = _write_done_agent(home, "20260508010105", chat_name="revived.md")
    revive_source = _write_text(tmp_path / "revived.txt", "revived artifact\n")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(revived_dir))
    with pytest.raises(SystemExit) as revived_exit:
        handle_artifact_file_command(
            _artifact_create_args(revive_source, label="Revived")
        )
    assert revived_exit.value.code == 0
    capsys.readouterr()
    shutil.rmtree(revived_dir)
    revived_while_dismissed = list_artifact_files(revived_dir)
    revived_dir.mkdir(parents=True)
    _write_json(
        revived_dir / "done.json",
        {
            "outcome": "completed",
            "response_path": str(home / ".sase" / "chats" / "revived.md"),
        },
    )
    revived_after_restore = list_artifact_files(revived_dir)

    assert [
        (artifact.kind, artifact.label)
        for artifact in list_artifact_files(chat_only_dir)
    ] == [("chat", "Chat transcript")]
    assert [
        (artifact.kind, artifact.label)
        for artifact in list_artifact_files(chat_plan_dir)
    ] == [
        ("chat", "Chat transcript"),
        ("plan", "plan.md"),
    ]
    assert [
        (artifact.kind, artifact.label)
        for artifact in list_artifact_files(chat_image_dir)
    ] == [
        ("chat", "Chat transcript"),
        ("image", "image.png"),
    ]
    assert [
        (artifact.kind, artifact.label)
        for artifact in list_artifact_files(explicit_dir)
    ] == [
        ("chat", "Chat transcript"),
        ("markdown", "Report"),
    ]
    assert [
        (artifact.kind, artifact.label) for artifact in revived_while_dismissed
    ] == [("file", "Revived")]
    assert [(artifact.kind, artifact.label) for artifact in revived_after_restore] == [
        ("chat", "Chat transcript"),
        ("file", "Revived"),
    ]


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered = False

    def __enter__(self) -> None:
        self.entered = True

    def __exit__(self, *_args: object) -> None:
        return None


class _ArtifactActionApp(AgentPanelsMixin):
    def __init__(self, agent: object) -> None:
        self.current_tab = "agents"
        self._selected_agent = agent
        self.notify = MagicMock()
        self.agent_list = MagicMock()
        self.pushed: list[tuple[object, object | None]] = []
        self.suspend_recorder = _SuspendRecorder()
        self._agents_with_children = []  # type: ignore[var-annotated]
        self._marked_agents = set()  # type: ignore[var-annotated]

    def _get_selected_agent(self) -> object:
        return self._selected_agent

    def query_one(self, selector: str, *_args: object, **_kwargs: object) -> object:
        if selector == "#agent-list-panel":
            return self.agent_list
        raise AssertionError(selector)

    def push_screen(self, modal: object, callback: object | None = None) -> None:
        self.pushed.append((modal, callback))

    def suspend(self) -> _SuspendRecorder:
        return self.suspend_recorder


def _agent(artifacts_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(status="DONE", get_artifacts_dir=lambda: str(artifacts_dir))


def test_agents_action_uses_panel_for_chat_only_and_multiple_artifact_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    chat_only_dir = _write_done_agent(home, "20260508020101", chat_name="chat-only.md")
    multi_dir = _write_done_agent(
        home,
        "20260508020102",
        chat_name="multi.md",
        plan=_write_text(tmp_path / "multi-plan.md", "# Plan\n"),
    )
    opened: list[ArtifactFile] = []

    def fake_viewer(artifact: ArtifactFile) -> ArtifactFileViewerResult:
        opened.append(artifact)
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file", fake_viewer
    )

    single_app = _ArtifactActionApp(_agent(chat_only_dir))
    single_app.action_open_artifact_files()

    assert single_app.suspend_recorder.entered is False
    assert opened == []
    assert len(single_app.pushed) == 1
    single_modal, single_callback = single_app.pushed[0]
    assert single_modal.__class__.__name__ == "ArtifactFileSelectionModal"
    assert single_callback is not None

    chat_artifact = list_artifact_files(chat_only_dir)[0]
    cast(Callable[[ArtifactFile], None], single_callback)(chat_artifact)

    assert single_app.suspend_recorder.entered is True
    assert [(artifact.kind, artifact.label) for artifact in opened] == [
        ("chat", "Chat transcript")
    ]
    single_app.notify.assert_not_called()

    multi_app = _ArtifactActionApp(_agent(multi_dir))
    multi_app.action_open_artifact_files()

    assert len(multi_app.pushed) == 1
    modal, callback = multi_app.pushed[0]
    assert modal.__class__.__name__ == "ArtifactFileSelectionModal"
    assert callback is not None
