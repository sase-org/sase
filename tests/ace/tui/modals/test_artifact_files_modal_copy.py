"""Clipboard and path-copy tests for the artifact-file selection modal."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from textual.widgets import OptionList

from sase.ace.tui.modals.artifact_files_modal import ArtifactFileSelectionModal
from sase.ace.tui.modals.copy_as_modal import CopyAsModal
from sase.artifact_cli.references import artifact_file_json_dict
from tests.ace.tui.modals.artifact_files_modal_test_helpers import (
    _TestApp,
    _artifact,
)


async def _drain_clipboard_tasks(app: object) -> None:
    """Wait for tracked copy delivery instead of relying on pump timing."""
    while tasks := tuple(getattr(app, "_pump_free_clipboard_tasks", ())):
        await asyncio.gather(*tasks)
        await asyncio.sleep(0)


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
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
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
        await _drain_clipboard_tasks(pilot.app)

        assert pilot.app.screen is modal
        assert result == "sentinel"

    assert copied == ["# Title\nbody\n"]
    assert notifications == [("Copied artifact.md (2 lines)", "information")]


async def test_artifact_file_modal_Y_anchors_workspace_stored_path_and_stays_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    workspace = home / "workspace"
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
    notifications: list[tuple[str, str]] = []
    result: object | None = "sentinel"

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
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

        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal
        assert result == "sentinel"

    assert copied == ["~/workspace/sdd/research/202605/artifact.md"]
    assert notifications == [
        (
            "Copied stored path: ~/workspace/sdd/research/202605/artifact.md",
            "information",
        )
    ]


async def test_artifact_file_modal_Y_copies_home_relative_stored_path_without_workspace(
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
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
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


async def test_artifact_file_modal_copy_anchors_pdf_markdown_source_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    workspace = home / "workspace"
    source = workspace / "docs" / "report.md"
    pdf = home / "artifacts" / "markdown_pdfs" / "docs__report.md.pdf"
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
    notifications: list[tuple[str, str]] = []

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:

        def notify(message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

        modal = ArtifactFileSelectionModal([artifact])
        modal.notify = notify  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("y")
        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal

    assert copied == ["# Source\n", "~/workspace/docs/report.md"]
    assert notifications[-1] == (
        "Copied source path: ~/workspace/docs/report.md",
        "information",
    )


async def test_artifact_file_modal_Y_prefers_stored_path_over_source_for_global_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    workspace = home / "workspace"
    source = workspace / "src" / "report.md"
    stored = home / ".sase" / "artifacts" / "agents" / "report.md"
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
    notifications: list[tuple[str, str]] = []

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:

        def notify(message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

        modal = ArtifactFileSelectionModal([artifact])
        modal.notify = notify  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal

    assert copied == ["~/.sase/artifacts/agents/report.md"]
    assert notifications == [
        ("Copied stored path: ~/.sase/artifacts/agents/report.md", "information")
    ]


async def test_artifact_file_modal_Y_never_emits_bare_path_for_recycled_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recycled `sase_<N>` workspace must not yield a bare relative path."""
    home = tmp_path / "home"
    workspace = home / "workspaces" / "sase_19"
    stored = home / ".sase" / "artifacts" / "agents" / "report.md"
    stored.parent.mkdir(parents=True)
    stored.write_text("# Stored\n", encoding="utf-8")
    # The workspace was reused, so this source path now names a different file.
    workspace.mkdir(parents=True)
    artifact = _artifact(
        1,
        label="report.md",
        path=str(stored),
        source_path="src/report.md",
        workspace_dir=str(workspace),
    )
    copied: list[str] = []

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal([artifact])
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal

    assert copied == ["~/.sase/artifacts/agents/report.md"]


async def test_artifact_file_modal_Y_warns_when_chosen_source_path_is_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    workspace = home / "workspace"
    pdf = home / "artifacts" / "markdown_pdfs" / "docs__report.md.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_text("generated pdf", encoding="utf-8")
    workspace.mkdir(parents=True)
    artifact = _artifact(
        1,
        label="report.md",
        kind="pdf",
        path=str(pdf),
        source_path="docs/report.md",
        workspace_dir=str(workspace),
    )
    copied: list[str] = []
    notifications: list[tuple[str, str]] = []

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:

        def notify(message: str, *, severity: str = "information") -> None:
            notifications.append((message, severity))

        modal = ArtifactFileSelectionModal([artifact])
        modal.notify = notify  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal

    assert copied == ["~/workspace/docs/report.md"]
    assert notifications == [
        (
            "Copied source path (no longer exists): ~/workspace/docs/report.md",
            "information",
        )
    ]


async def test_artifact_file_modal_Y_anchors_path_recovered_from_agent_meta_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    artifacts_dir = home / "artifacts"
    workspace = home / "workspace"
    source = workspace / "sdd" / "plans" / "202605" / "plan.md"
    artifacts_dir.mkdir(parents=True)
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

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal([artifact])
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("Y")
        await pilot.pause()

        assert pilot.app.screen is modal

    assert copied == ["~/workspace/sdd/plans/202605/plan.md"]


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
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
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
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
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


async def test_artifact_file_modal_copy_palette_copies_every_single_representation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    stored = home / "artifacts" / "report.md"
    source = home / "workspace" / "docs" / "report.md"
    stored.parent.mkdir(parents=True)
    source.parent.mkdir(parents=True)
    stored.write_text("# Stored\n", encoding="utf-8")
    source.write_text("# Source\nbody\n", encoding="utf-8")
    artifact = _artifact(
        7,
        label="Report [final].md",
        path=str(stored),
        source_path=str(source),
        workspace_dir=str(home / "workspace"),
        sha256="a" * 64,
        size_bytes=14,
        mime_type="text/markdown",
    )
    copied: list[str] = []

    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal([artifact])
        pilot.app.push_screen(modal)
        await pilot.pause()

        for key in ("@", "l", "c", "p", "P", "J"):
            await pilot.press("%")
            assert isinstance(pilot.app.screen, CopyAsModal)
            await pilot.press(key)
            await pilot.pause()
            assert pilot.app.screen is modal

    assert copied == [
        f"@file:{artifact.id}",
        f"[Report \\[final\\].md](file:{artifact.id})",
        "# Stored\n",
        "~/artifacts/report.md",
        "~/workspace/docs/report.md",
        json.dumps(artifact_file_json_dict(artifact), indent=2),
    ]


async def test_artifact_file_modal_copy_palette_formats_marked_sets_and_skips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_path = tmp_path / "first.md"
    second_path = tmp_path / "second.txt"
    first_path.write_text("# First\n", encoding="utf-8")
    second_path.write_text("second\n", encoding="utf-8")
    first = _artifact(
        1,
        label="First",
        path=str(first_path),
        source_path=str(first_path),
    )
    second = _artifact(
        2,
        label="Second",
        path=str(second_path),
        kind="file",
    )
    copied: list[str] = []
    notifications: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) or True,
    )

    async with _TestApp().run_test() as pilot:
        modal = ArtifactFileSelectionModal([first, second])
        modal.notify = (  # type: ignore[method-assign]
            lambda message, *, severity="information": notifications.append(
                (message, severity)
            )
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#agent-artifact-files-list", OptionList)
        option_list.highlighted = 0
        await pilot.press("m")
        option_list.highlighted = 1
        await pilot.press("m")

        for key in ("@", "l", "c", "P", "J"):
            await pilot.press("%", key)
            await pilot.pause()
            await _drain_clipboard_tasks(pilot.app)

    assert copied[0] == f"@file:{first.id}\n@file:{second.id}"
    assert copied[1] == (f"- [First](file:{first.id})\n- [Second](file:{second.id})")
    assert copied[2] == "### First\n```\n# First\n\n```"
    assert copied[3] == str(first_path)
    assert json.loads(copied[4]) == [
        artifact_file_json_dict(first),
        artifact_file_json_dict(second),
    ]
    assert (
        "Copied 1 artifact file's contents — 1 non-Markdown",
        "information",
    ) in notifications
    assert (
        "Copied 1 source path — 1 without a recorded source path",
        "information",
    ) in notifications


async def test_artifact_file_modal_copy_palette_disables_unavailable_contents_and_source(
    tmp_path: Path,
) -> None:
    artifact = _artifact(
        1,
        label="image.png",
        path=str(tmp_path / "image.png"),
        kind="image",
    )
    notifications: list[tuple[str, str]] = []

    async with _TestApp().run_test() as pilot:
        pilot.app.notify = (  # type: ignore[method-assign]
            lambda message, *, severity="information", **_kwargs: notifications.append(
                (message, severity)
            )
        )
        modal = ArtifactFileSelectionModal([artifact])
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("%")
        palette = pilot.app.screen
        assert isinstance(palette, CopyAsModal)
        rows = {row.target: row for row in palette.context.rows}
        assert rows["contents"].disabled_reason is not None
        assert rows["source_path"].preview == "not recorded"

        await pilot.press("c", "P")
        assert pilot.app.screen is palette
        await pilot.press("escape")
        await pilot.pause()

    assert notifications == [
        ("Contents copy is available only for Markdown files", "warning"),
        ("Artifact file source path was not recorded", "warning"),
    ]
