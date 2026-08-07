"""Agents-tab picker coverage for byte-free (VCS-backed) artifact rows.

Regression coverage for the crash where pressing <enter> on a byte-free row
(``path=None`` with VCS provenance) fed ``None`` straight into the viewer
instead of materializing bytes first.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.graphics import ArtifactFileViewerResult
from sase.ace.tui.modals import ArtifactFileSelectionResult
from sase.core.artifact_file_facade import ArtifactFile
from tests.ace.tui._artifact_file_vcs_fixtures import (
    install_materialization_context,
    vcs_row,
)

from ._artifact_file_image_helpers import _ImageActionApp, _decoration_state

_MATERIALIZE_TARGET = (
    "sase.ace.tui.models.artifact_file_clipboard.materialize_artifact_file_entries"
)


def _vcs_row(name: str = "chart.png") -> ArtifactFile:
    return ArtifactFile(
        id=f"vcs:{name}",
        label=name,
        kind="image",
        path=None,
        vcs_repo="sase",
        vcs_sha="deadbeef",
        vcs_relpath=f"tests/ace/tui/visual/snapshots/png/{name}",
    )


def test_agents_open_artifact_files_materializes_byte_free_row_before_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    row = _vcs_row()
    cached = tmp_path / "cache.png"
    cached.write_bytes(b"\x89PNG\r\n\x1a\n")

    def fake_materialize(entries):
        assert tuple(entries) == (row,)
        return tuple(replace(entry, path=str(cached)) for entry in entries)

    monkeypatch.setattr(_MATERIALIZE_TARGET, fake_materialize)

    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [row]

    calls: list[object] = []

    def fake_viewer(viewed_artifact) -> ArtifactFileViewerResult:
        calls.append(viewed_artifact)
        assert viewed_artifact.path is not None
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file", fake_viewer
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(row)

    assert len(calls) == 1
    assert calls[0].path == str(cached)
    app.notify.assert_not_called()
    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifact_files_materialize_oserror_notifies_and_restores_focus(
    monkeypatch,
) -> None:
    row = _vcs_row()

    def fake_materialize(entries):
        raise OSError(f"content unavailable for {row.vcs_repo}@{row.vcs_sha}:x")

    monkeypatch.setattr(_MATERIALIZE_TARGET, fake_materialize)

    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [row]

    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr("sase.ace.tui.graphics.view_registered_artifact_file", viewer)

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(row)

    viewer.assert_not_called()
    app.notify.assert_called_once_with(
        "Could not open artifact file: content unavailable for sase@deadbeef:x",
        severity="warning",
    )
    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifact_files_marked_zoom_materializes_and_forwards_zoom(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first = _vcs_row("first.png")
    second = _vcs_row("second.png")
    cached_first = tmp_path / "first-cached.png"
    cached_second = tmp_path / "second-cached.png"
    cached_first.write_bytes(b"\x89PNG\r\n\x1a\n")
    cached_second.write_bytes(b"\x89PNG\r\n\x1a\n")

    def fake_materialize(entries):
        mapping = {first.id: cached_first, second.id: cached_second}
        return tuple(replace(entry, path=str(mapping[entry.id])) for entry in entries)

    monkeypatch.setattr(_MATERIALIZE_TARGET, fake_materialize)

    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [first, second]

    calls: list[tuple[list[object], bool]] = []

    def fake_tmux_viewer(selected_artifacts, *, zoom: bool = False):
        calls.append((list(selected_artifacts), zoom))
        return ArtifactFileViewerResult(True, pane_id="%7")

    from sase.ace.tui.graphics import TmuxPaneDecorationResult

    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists", lambda _pane_id: True
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_files_in_tmux_pane",
        fake_tmux_viewer,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.decorate_artifact_file_tmux_panes",
        lambda _pane_id: TmuxPaneDecorationResult(True, state=_decoration_state()),
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(ArtifactFileSelectionResult([first, second], zoom=True))

    assert len(calls) == 1
    materialized_artifacts, zoom = calls[0]
    assert zoom is True
    assert {a.path for a in materialized_artifacts} == {
        str(cached_first),
        str(cached_second),
    }
    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifact_files_with_stored_paths_skips_materialization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "visible.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    artifact = ArtifactFile(
        id="stored",
        label="Image",
        kind="image",
        path=str(image),
    )

    materialize = MagicMock()
    monkeypatch.setattr(_MATERIALIZE_TARGET, materialize)
    spawn = MagicMock(return_value=None)
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._panel_artifact_files.spawn_pump_free_task",
        spawn,
    )

    app = _ImageActionApp(str(image))
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [artifact]

    calls: list[object] = []
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file",
        lambda viewed: calls.append(viewed) or ArtifactFileViewerResult(True),
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifact)

    assert calls == [artifact]
    materialize.assert_not_called()
    spawn.assert_not_called()
    app.agent_list.focus.assert_called_once_with()


async def test_agents_open_artifact_files_byte_free_row_spawns_pump_free_task(
    tmp_path: Path,
    monkeypatch,
) -> None:
    row = _vcs_row()
    cached = tmp_path / "cache.png"
    cached.write_bytes(b"\x89PNG\r\n\x1a\n")

    def fake_materialize(entries):
        return tuple(replace(entry, path=str(cached)) for entry in entries)

    monkeypatch.setattr(_MATERIALIZE_TARGET, fake_materialize)

    captured: list[object] = []

    def capture_task(_owner, coro, **_kwargs):
        captured.append(coro)
        return object()

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._panel_artifact_files.spawn_pump_free_task",
        capture_task,
    )

    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [row]

    calls: list[object] = []
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file",
        lambda viewed: calls.append(viewed) or ArtifactFileViewerResult(True),
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(row)

    assert len(captured) == 1
    await captured[0]

    assert len(calls) == 1
    assert calls[0].path == str(cached)
    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifact_files_resolves_real_bytes_from_vcs_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: real git materialization, not a mocked stand-in."""

    repo, row, content = vcs_row(tmp_path, kind="markdown")
    install_materialization_context(monkeypatch, tmp_path, repo)

    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [row]

    calls: list[object] = []
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file",
        lambda viewed: calls.append(viewed) or ArtifactFileViewerResult(True),
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(row)

    assert len(calls) == 1
    materialized_path = Path(calls[0].path)
    assert materialized_path.is_relative_to(tmp_path / "artifacts" / "vcs-cache")
    assert materialized_path.read_text(encoding="utf-8") == content
    app.agent_list.focus.assert_called_once_with()
