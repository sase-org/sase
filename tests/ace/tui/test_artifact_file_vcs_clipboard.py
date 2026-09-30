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


def test_materialize_entries_prefers_owning_project_over_launch_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    import subprocess
    from types import SimpleNamespace as _SimpleNamespace

    from sase.ace.tui.models.artifact_file_clipboard import (
        materialize_artifact_file_entries,
    )
    from sase.artifact_ref_models import ArtifactRefRepository

    def _git(repo: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    wrong_repo = tmp_path / "wrong"
    wrong_repo.mkdir()
    _git(wrong_repo, "init")
    _git(wrong_repo, "config", "user.email", "test@example.com")
    _git(wrong_repo, "config", "user.name", "Test")
    (wrong_repo / "other.txt").write_text("wrong", encoding="utf-8")
    _git(wrong_repo, "add", "other.txt")
    _git(wrong_repo, "commit", "-m", "wrong")

    right_repo = tmp_path / "right"
    right_repo.mkdir()
    _git(right_repo, "init")
    _git(right_repo, "config", "user.email", "test@example.com")
    _git(right_repo, "config", "user.name", "Test")
    content = "# owner report\n"
    (right_repo / "docs").mkdir()
    (right_repo / "docs" / "report.md").write_text(content, encoding="utf-8")
    _git(right_repo, "add", "docs/report.md")
    _git(right_repo, "commit", "-m", "right")
    sha = _git(right_repo, "rev-parse", "HEAD")

    monkeypatch.setattr(
        "sase.core.artifact_file_vcs.default_artifact_files_root",
        lambda: tmp_path / "artifacts",
    )

    wrong_context = _SimpleNamespace(
        repositories=(
            ArtifactRefRepository(
                "research",
                checkout_path=wrong_repo,
                checkout_paths=(wrong_repo,),
            ),
        )
    )
    monkeypatch.setattr(
        "sase.artifact_ref_context.launch_artifact_ref_context",
        lambda **_kwargs: wrong_context,
    )

    def fake_owner(*, project, workspace_num):  # type: ignore[no-untyped-def]
        assert project == "owner-project"
        return (
            ArtifactRefRepository(
                "research",
                checkout_path=right_repo,
                checkout_paths=(right_repo,),
            ),
        )

    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_repositories",
        fake_owner,
    )

    row = ArtifactFile(
        id="default:vcs",
        label="Report",
        kind="markdown",
        path=None,
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content.encode()),
        mime_type="text/markdown",
        vcs_repo="research",
        vcs_sha=sha,
        vcs_relpath="docs/report.md",
        project="owner-project",
    )

    (resolved,) = materialize_artifact_file_entries((row,))
    assert Path(resolved.path or "").read_text(encoding="utf-8") == content


def test_materialize_entries_oserror_includes_owning_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.models.artifact_file_clipboard import (
        materialize_artifact_file_entries,
    )
    from types import SimpleNamespace as _SimpleNamespace

    import pytest as _pytest

    monkeypatch.setattr(
        "sase.core.artifact_file_vcs.default_artifact_files_root",
        lambda: tmp_path / "artifacts",
    )
    empty_context = _SimpleNamespace(repositories=())
    monkeypatch.setattr(
        "sase.artifact_ref_context.launch_artifact_ref_context",
        lambda **_kwargs: empty_context,
    )
    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_repositories",
        lambda *, project, workspace_num: (),
    )

    row = ArtifactFile(
        id="default:vcs",
        label="Report",
        kind="markdown",
        path=None,
        sha256="a" * 64,
        size_bytes=4,
        mime_type="text/markdown",
        vcs_repo="research",
        vcs_sha="b" * 40,
        vcs_relpath="docs/missing.md",
        project="owner-project",
    )

    with _pytest.raises(OSError, match=r"\(project owner-project\)"):
        materialize_artifact_file_entries((row,))
