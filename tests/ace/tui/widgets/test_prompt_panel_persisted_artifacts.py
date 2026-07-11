"""Tests for the ARTIFACTS section's handling of persisted default artifacts.

Covers two cases the auto-persist feature must handle correctly:

* Persisted artifacts (absolute paths under ``~/.sase/artifacts``) display as
  workspace-relative when the original ``source_path`` is known.
* Indexed artifacts whose ``path`` no longer exists render with a ``(missing)``
  suffix instead of silently breaking.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets.prompt_panel._agent_artifacts import (
    AgentArtifactPath,
    agent_artifact_paths,
    append_agent_artifacts_section,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.core.agent_artifact_facade import store_default_agent_artifact


class _StubAgent:
    def __init__(
        self,
        artifacts_dir: str,
        *,
        workspace_dir: str | None = None,
    ) -> None:
        self._artifacts_dir = artifacts_dir
        self.workspace_dir = workspace_dir
        self.followup_agents: list[_StubAgent] = []

    def get_artifacts_dir(self) -> str:
        return self._artifacts_dir


def _make_agent_dir(home: Path, timestamp: str) -> Path:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / timestamp
    )
    artifacts_dir.mkdir(parents=True)
    return artifacts_dir


def test_persisted_artifact_displays_workspace_relative_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    artifacts_dir = _make_agent_dir(home, "20260511120000")
    workspace = tmp_path / "sase_42"
    image = workspace / "sdd" / "research" / "diagram.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")

    stored = store_default_agent_artifact(
        image,
        artifacts_dir,
        workspace_dir=str(workspace),
    )
    assert stored is not None
    (artifacts_dir / "done.json").write_text(
        json.dumps(
            {
                "workspace_dir": str(workspace),
                "default_artifacts_persisted": True,
            }
        ),
        encoding="utf-8",
    )

    agent = _StubAgent(str(artifacts_dir), workspace_dir=str(workspace))
    [entry] = agent_artifact_paths(agent)  # type: ignore[arg-type]

    assert entry.display_path == "sdd/research/diagram.png"
    assert entry.actual_path == str(Path(stored.path).resolve(strict=False))
    assert entry.exists is True


def test_missing_persisted_artifact_renders_with_missing_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    artifacts_dir = _make_agent_dir(home, "20260511121000")
    workspace = tmp_path / "sase_42"
    image = workspace / "sdd" / "research" / "diagram.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"png")

    stored = store_default_agent_artifact(
        image,
        artifacts_dir,
        workspace_dir=str(workspace),
    )
    assert stored is not None
    (artifacts_dir / "done.json").write_text(
        json.dumps(
            {
                "workspace_dir": str(workspace),
                "default_artifacts_persisted": True,
            }
        ),
        encoding="utf-8",
    )

    # Workspace AND global store file both gone — simulates fully missing data.
    shutil.rmtree(workspace)
    Path(stored.path).unlink()

    agent = _StubAgent(str(artifacts_dir), workspace_dir=str(workspace))
    [entry] = agent_artifact_paths(agent)  # type: ignore[arg-type]

    assert entry.exists is False

    text = Text()
    append_agent_artifacts_section(
        text,
        artifact_paths=agent_artifact_paths(agent),  # type: ignore[arg-type]
    )
    rendered = text.plain
    assert "(missing)" in rendered
    assert "diagram.png" in rendered
    assert "▨" in rendered
    icon_offset = rendered.index("▨")
    assert any(
        span.start <= icon_offset < span.end and span.style == "dim bold #5FD7AF"
        for span in text.spans
    )


def test_persisted_artifact_paths_retain_authoritative_view_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home / ".sase"))

    artifacts_dir = _make_agent_dir(home, "20260511122000")
    workspace = tmp_path / "sase_42"
    workspace.mkdir()
    artifacts = {
        "picture.png": None,
        "demo.mp4": "file",
        "notes.md": "plan",
        "report.pdf": "file",
        "results.csv": "file",
    }
    for filename, kind in artifacts.items():
        source = workspace / filename
        source.write_bytes(b"artifact")
        assert (
            store_default_agent_artifact(
                source,
                artifacts_dir,
                kind=kind,
                workspace_dir=str(workspace),
            )
            is not None
        )

    agent = _StubAgent(str(artifacts_dir), workspace_dir=str(workspace))
    entries = agent_artifact_paths(agent)  # type: ignore[arg-type]

    assert {entry.display_path: entry.view_mode for entry in entries} == {
        "picture.png": "image",
        "demo.mp4": "video",
        "notes.md": "markdown",
        "report.pdf": "pdf",
        "results.csv": "text",
    }


def test_artifact_section_renders_type_icons_styles_and_single_cell_alignment() -> None:
    paths = [
        AgentArtifactPath("picture.png", "/tmp/picture.png", view_mode="image"),
        AgentArtifactPath("demo.mp4", "/tmp/demo.mp4", view_mode="video"),
        AgentArtifactPath("notes.md", "/tmp/notes.md", view_mode="markdown"),
        AgentArtifactPath("report.pdf", "/tmp/report.pdf", view_mode="pdf"),
        AgentArtifactPath("results.csv", "/tmp/results.csv", view_mode="text"),
    ]
    hint_state = HeaderHintState(1, {}, None, {})
    text = Text()

    append_agent_artifacts_section(
        text,
        artifact_paths=paths,
        hint_state=hint_state,
    )

    expected_icons = (
        ("▨", "bold #5FD7AF"),
        ("▶", "bold #FF875F"),
        ("▤", "bold #D7D7AF"),
        ("▤", "bold #D7D7AF"),
        ("•", "bold #FFD787"),
    )
    lines = text.plain.splitlines()[1:]
    assert len(lines) == len(expected_icons)
    for line, (icon, style) in zip(lines, expected_icons, strict=True):
        assert line.startswith(f"  {icon} [")
        assert cell_len(line.split("[", maxsplit=1)[0]) == 4
        icon_offset = text.plain.index(line) + 2
        assert any(
            span.start <= icon_offset < span.end and span.style == style
            for span in text.spans
        )

    assert hint_state.hint_mappings == {
        index: path.actual_path for index, path in enumerate(paths, start=1)
    }
