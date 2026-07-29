"""Tests for the preview reader's path-based viewer hand-off."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from collections.abc import Iterator

import pytest

from sase.ace.tui.actions import artifact_viewer_handoff
from sase.ace.tui.graphics import ArtifactFileViewerResult


def test_open_artifact_path_tracks_a_tmux_pane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewed: list[object] = []
    tracked: list[str] = []
    app = SimpleNamespace(
        _track_artifact_file_tmux_pane=tracked.append,
        notify=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(artifact_viewer_handoff, "is_tmux_session", lambda: True)
    monkeypatch.setattr(
        artifact_viewer_handoff,
        "view_artifact_files_in_tmux_pane",
        lambda specs: (
            viewed.extend(specs) or ArtifactFileViewerResult(True, pane_id="%7")
        ),
    )

    artifact_viewer_handoff.open_artifact_path(app, "/tmp/plan.md")

    assert [str(spec.path) for spec in viewed] == ["/tmp/plan.md"]
    assert tracked == ["%7"]


def test_open_artifact_path_suspends_and_surfaces_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoffs: list[dict[str, object]] = []
    notifications: list[tuple[str, str]] = []

    @contextmanager
    def fake_suspend(_app: object, **metadata: object) -> Iterator[None]:
        handoffs.append(metadata)
        yield

    app = SimpleNamespace(
        notify=lambda message, *, severity: notifications.append((message, severity))
    )
    monkeypatch.setattr(artifact_viewer_handoff, "is_tmux_session", lambda: False)
    monkeypatch.setattr(
        artifact_viewer_handoff,
        "suspend_for_external_tool",
        fake_suspend,
    )
    monkeypatch.setattr(
        artifact_viewer_handoff,
        "view_artifact_file",
        lambda path: ArtifactFileViewerResult(
            False,
            warning=f"Unable to view {path}",
        ),
    )

    artifact_viewer_handoff.open_artifact_path(app, "/tmp/plan.md")

    assert handoffs == [
        {
            "action": "preview_viewer_handoff",
            "tool_kind": "artifact_file_viewer",
            "path_count": 1,
            "status_message": "Opening preview in artifact viewer…",
        }
    ]
    assert notifications == [("Unable to view /tmp/plan.md", "warning")]
