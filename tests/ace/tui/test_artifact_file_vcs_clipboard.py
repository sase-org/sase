"""VCS-backed artifact-file coverage for ACE clipboard surfaces."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.modals.artifact_files_modal_copying import ArtifactFileCopyingMixin
from sase.ace.tui.modals.artifact_files_modal_rendering import (
    artifact_file_stored_clipboard_path,
)
from sase.core.artifact_file_types import ArtifactFile
from tests.ace.tui._artifact_file_vcs_fixtures import (
    install_materialization_context as _install_materialization_context,
    vcs_row as _vcs_row,
)
from tests.ace.tui._artifacts_copy_helpers import CopyHarness


def _files_pane(row: ArtifactFile) -> SimpleNamespace:
    target = ("file", row.id)
    snapshot = SimpleNamespace(
        display_name="sase",
        view_mode_for=lambda _entry: "markdown",
    )
    return SimpleNamespace(
        selected_entry=row,
        selected_view_mode="markdown",
        selected_entry_target=lambda: target,
        entry_targets=lambda: (target,),
        entries_for_targets=lambda targets: (row,) if target in targets else (),
        project_scope="sase",
        project_file="/tmp/sase.sase",
        snapshot=snapshot,
    )


def test_copy_as_path_and_contents_materialize_vcs_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, row, content = _vcs_row(tmp_path)
    _install_materialization_context(monkeypatch, tmp_path, repo)
    app = CopyHarness()
    app.current_artifacts_subtab = "files"
    app.files_pane = _files_pane(row)

    assert app._handle_copy_key("p") is True
    assert app._handle_copy_key("percent_sign") is True

    copied_path = Path(app.copies[0][0]).expanduser()
    assert copied_path.read_text(encoding="utf-8") == content
    assert copied_path.is_relative_to(tmp_path / "artifacts" / "vcs-cache")
    assert app.copies[1][0] == content


def test_marked_copy_contents_uses_snapshot_mode_and_materializes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, row, content = _vcs_row(tmp_path)
    _install_materialization_context(monkeypatch, tmp_path, repo)
    target = ("file", row.id)
    app = CopyHarness()
    app.current_artifacts_subtab = "files"
    app.current_files_subtab = "other"
    app.files_pane = _files_pane(row)
    app._artifacts_marked_targets = {"other": {target}}

    assert app._handle_copy_key("percent_sign") is True

    copied, message = app.copies[0]
    assert copied == f"### {row.label}\n```\n{content}\n```"
    assert message == "Copied 1 artifact-file contents"


def test_picker_path_and_contents_materialize_vcs_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, row, content = _vcs_row(tmp_path)
    _install_materialization_context(monkeypatch, tmp_path, repo)

    copied_path = artifact_file_stored_clipboard_path(row)
    copied_contents = ArtifactFileCopyingMixin._read_artifact_file_contents(row)

    assert copied_path is not None
    assert Path(copied_path.text).expanduser().read_text(encoding="utf-8") == content
    assert copied_contents == content
