"""VCS-backed artifact-file coverage for ACE clipboard surfaces."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.ace.tui.modals.artifact_files_modal_copying import ArtifactFileCopyingMixin
from sase.ace.tui.modals.artifact_files_modal_rendering import (
    artifact_file_stored_clipboard_path,
)
from sase.artifact_ref_models import ArtifactRefRepository
from sase.core.artifact_file_types import ArtifactFile
from tests.ace.tui._artifacts_copy_helpers import CopyHarness


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _vcs_row(tmp_path: Path) -> tuple[Path, ArtifactFile, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    source = repo / "docs" / "report.md"
    source.parent.mkdir()
    content = "# exact report\n"
    source.write_text(content, encoding="utf-8")
    _git(repo, "add", "docs/report.md")
    _git(repo, "commit", "-m", "add report")
    row = ArtifactFile(
        id="default:vcs",
        label="Tracked report",
        kind="markdown",
        path=None,
        source_path=str(source),
        workspace_dir=str(repo),
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content.encode()),
        mime_type="text/markdown",
        vcs_repo="sase",
        vcs_sha=_git(repo, "rev-parse", "HEAD"),
        vcs_relpath="docs/report.md",
    )
    return repo, row, content


def _install_materialization_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repo: Path,
) -> None:
    repository = ArtifactRefRepository(
        "sase",
        checkout_path=repo,
        checkout_paths=(repo,),
    )
    context = SimpleNamespace(repositories=(repository,))
    monkeypatch.setattr(
        "sase.artifact_ref_context.launch_artifact_ref_context",
        lambda **_kwargs: context,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_vcs.default_artifact_files_root",
        lambda: tmp_path / "artifacts",
    )


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
    app.files_pane = _files_pane(row)
    app._artifacts_marked_targets = {"files": {target}}

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
