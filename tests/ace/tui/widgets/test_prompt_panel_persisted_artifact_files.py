"""Tests for the ARTIFACTS lane's handling of persisted default artifacts.

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

from sase.ace.tui.widgets.prompt_panel._artifact_files import (
    ArtifactFilePath,
    artifact_file_paths,
    append_artifact_file_paths,
)
from sase.ace.tui.widgets.prompt_panel._agent_context_common import (
    COLOR_ARTIFACTS_SUBHEADER,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import HeaderHintState
from sase.core.artifact_file_facade import store_default_artifact_file


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

    stored = store_default_artifact_file(
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
    [entry] = artifact_file_paths(agent)  # type: ignore[arg-type]

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

    stored = store_default_artifact_file(
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
    [entry] = artifact_file_paths(agent)  # type: ignore[arg-type]

    assert entry.exists is False

    text = Text()
    append_artifact_file_paths(
        text,
        artifact_file_paths=artifact_file_paths(agent),  # type: ignore[arg-type]
    )
    rendered = text.plain
    assert "(missing)" in rendered
    assert "diagram.png" in rendered
    assert "▨" in rendered
    icon_offset = rendered.index("▨")
    assert any(
        span.start <= icon_offset < span.end
        and span.style == f"dim {COLOR_ARTIFACTS_SUBHEADER}"
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
            store_default_artifact_file(
                source,
                artifacts_dir,
                kind=kind,
                workspace_dir=str(workspace),
            )
            is not None
        )

    agent = _StubAgent(str(artifacts_dir), workspace_dir=str(workspace))
    entries = artifact_file_paths(agent)  # type: ignore[arg-type]

    assert {entry.display_path: entry.view_mode for entry in entries} == {
        "picture.png": "image",
        "demo.mp4": "video",
        "notes.md": "markdown",
        "report.pdf": "pdf",
        "results.csv": "text",
    }


def test_artifact_rows_render_monochrome_type_icons_with_single_cell_alignment() -> (
    None
):
    paths = [
        ArtifactFilePath("picture.png", "/tmp/picture.png", view_mode="image"),
        ArtifactFilePath("demo.mp4", "/tmp/demo.mp4", view_mode="video"),
        ArtifactFilePath("notes.md", "/tmp/notes.md", view_mode="markdown"),
        ArtifactFilePath("report.pdf", "/tmp/report.pdf", view_mode="pdf"),
        ArtifactFilePath("results.csv", "/tmp/results.csv", view_mode="text"),
    ]
    hint_state = HeaderHintState(1, {}, None, {})
    text = Text()

    append_artifact_file_paths(
        text,
        artifact_file_paths=paths,
        hint_state=hint_state,
        indent="  ",
    )

    expected_icons = ("▨", "▶", "▤", "▤", "•")
    lines = text.plain.splitlines()
    assert len(lines) == len(expected_icons)
    for line, icon in zip(lines, expected_icons, strict=True):
        assert line.startswith(f"  {icon} [")
        assert cell_len(line.split("[", maxsplit=1)[0]) == 4
        icon_offset = text.plain.index(line) + 2
        assert any(
            span.start <= icon_offset < span.end
            and span.style == COLOR_ARTIFACTS_SUBHEADER
            for span in text.spans
        )

    assert hint_state.hint_mappings == {
        index: path.actual_path for index, path in enumerate(paths, start=1)
    }
