"""Clipboard and path-copy tests for the artifact-file selection modal."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.modals.artifact_files_modal import ArtifactFileSelectionModal
from tests.ace.tui.modals.artifact_files_modal_test_helpers import (
    _TestApp,
    _artifact,
)


async def test_artifact_file_modal_y_copies_highlighted_markdown_contents_and_stays_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_path = tmp_path / "artifact.md"
    artifact_path.write_text("# Title\nbody\n", encoding="utf-8")
    artifacts = [_artifact(1, label="artifact.md", path=str(artifact_path))]
    copied: list[str] = []
    notifications: list[tuple[str, str]] = []
    result: object | None = "sentinel"

    monkeypatch.setattr(
        "sase.ace.tui.modals.artifact_files_modal.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        def notify(message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

        modal = ArtifactFileSelectionModal(artifacts)
        modal.notify = notify  # type: ignore[method-assign]
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("y")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert result == "sentinel"

    assert copied == ["# Title\nbody\n"]
    assert notifications == [("Copied: artifact.md (2 lines)", "information")]


async def test_artifact_file_modal_Y_copies_workspace_relative_path_and_stays_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    artifact_path = workspace / "sdd" / "research" / "202605" / "artifact.md"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("# Title\n", encoding="utf-8")
    artifacts = [
        _artifact(
            1,
            label="artifact.md",
            path=str(artifact_path),
            workspace_dir=str(workspace),
        )
    ]
    copied: list[str] = []
    result: object | None = "sentinel"

    monkeypatch.setattr(
        "sase.ace.tui.modals.artifact_files_modal.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert result == "sentinel"

    assert copied == ["sdd/research/202605/artifact.md"]


async def test_artifact_file_modal_Y_without_workspace_falls_back_to_home_relative_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    artifact_path = home / "work" / "artifact.md"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text("# Title\n", encoding="utf-8")
    artifacts = [_artifact(1, label="artifact.md", path=str(artifact_path))]
    copied: list[str] = []
    result: object | None = "sentinel"

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        "sase.ace.tui.modals.artifact_files_modal.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = ArtifactFileSelectionModal(artifacts)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert result == "sentinel"

    assert copied == ["~/work/artifact.md"]


async def test_artifact_file_modal_copy_uses_pdf_markdown_source_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "docs" / "report.md"
    pdf = tmp_path / "artifacts" / "markdown_pdfs" / "docs__report.md.pdf"
    source.parent.mkdir(parents=True)
    pdf.parent.mkdir(parents=True)
    source.write_text("# Source\n", encoding="utf-8")
    pdf.write_text("generated pdf", encoding="utf-8")
    artifact = _artifact(
        1,
        label="report.md",
        kind="pdf",
        path=str(pdf),
        source_path="docs/report.md",
        workspace_dir=str(workspace),
    )
    copied: list[str] = []

    monkeypatch.setattr(
        "sase.ace.tui.modals.artifact_files_modal.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal([artifact])
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("y")
        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal

    assert copied == ["# Source\n", "docs/report.md"]


async def test_artifact_file_modal_Y_uses_workspace_relative_source_path_for_global_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "report.md"
    stored = tmp_path / ".sase" / "artifacts" / "agents" / "report.md"
    source.parent.mkdir(parents=True)
    stored.parent.mkdir(parents=True)
    source.write_text("# Source\n", encoding="utf-8")
    stored.write_text("# Stored\n", encoding="utf-8")
    artifact = _artifact(
        1,
        label="report.md",
        path=str(stored),
        source_path=str(source),
        workspace_dir=str(workspace),
    )
    copied: list[str] = []

    monkeypatch.setattr(
        "sase.ace.tui.modals.artifact_files_modal.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal([artifact])
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal

    assert copied == ["src/report.md"]


async def test_artifact_file_modal_Y_recovers_workspace_from_agent_meta_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    workspace = tmp_path / "workspace"
    source = workspace / "sdd" / "plans" / "202605" / "plan.md"
    artifacts_dir.mkdir()
    source.parent.mkdir(parents=True)
    source.write_text("# Plan\n", encoding="utf-8")
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(workspace)}),
        encoding="utf-8",
    )
    artifact = _artifact(
        1,
        label="plan.md",
        path="sdd/plans/202605/plan.md",
        agent_artifacts_dir=str(artifacts_dir),
    )
    copied: list[str] = []

    monkeypatch.setattr(
        "sase.ace.tui.modals.artifact_files_modal.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal([artifact])
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal

    assert copied == ["sdd/plans/202605/plan.md"]


async def test_artifact_file_modal_y_recovers_workspace_from_agent_meta_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    workspace = tmp_path / "workspace"
    source = workspace / "sdd" / "plans" / "202605" / "plan.md"
    artifacts_dir.mkdir()
    source.parent.mkdir(parents=True)
    source.write_text("# Plan\n", encoding="utf-8")
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"workspace_dir": str(workspace)}),
        encoding="utf-8",
    )
    artifact = _artifact(
        1,
        label="plan.md",
        path="sdd/plans/202605/plan.md",
        agent_artifacts_dir=str(artifacts_dir),
    )
    copied: list[str] = []

    monkeypatch.setattr(
        "sase.ace.tui.modals.artifact_files_modal.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal([artifact])
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("y")
        await pilot.pause()

        assert pilot.app.screen is modal

    assert copied == ["# Plan\n"]


async def test_artifact_file_modal_y_warns_for_non_markdown_artifact_file_without_copying(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_path = tmp_path / "artifact.txt"
    artifact_path.write_text("not markdown\n", encoding="utf-8")
    artifacts = [
        _artifact(1, label="artifact.txt", path=str(artifact_path), kind="text")
    ]
    copied: list[str] = []
    notifications: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "sase.ace.tui.modals.artifact_files_modal.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:

        def notify(message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

        modal = ArtifactFileSelectionModal(artifacts)
        modal.notify = notify  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("y")
        await pilot.pause()

        assert pilot.app.screen is modal

    assert copied == []
    assert notifications == [
        ("Selected artifact file is not Markdown", "warning"),
    ]
